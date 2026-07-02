import time
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END

from src import retriever
from src.generator.state import GeneratorState
from src.generator.context_router import analyze_context, rewrite_query
from src.generator.context_builder import build_context
from src.generator.generator_agent import generate_answer
from src.generator.verifier_agent import verify_answer

# --- Node Functions ---

async def route_context_node(state: GeneratorState) -> dict:
    query = state["query"]
    history = state["history"]
    last_retrieval = state.get("retrieval_result")
    
    # Check if we can reuse the existing retrieval context
    can_reuse = await analyze_context(query, history, last_retrieval)
    
    if can_reuse and last_retrieval:
        print("[GeneratorGraph] ContextRouter: Cache Hit. Reusing previous retrieval context.")
        return {
            "bypassed_retrieval": True,
            "retrieval_result": last_retrieval
        }
    else:
        print("[GeneratorGraph] ContextRouter: Cache Miss / New Search Required.")
        # Rewrite query to standalone search query
        rewritten = await rewrite_query(query, history)
        # Execute fresh retrieval
        fresh_res = await retriever.query(rewritten)
        return {
            "bypassed_retrieval": False,
            "retrieval_result": fresh_res,
            "query": rewritten # Update query to rewritten for prompt grounding
        }

async def build_context_node(state: GeneratorState) -> dict:
    retrieval_result = state["retrieval_result"]
    context_str = build_context(retrieval_result)
    return {"context_str": context_str}

async def generate_answer_node(state: GeneratorState) -> dict:
    query = state["query"]
    history = state["history"]
    context_str = state["context_str"]
    retry_count = state.get("retry_count", 0)
    
    feedback = None
    if retry_count > 0 and state.get("verification"):
        feedback = "\n".join(state["verification"]["issues"])
        print(f"[GeneratorGraph] GeneratorAgent: Retrying with verifier feedback:\n{feedback}")
    else:
        print("[GeneratorGraph] GeneratorAgent: Generating answer...")
        
    raw_ans = await generate_answer(query, history, context_str, feedback)
    return {"raw_answer": raw_ans}

async def verify_answer_node(state: GeneratorState) -> dict:
    raw_ans = state["raw_answer"]
    retrieval_res = state["retrieval_result"]
    context_str = state["context_str"]
    bypassed = state.get("bypassed_retrieval", False)
    query = state["query"]
    history = state["history"]
    
    # Edge Case 1: Insufficient context escape hatch
    if raw_ans.strip().startswith("INSUFFICIENT_CONTEXT"):
        if bypassed:
            print("[GeneratorGraph] VerifierAgent: Insufficient Context detected on Cache Hit. Forcing fresh retrieval.")
            # Trigger fresh retrieval
            rewritten = await rewrite_query(query, history)
            fresh_res = await retriever.query(rewritten)
            return {
                "bypassed_retrieval": False,
                "retrieval_result": fresh_res,
                "query": rewritten
            }
        else:
            print("[GeneratorGraph] VerifierAgent: Insufficient Context detected after fresh retrieval. Terminating.")
            return {
                "verification": {
                    "passed": True,
                    "score": 1.0,
                    "grounded_claims": 0,
                    "ungrounded_claims": 0,
                    "issues": []
                },
                "citations": []
            }
            
    print("[GeneratorGraph] VerifierAgent: Verifying groundedness (Threshold: 0.90)...")
    report, citations = await verify_answer(raw_ans, retrieval_res, context_str)
    print(f"[GeneratorGraph] VerifierAgent: Score={report['score']}, Passed={report['passed']}")
    
    # Increment retry counter if failed
    new_retry = state.get("retry_count", 0)
    if not report["passed"] and new_retry == 0:
        new_retry = 1
        
    return {
        "verification": report,
        "citations": citations,
        "retry_count": new_retry
    }

async def finalize_node(state: GeneratorState) -> dict:
    raw_ans = state["raw_answer"]
    report = state["verification"]
    
    final_ans = raw_ans
    # Edge Case 2: Verification fails twice -> append warning
    if not report["passed"]:
        warning_block = "\n\n[LOW CONFIDENCE - UNVERIFIED CLAIMS DETECTED]\n"
        for issue in report["issues"]:
            warning_block += f"- {issue}\n"
        final_ans = raw_ans + warning_block
        print("[GeneratorGraph] VerifierAgent: Answer failed verification twice. Warning appended.")
        
    return {"final_answer": final_ans}

# --- Routing logic ---

def route_after_verification(state: GeneratorState) -> str:
    raw_ans = state["raw_answer"]
    bypassed = state.get("bypassed_retrieval", False)
    
    # Escape hatch
    if raw_ans.strip().startswith("INSUFFICIENT_CONTEXT"):
        if bypassed:
            return "build_context" # loop back with fresh retrieval result
        else:
            return "finalize"
            
    report = state["verification"]
    retry_count = state.get("retry_count", 0)
    
    if report["passed"]:
        return "finalize"
    elif retry_count == 1:
        # This means we just failed the first attempt and updated retry_count = 1
        # Loop back to generate_answer node
        return "generate_answer"
    else:
        # Fails twice, go to finalize
        return "finalize"

# --- Define graph ---

builder = StateGraph(GeneratorState)

builder.add_node("route_context", route_context_node)
builder.add_node("build_context", build_context_node)
builder.add_node("generate_answer", generate_answer_node)
builder.add_node("verify_answer", verify_answer_node)
builder.add_node("finalize", finalize_node)

builder.set_entry_point("route_context")

builder.add_edge("route_context", "build_context")
builder.add_edge("build_context", "generate_answer")
builder.add_edge("generate_answer", "verify_answer")

builder.add_conditional_edges(
    "verify_answer",
    route_after_verification,
    {
        "build_context": "build_context",
        "generate_answer": "generate_answer",
        "finalize": "finalize"
    }
)

builder.add_edge("finalize", END)

COMPILED_GRAPH = builder.compile()
