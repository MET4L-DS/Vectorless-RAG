import time
from typing import List, Dict, Any
from src.generator.state import GeneratorState
from src.generator.graph import COMPILED_GRAPH
from src.retriever.state import RetrievalResult

async def generate(
    query: str,
    history: List[Dict[str, str]],
    last_retrieval: RetrievalResult | None = None
) -> Dict[str, Any]:
    """
    Public API entry point for Phase 4 Generative & Verifier flow.
    Evaluates context router, routes, builds context, generates, and verifies.
    """
    start_time = time.time()
    
    initial_state: GeneratorState = {
        "query": query,
        "history": history,
        "retrieval_result": last_retrieval or {"primary": [], "supporting": [], "citations": [], "sources": [], "query_metadata": {}},
        "context_str": "",
        "raw_answer": "",
        "citations": [],
        "verification": {"passed": False, "score": 0.0, "grounded_claims": 0, "ungrounded_claims": 0, "issues": []},
        "final_answer": "",
        "retry_count": 0,
        "bypassed_retrieval": False,
        "error": None,
        "latency_ms": 0
    }
    
    final_state = await COMPILED_GRAPH.ainvoke(initial_state)
    
    latency = round((time.time() - start_time) * 1000)
    
    return {
        "answer": final_state.get("final_answer", ""),
        "citations": final_state.get("citations", []),
        "confidence": final_state.get("verification", {}).get("score", 0.0),
        "verification": final_state.get("verification"),
        "retrieval": final_state.get("retrieval_result"),
        "latency_ms": latency
    }
