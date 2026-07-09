import time
import re
from typing import List, cast
from langgraph.graph import StateGraph, END

from .state import AgentState
from .corpus_index import CorpusIndex
from .bm25_index import BM25Index
from .tree_navigator import TreeNavigator
from .sop_retriever import SOPRetriever
from .cross_ref_linker import CrossRefLinker
from .assembler import Assembler
from .client import call_model_with_retry, call_model_structured
from .schemas import IntentClassification

# Define Singletons that will be injected into nodes
_corpus_index = None
_bm25_index = None
_tree_navigator = None
_sop_retriever = None
_cross_ref_linker = None
_assembler = None

def init_components(corpus: CorpusIndex, bm25: BM25Index):
    global _corpus_index, _bm25_index, _tree_navigator, _sop_retriever, _cross_ref_linker, _assembler
    _corpus_index = corpus
    _bm25_index = bm25
    _tree_navigator = TreeNavigator(corpus)
    _sop_retriever = SOPRetriever(corpus)
    _cross_ref_linker = CrossRefLinker(corpus)
    _assembler = Assembler()

# --- Nodes ---

async def analyse_intent_node(state: AgentState) -> dict:
    query = state["query"]
    query_lower = query.lower()
    
    # 1. Fast Keyword Heuristic
    targets = set()
    if any(k in query_lower for k in ["bns", "punishment", "murder", "theft", "rape", "offence", "robbery"]):
        targets.add("BNS")
    if any(k in query_lower for k in ["bnss", "procedure", "warrant", "arrest", "fir", "bail", "court", "magistrate"]):
        targets.add("BNSS")
    if any(k in query_lower for k in ["bsa", "evidence", "witness", "testimony", "document"]):
        targets.add("BSA")
    if any(k in query_lower for k in ["sop", "police", "officer", "station", "diary", "investigate"]):
        targets.add("SOP")
    if any(k in query_lower for k in ["it act", "information technology", "hacking", "cyber", "electronic record", "digital signature"]):
        targets.add("IT")
    if any(k in query_lower for k in ["jja", "juvenile", "child welfare", "board", "conflict with law", "minor"]):
        # 'minor' can also apply to POCSO or BNS, but let's heuristically check both
        targets.add("JJA")
    if any(k in query_lower for k in ["pocso", "sexual offence", "child sexual", "penetrative"]):
        targets.add("POCSO")
    if any(k in query_lower for k in ["ndps", "drug", "narcotic", "psychotropic", "substance", "trafficking"]):
        targets.add("NDPS")
    if any(k in query_lower for k in ["pca", "corruption", "bribe", "public servant", "gratification", "sanction"]):
        targets.add("PCA")
        
    if not targets:
        # Fallback to LLM if ambiguous
        prompt = f"""You are a legal intent classifier.
User Query: "{query}"
Classify which of these Indian legal documents might contain the answer:
- BNS (Bharatiya Nyaya Sanhita — Criminal Code / Offences / Punishments)
- BNSS (Bharatiya Nagarik Suraksha Sanhita — Criminal Procedure / Arrest / Trial)
- BSA (Bharatiya Sakshya Adhiniyam — Evidence Act)
- SOP (Police Standard Operating Procedures)
- IT (Information Technology Act — Cyber crimes, digital evidence, data protection)
- JJA (Juvenile Justice Act — Juvenile offenders, child welfare, adoption)
- POCSO (Protection of Children from Sexual Offences Act — Child sexual offences)
- NDPS (Narcotic Drugs and Psychotropic Substances Act — Narcotics, bail)
- PCA (Prevention of Corruption Act — Bribery, public servant corruption)
"""
        try:
            result: IntentClassification = await call_model_structured(prompt, IntentClassification)
            targets = set(result.target_corpora)
            print(f"[Router] Query was ambiguous. LLM Classifier selected: {list(targets)} (Reason: {result.reasoning})")
        except Exception as e:
            print(f"[Router] Error in LLM intent classification: {e}. Falling back to searching all.")
            targets = {"BNS", "BNSS", "BSA", "SOP", "IT", "JJA", "POCSO", "NDPS", "PCA"}
    else:
        print(f"[Router] Query matched keyword heuristics. Target corpora: {list(targets)}")
        
    # If still nothing, search all
    if not targets:
        targets = {"BNS", "BNSS", "BSA", "SOP", "IT", "JJA", "POCSO", "NDPS", "PCA"}
        
    return {"target_corpora": list(targets)}

async def bm25_search_node(state: AgentState) -> dict:
    print(f"[DEBUG] bm25_search_node: _bm25_index={_bm25_index}, target_corpora={state['target_corpora']}")
    if not _bm25_index or not _corpus_index:
        return {"bm25_hits": []}
    hits = _bm25_index.search(state["query"], _corpus_index, top_k=20, act_filter=state["target_corpora"])
    print(f"[DEBUG] bm25_search_node: Found {len(hits)} hits")
    return {"bm25_hits": hits}

async def navigate_statutes_node(state: AgentState) -> dict:
    if not _tree_navigator:
        return {"tree_hits": []}
        
    hits = []
    targets = state["target_corpora"]
    statutes = [t for t in targets if t in ["BNS", "BNSS", "BSA", "IT", "JJA", "POCSO", "NDPS", "PCA"]]
    
    for stat in statutes:
        stat_hits = await _tree_navigator.navigate(state["query"], stat, top_chapters=2, top_sections=3)
        hits.extend(stat_hits)
        
    return {"tree_hits": hits}

async def retrieve_sop_node(state: AgentState) -> dict:
    if not _sop_retriever:
        return {"tree_hits": []}
    hits = await _sop_retriever.retrieve(state["query"], top_k=3)
    return {"tree_hits": hits}

def enrich_cross_refs_node(state: AgentState) -> dict:
    if not _cross_ref_linker:
        return {"cross_ref_hits": []}
    
    primary = state.get("tree_hits", []) + state.get("bm25_hits", [])
    if not primary:
        return {"cross_ref_hits": []}
        
    enriched = _cross_ref_linker.enrich(primary, max_links_per_node=2)
    return {"cross_ref_hits": enriched}

def assemble_results_node(state: AgentState) -> dict:
    if not _assembler:
        return {"final_results": []}
        
    bm25 = state.get("bm25_hits", [])
    tree = state.get("tree_hits", [])
    cross = state.get("cross_ref_hits", [])
    
    print(f"[DEBUG] BM25 hits: {len(bm25)}, Tree hits: {len(tree)}, CrossRef hits: {len(cross)}")
        
    res = _assembler.assemble(
        bm25,
        tree,
        cross
    )
    
    # We'll return it in a special key "raw_result_dict" which isn't in AgentState strictly,
    # but in Python TypedDicts at runtime allow extra keys in langgraph unless strictly validated.
    # Let's just put all nodes in final_results and rely on the calling code to rebuild it.
    all_res = res["primary"] + res["supporting"]
    return {"final_results": all_res, "metadata": res}

# --- Routing ---

def route_after_intent(state: AgentState) -> List[str]:
    targets = []
    targets.append("bm25_search")
    
    statute_acts = {"BNS", "BNSS", "BSA"}
    if any(a in statute_acts for a in state["target_corpora"]):
        targets.append("navigate_statutes")
        
    if "SOP" in state["target_corpora"]:
        targets.append("retrieve_sop")
        
    return targets

# --- Graph Definition ---

builder = StateGraph(AgentState)

builder.add_node("analyse_intent", analyse_intent_node)
builder.add_node("bm25_search", bm25_search_node)
builder.add_node("navigate_statutes", navigate_statutes_node)
builder.add_node("retrieve_sop", retrieve_sop_node)
builder.add_node("enrich_cross_refs", enrich_cross_refs_node)
builder.add_node("assemble_results", assemble_results_node)

builder.set_entry_point("analyse_intent")

builder.add_conditional_edges(
    "analyse_intent",
    route_after_intent,
    {
        "bm25_search": "bm25_search",
        "navigate_statutes": "navigate_statutes",
        "retrieve_sop": "retrieve_sop"
    }
)

# Fan-in
builder.add_edge("bm25_search", "enrich_cross_refs")
builder.add_edge("navigate_statutes", "enrich_cross_refs")
builder.add_edge("retrieve_sop", "enrich_cross_refs")

builder.add_edge("enrich_cross_refs", "assemble_results")
builder.add_edge("assemble_results", END)

COMPILED_GRAPH = builder.compile()
