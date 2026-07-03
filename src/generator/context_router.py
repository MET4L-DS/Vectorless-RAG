from typing import List, Dict
from src.retriever.client import call_model_with_retry, call_model_structured
from src.retriever.state import RetrievalResult
from src.retriever.schemas import CacheDecision, RewrittenQuery

def format_history(history: List[Dict[str, str]]) -> str:
    if not history:
        return "None"
    formatted = []
    for turn in history:
        u = turn.get("user", "")
        a = turn.get("assistant", "")
        formatted.append(f"User: {u}\nAssistant: {a}")
    return "\n---\n".join(formatted)

def format_retrieval_catalog(retrieval: RetrievalResult) -> str:
    catalog = []
    # Include primary nodes
    for idx, node in enumerate(retrieval.get("primary", [])):
        catalog.append(f"ID: {node['node_id']} (Primary)\nTitle: {node['title']}\nSummary: {node['summary']}")
    # Include supporting nodes
    for idx, node in enumerate(retrieval.get("supporting", [])):
        catalog.append(f"ID: {node['node_id']} (Supporting)\nTitle: {node['title']}\nSummary: {node['summary']}")
    
    if not catalog:
        return "No retrieved documents in context."
    return "\n---\n".join(catalog)

async def analyze_context(query: str, history: List[Dict[str, str]], last_retrieval: RetrievalResult | None) -> bool:
    """
    Decides if the current query can be answered using only the last retrieved context.
    Returns True if YES (bypass retrieval), False if NO.
    """
    if not last_retrieval:
        return False
        
    history_str = format_history(history)
    retrieved_catalog = format_retrieval_catalog(last_retrieval)
    
    prompt = f"""You are an intelligent legal query router.
Below is the conversation history:
{history_str}

We have already retrieved the following legal nodes from the database:
{retrieved_catalog}

User Query: "{query}"

Determine if this user query can be fully and accurately answered using ONLY the already retrieved legal nodes.
- If yes (e.g., it is a follow-up, clarification, or references the exact same sections), reply with YES.
- If no (e.g., it asks about a completely different act, procedure, or offence not covered by the retrieved nodes), reply with NO.
"""
    try:
        result: CacheDecision = await call_model_structured(prompt, CacheDecision)
        print(f"[ContextRouter] Router response: {result.can_reuse} (Reason: {result.reasoning})")
        return result.can_reuse
    except Exception as e:
        print(f"[ContextRouter] Error in analyze_context: {e}")
        
    return False

async def rewrite_query(query: str, history: List[Dict[str, str]]) -> str:
    """
    Reformulates a conversational query into a standalone query.
    """
    if not history:
        return query
        
    history_str = format_history(history)
    
    prompt = f"""You are a query rewriter for a legal RAG system.
Given the conversation history and the latest user query, reformulate the query into a standalone search query that contains all necessary names, legal terms, and context, making it suitable for a direct search index.

Conversation History:
{history_str}

User Query: "{query}"
"""
    try:
        result: RewrittenQuery = await call_model_structured(prompt, RewrittenQuery)
        print(f"[ContextRouter] Rewritten query: '{result.standalone_query}'")
        return result.standalone_query
    except Exception as e:
        print(f"[ContextRouter] Error in rewrite_query: {e}")
        
    return query

