from typing import TypedDict, Annotated
from operator import add

class RetrievedNode(TypedDict):
    node_id: str
    act_code: str
    title: str
    summary: str
    content: str | None          # Only populated for leaf nodes
    score: float
    node_type: str
    page_range: list[int]
    cross_act_refs: list[dict]
    internal_refs: list[str]
    retrieval_method: str         # "bm25" | "tree_navigation" | "cross_ref"

class AgentState(TypedDict):
    query: str
    target_corpora: Annotated[list[str], add]  # reducer: merge lists from parallel nodes
    query_type: str                            # e.g., "procedure", "statute", "both"
    bm25_hits: Annotated[list[RetrievedNode], add]
    tree_hits: Annotated[list[RetrievedNode], add]
    cross_ref_hits: Annotated[list[RetrievedNode], add]
    final_results: list[RetrievedNode]
    metadata: dict
    error: str | None
    iteration_count: int          # loop guard

class RetrievalResult(TypedDict):
    primary: list[RetrievedNode]    # Top hits (e.g. top 5)
    supporting: list[RetrievedNode] # Context hits (e.g. next 10)
    citations: list[str]            # Compact list of source node_ids/titles
    sources: list[str]              # Human-readable list of acts/sections
    query_metadata: dict            # Latency, hits count, etc.
