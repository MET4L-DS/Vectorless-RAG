from typing import TypedDict, List, Dict, Any, Annotated
from operator import add
from src.retriever.state import RetrievedNode, RetrievalResult
from src.retriever.schemas import GeneratedAnswer

class Citation(TypedDict):
    node_id: str          # e.g., "BNSS_S35"
    act_code: str         # e.g., "BNSS"
    title: str            # e.g., "35. When police may arrest without warrant"
    quoted_text: str      # Exact or near-exact matched text snippet
    page_range: List[int]

class VerificationReport(TypedDict):
    passed: bool
    score: float          # Fraction of claims successfully grounded
    grounded_claims: int
    ungrounded_claims: int
    issues: List[str]     # Free-text audit comments

class GeneratorState(TypedDict):
    query: str
    history: List[Dict[str, str]]       # Conversation history: [{"user": "...", "assistant": "..."}]
    retrieval_result: RetrievalResult  # The retrieval context (either new or persisted)
    context_str: str                   # Formatted context passed to LLM
    raw_answer: str                    # Raw LLM answer
    generated: GeneratedAnswer | None         # Structured LLM output
    citations: List[Citation]
    verification: VerificationReport
    final_answer: str                  # Post-verification final answer
    retry_count: int                   # Verification correction loop count (max 1)
    bypassed_retrieval: bool           # Track if retrieval was bypassed
    error: str | None
    latency_ms: int

