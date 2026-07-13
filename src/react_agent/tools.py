import contextvars
from typing import Literal, List, Optional
from langchain_core.tools import tool
from src.retriever import graph
from src.retriever.state import RetrievedNode
from langgraph.config import get_stream_writer

# ContextVar to collect retrieved nodes dynamically across tool executions for CLI/serve metadata
retrieved_nodes_var = contextvars.ContextVar("retrieved_nodes", default=None)

def emit_status(message: str):
    """Helper to safely stream custom status updates to LangGraph if running in an execution context."""
    try:
        writer = get_stream_writer()
        writer({"message": message})
    except Exception:
        # Failsafe for direct unit testing outside LangGraph context
        pass


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
    return "\n---\n" + "\n---\n".join(formatted)

@tool
async def search_statutes(
    statute_code: Literal["BNS", "BNSS", "BSA", "IT", "JJA", "POCSO", "NDPS", "PCA"],
    query: str,
    method: Literal["tree", "bm25", "hybrid"] = "hybrid"
) -> str:
    """
    Searches a specific Indian statutory act for sections relevant to a query.
    Use this when you need legal definitions, criminal offences, punishments, or procedures.

    Parameters:
    - statute_code:
      - 'BNS'   (Bharatiya Nyaya Sanhita 2023 — criminal offences, penalties, murder, robbery, fraud)
      - 'BNSS'  (Bharatiya Nagarik Suraksha Sanhita 2023 — trial procedure, arrests, bail, FIRs)
      - 'BSA'   (Bharatiya Sakshya Adhiniyam 2023 — evidence, witnesses, confessions, burden of proof)
      - 'IT'    (Information Technology Act 2000 — cyber crimes, digital evidence, electronic records,
                 computer offences, identity theft, cyber terrorism, data protection)
      - 'JJA'   (Juvenile Justice Act 2015 — juvenile offenders, child welfare boards, children in
                 conflict with law, adoption, rehabilitation)
      - 'POCSO' (Protection of Children from Sexual Offences Act 2012 — child sexual assault,
                 aggravated offences, special courts, child testimony procedure)
      - 'NDPS'  (Narcotic Drugs and Psychotropic Substances Act 1985 — narcotics offences,
                 controlled substances, bail conditions, forfeiture of property)
      - 'PCA'   (Prevention of Corruption Act 1988 — bribery, public servant corruption,
                 undue advantage, special courts, sanction for prosecution)
    - query: Specific keywords, section numbers, or legal scenario to search.
    - method: Search methodology ('tree' for hierarchical navigation, 'bm25' for keyword search,
              'hybrid' for both — recommended).
    """
    if not graph._corpus_index:
        return "Error: Corpus index not initialized. Ensure retriever.load() has been called."

    nodes = []
    seen_ids = set()

    # 1. Tree Navigation (guided search)
    if method in ["tree", "hybrid"] and graph._tree_navigator:
        try:
            emit_status(f"🌲 Navigating chapter tree for {statute_code}...")
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
            emit_status(f"🔍 Searching {statute_code} BM25 index...")
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

    emit_status(f"⚡ Completed search for {statute_code}")
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
        emit_status("📋 Searching Police SOP manual...")
        nodes = await graph._sop_retriever.retrieve(query, top_k=5)
        emit_status("⚡ Completed SOP search")
        return _format_nodes(nodes)
    except Exception as e:
        return f"Error searching Police SOP: {e}"

@tool
async def enrich_with_cross_references(section_id: str) -> str:
    """
    Fetches other legal sections that are cross-referenced or linked to a specific section ID
    (e.g., 'BNSS_S35', 'IT_S66', 'POCSO_S28').
    Use this when you have retrieved a section and want to follow its legal citations to other
    acts or sections (for example, connecting a police procedure to a BNSS section, or a
    POCSO special court provision to a BNSS trial procedure section).
    """
    if not graph._cross_ref_linker or not graph._corpus_index:
        return "Error: Cross-reference linker not initialized."

    node = graph._corpus_index.get_node(section_id)
    if not node:
        return f"Error: Legal section '{section_id}' not found in the index."

    act_code = section_id.split("_")[0]
    p_node: RetrievedNode = {
        "node_id":          section_id,
        "act_code":         act_code,
        "title":            node.get("title", ""),
        "summary":          node.get("summary", ""),
        "content":          node.get("content", ""),
        "score":            1.0,
        "node_type":        node.get("node_type", "section"),
        "page_range":       node.get("metadata", {}).get("page_range", []),
        "cross_act_refs":   node.get("metadata", {}).get("cross_act_refs", []),
        "internal_refs":    node.get("metadata", {}).get("internal_refs", []),
        "retrieval_method": "direct_lookup"
    }

    try:
        emit_status(f"🔗 Resolving cross-references for {section_id}...")
        enriched_nodes = graph._cross_ref_linker.enrich([p_node], max_links_per_node=5)
        emit_status(f"⚡ Completed cross-reference resolution for {section_id}")
        return _format_nodes(enriched_nodes)
    except Exception as e:
        return f"Error resolving cross references: {e}"


@tool
async def find_case_law_for_section(section_id: str) -> str:
    """
    [Phase 10 — Scaffold] Finds judicial precedents (case law) that have interpreted or
    applied a specific statutory section.
    Use when the user asks how courts have applied, interpreted, or challenged a particular
    statutory provision (e.g. 'Has the Supreme Court ruled on NDPS Section 37 bail?').

    Parameters:
    - section_id: Node ID of the statutory section (e.g. 'BNSS_S35', 'NDPS_S37').
    """
    if not graph._corpus_index:
        return "Error: Corpus index not initialized."

    node = graph._corpus_index.get_node(section_id)
    if not node:
        return f"Error: Section '{section_id}' not found in the corpus index."

    case_ids: List[str] = node.get("metadata", {}).get("interpreted_by", [])
    if not case_ids:
        return (
            f"No case law nodes are currently linked to '{section_id}'. "
            "The judicial precedents corpus has not yet been loaded (Phase 10). "
            "Please answer based on the statutory text alone."
        )

    # Phase 10 will implement full retrieval here
    return f"[Phase 10 placeholder] Case law nodes linked to {section_id}: {case_ids}"
