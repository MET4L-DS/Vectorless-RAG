import time
import contextvars
from typing import List, Dict, Any

from langchain_core.messages import HumanMessage, AIMessage
from src.retriever import graph
from src.retriever.schemas import GeneratedAnswer
from src.react_agent.agent import COMPILED_AGENT
from src.react_agent.tools import retrieved_nodes_var

async def generate(
    query: str,
    history: List[Dict[str, str]],
    last_retrieval: Any = None
) -> Dict[str, Any]:
    """
    Public entry point for the ReAct Agent flow.
    Converts conversation history, invokes the agent reasoning loop, 
    gathers dynamic retrieval traces, and formats the output.
    """
    start_time = time.time()
    
    # 1. Format history to LangChain message objects
    messages = []
    for turn in history:
        user_text = turn.get("user", "")
        assistant_text = turn.get("assistant", "")
        # Clean [References] or warnings from assistant history to keep prompt clean
        cleaned_assistant = assistant_text.split("[References]")[0].strip()
        cleaned_assistant = cleaned_assistant.split("[LOW CONFIDENCE")[0].strip()
        
        messages.append(HumanMessage(content=user_text))
        messages.append(AIMessage(content=cleaned_assistant))
        
    messages.append(HumanMessage(content=query))
    
    # 2. Setup ContextVar to collect retrieved nodes during execution
    collected_nodes = []
    token = retrieved_nodes_var.set(collected_nodes)
    
    try:
        # We set a safe recursion limit (10 steps) to prevent runaway loops
        # and preserve gemini-3.1-flash-lite RPM quotas.
        final_state = await COMPILED_AGENT.ainvoke(
            {"messages": messages}, 
            config={"recursion_limit": 10}
        )
        
        generated: GeneratedAnswer = final_state.get("structured_response")
    except Exception as e:
        print(f"[ReAct Agent] Graph execution failed: {e}")
        generated = GeneratedAnswer(
            answer_text=f"An error occurred during ReAct reasoning: {e}",
            key_provisions=[],
            citations=[],
            is_insufficient_context=True
        )
    finally:
        # Clean up context var
        retrieved_nodes_var.reset(token)
        
    latency = round((time.time() - start_time) * 1000)
    
    # 3. Resolve citation dictionaries from keys
    citations_list = []
    if generated and generated.citations:
        for cid in generated.citations:
            node = graph._corpus_index.get_node(cid) if graph._corpus_index else None
            if node:
                citations_list.append({
                    "node_id": cid,
                    "act_code": cid.split("_")[0],
                    "title": node.get("title", ""),
                    "quoted_text": "",
                    "page_range": node.get("metadata", {}).get("page_range", [])
                })
                
    # 4. Construct final answer markdown exactly matching the state machine layout
    lines = []
    lines.append("[Answer]")
    lines.append(generated.answer_text)
    lines.append("")
    
    if generated.key_provisions:
        lines.append("[Key Provisions]")
        for provision in generated.key_provisions:
            p_strip = provision.strip()
            if not p_strip.startswith("-"):
                p_strip = f"- {p_strip}"
            lines.append(p_strip)
        lines.append("")
        
    if citations_list:
        lines.append("[References]")
        for idx, citation in enumerate(citations_list):
            lines.append(f"[{idx+1}] {citation['node_id']}: {citation['title']}")
            
    final_ans = "\n".join(lines).strip()
    
    # 5. Build RetrievalResult containing primary/supporting nodes and metadata
    primary_ids = {c["node_id"] for c in citations_list}
    primary_nodes = [n for n in collected_nodes if n["node_id"] in primary_ids]
    supporting_nodes = [n for n in collected_nodes if n["node_id"] not in primary_ids]
    
    # Deduplicate nodes
    def deduplicate(node_list):
        seen = set()
        res = []
        for n in node_list:
            if n["node_id"] not in seen:
                res.append(n)
                seen.add(n["node_id"])
        return res
        
    primary_nodes = deduplicate(primary_nodes)
    supporting_nodes = deduplicate(supporting_nodes)
    
    # Hydrate metadata counts based on what tools were invoked
    bm25_count = sum(1 for n in collected_nodes if n.get("retrieval_method") == "bm25")
    tree_count = sum(1 for n in collected_nodes if n.get("retrieval_method") == "tree_navigation")
    cross_ref_count = sum(1 for n in collected_nodes if "cross_ref" in n.get("retrieval_method", ""))
    
    retrieval_result = {
        "primary": primary_nodes,
        "supporting": supporting_nodes,
        "citations": citations_list,
        "sources": [n["node_id"] for n in primary_nodes],
        "query_metadata": {
            "target_corpora": list({n["act_code"] for n in collected_nodes}),
            "bm25_hits": bm25_count,
            "tree_hits": tree_count,
            "cross_ref_hits": cross_ref_count,
            "total_unique_hits": len(deduplicate(collected_nodes))
        }
    }
    
    # 6. Return standard dict contract matching generator.generate()
    # Confidence is 0.0 if insufficient context, 1.0 otherwise (no verifier check)
    confidence = 0.0 if generated.is_insufficient_context else 1.0
    
    return {
        "answer": final_ans,
        "citations": citations_list,
        "confidence": confidence,
        "verification": {
            "passed": not generated.is_insufficient_context,
            "score": confidence,
            "grounded_claims": len(citations_list),
            "ungrounded_claims": 0,
            "issues": []
        },
        "retrieval": retrieval_result,
        "latency_ms": latency
    }
