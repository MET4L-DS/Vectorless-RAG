import contextvars
from typing import Literal, List
from langchain_core.tools import tool
from src.retriever import graph
from src.retriever.state import RetrievedNode

# ContextVar to collect retrieved nodes dynamically across tool executions for CLI/serve metadata
retrieved_nodes_var = contextvars.ContextVar("retrieved_nodes", default=None)

def _format_nodes(nodes: List[RetrievedNode]) -> str:
    """Helper to format retrieved nodes for LLM observation."""
    if not nodes:
        return "No matching legal sections or procedures found."
    
    # Store in ContextVar if active
    collected = retrieved_nodes_var.get()
    if collected is not None:
        for node in nodes:
            if not any(x["node_id"] == node["node_id"] for x in collected):
                collected.append(node)
                
    formatted = []

    for node in nodes:
        fmt = (
            f"ID: {node['node_id']}\n"
            f"Act/Corpus: {node['act_code']}\n"
            f"Title: {node['title']}\n"
            f"Summary: {node.get('summary', '')}\n"
            f"Content:\n{node.get('content', '')}\n"
            f"Retrieval Method: {node.get('retrieval_method', 'unknown')}\n"
            f"Score: {node.get('score', 1.0):.2f}"
        )
        formatted.append(fmt)
    return "\n" + "="*50 + "\n" + ("\n" + "="*50 + "\n").join(formatted)

@tool
async def search_statutes(
    statute_code: Literal["BNS", "BNSS", "BSA"], 
    query: str, 
    method: Literal["tree", "bm25", "hybrid"] = "hybrid"
) -> str:
    """
    Searches a specific Indian statutory act (BNS, BNSS, or BSA) for sections relevant to a query.
    Use this when you need legal definitions, criminal offenses, punishments, or trial procedures.
    
    Parameters:
    - statute_code: 
      - 'BNS' (Bharatiya Nyaya Sanhita - Criminal offences, penalties, punishments, murder, robbery, etc.)
      - 'BNSS' (Bharatiya Nagarik Suraksha Sanhita - Criminal trial procedures, arrests, bail, FIRs, investigations)
      - 'BSA' (Bharatiya Sakshya Adhiniyam - Evidence act, witnesses, confessions, burden of proof)
    - query: Specific keywords, section numbers, or legal scenario to search.
    - method: Search methodology ('tree' for hierarchical navigation, 'bm25' for keyword search, 'hybrid' for both).
    """
    if not graph._corpus_index:
        return "Error: Corpus index not initialized. Ensure retriever.load() has been called."
        
    nodes = []
    seen_ids = set()
    
    # 1. Tree Navigation (guided search)
    if method in ["tree", "hybrid"] and graph._tree_navigator:
        try:
            tree_nodes = await graph._tree_navigator.navigate(query, statute_code)
            for n in tree_nodes:
                if n["node_id"] not in seen_ids:
                    nodes.append(n)
                    seen_ids.add(n["node_id"])
        except Exception as e:
            print(f"[Tool: search_statutes] Tree Nav failed: {e}")
            
    # 2. BM25 (keyword search)
    if method in ["bm25", "hybrid"] and graph._bm25_index:
        try:
            bm25_nodes = graph._bm25_index.search(
                query, 
                graph._corpus_index, 
                top_k=5, 
                act_filter=[statute_code]
            )
            for n in bm25_nodes:
                if n["node_id"] not in seen_ids:
                    nodes.append(n)
                    seen_ids.add(n["node_id"])
        except Exception as e:
            print(f"[Tool: search_statutes] BM25 failed: {e}")
            
    return _format_nodes(nodes)

@tool
async def search_police_sop(query: str) -> str:
    """
    Searches the Police Standard Operating Procedures (SOP) manual for operational guidelines, 
    patrol duties, checklists, timelines, and practical steps taken by police officers.
    Use this when the query relates to how a police officer should register an FIR, conduct an arrest, 
    handle electronic evidence, or maintain a police station diary.
    """
    if not graph._sop_retriever or not graph._corpus_index:
        return "Error: SOP retriever not initialized."
        
    try:
        nodes = await graph._sop_retriever.retrieve(query, top_k=5)
        return _format_nodes(nodes)
    except Exception as e:
        return f"Error searching Police SOP: {e}"

@tool
async def enrich_with_cross_references(section_id: str) -> str:
    """
    Fetches other legal sections that are cross-referenced or linked to a specific section ID (e.g., 'BNSS_S35').
    Use this when you have retrieved a section and want to follow its legal citations to other acts or sections
    (for example, connecting a police procedure in the SOP to a section in the BNSS).
    """
    if not graph._cross_ref_linker or not graph._corpus_index:
        return "Error: Cross-reference linker not initialized."
        
    node = graph._corpus_index.get_node(section_id)
    if not node:
        return f"Error: Legal section '{section_id}' not found in the index."
        
    # Construct a skeleton RetrievedNode representation for the linker to consume
    act_code = section_id.split("_")[0]
    p_node: RetrievedNode = {
        "node_id": section_id,
        "act_code": act_code,
        "title": node.get("title", ""),
        "summary": node.get("summary", ""),
        "content": node.get("content", ""),
        "score": 1.0,
        "node_type": node.get("node_type", "section"),
        "page_range": node.get("metadata", {}).get("page_range", []),
        "cross_act_refs": node.get("metadata", {}).get("cross_act_refs", []),
        "internal_refs": node.get("metadata", {}).get("internal_refs", []),
        "retrieval_method": "direct_lookup"
    }
    
    try:
        enriched_nodes = graph._cross_ref_linker.enrich([p_node], max_links_per_node=5)
        return _format_nodes(enriched_nodes)
    except Exception as e:
        return f"Error resolving cross references: {e}"
