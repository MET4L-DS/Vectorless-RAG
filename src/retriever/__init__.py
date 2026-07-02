import time
from typing import Dict, Any

from .corpus_index import CorpusIndex
from .bm25_index import BM25Index
from .graph import COMPILED_GRAPH, init_components
from .state import AgentState, RetrievalResult

_corpus_index = None
_bm25_index = None

def load(tree_dir: str = "tree"):
    """Initialize all indices. Must be called once before query()."""
    global _corpus_index, _bm25_index
    print(f"Loading Vectorless-RAG Retriever from {tree_dir}...")
    _corpus_index = CorpusIndex(tree_dir)
    _bm25_index = BM25Index()
    _bm25_index.load_or_build(_corpus_index, save_dir=f"{tree_dir}/bm25_index")
    
    # Inject components into the LangGraph nodes
    init_components(_corpus_index, _bm25_index)
    print("Retriever fully loaded and ready.")

async def query(question: str) -> RetrievalResult:
    """Execute the full retrieval pipeline for a question."""
    if not _corpus_index:
        raise RuntimeError("Retriever not loaded. Call load() first.")
        
    start_time = time.time()
        
    initial_state = AgentState(
        query=question,
        target_corpora=[],
        query_type="unknown",
        bm25_hits=[], 
        tree_hits=[], 
        cross_ref_hits=[],
        final_results=[], 
        error=None, 
        iteration_count=0
    )
    
    final_state = await COMPILED_GRAPH.ainvoke(initial_state)
    
    # We extracted the dict format in assemble_results_node to avoid strict schema issues
    metadata = final_state.get("metadata", {})
    if "query_metadata" not in metadata:
        metadata["query_metadata"] = {}
        
    metadata["query_metadata"]["total_latency_ms"] = round((time.time() - start_time) * 1000)
    metadata["query_metadata"]["target_corpora"] = final_state.get("target_corpora", [])
    
    # Safely return structured output
    result: RetrievalResult = {
        "primary": metadata.get("primary", []),
        "supporting": metadata.get("supporting", []),
        "citations": metadata.get("citations", []),
        "sources": metadata.get("sources", []),
        "query_metadata": metadata.get("query_metadata", {})
    }
    
    return result

def list_loaded_acts() -> list[str]:
    if not _corpus_index:
        return []
    return _corpus_index.list_acts()

def reload(act_code: str):
    if not _corpus_index:
        return
    _corpus_index.reload(act_code)
    # If the corpus changed, we should technically rebuild BM25, but 
    # for hot-reloading we'll skip it unless we add a full rebuild flag.
    print(f"Reloaded {act_code} into CorpusIndex.")
