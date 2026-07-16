import re
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from src.react_agent.tools import (
    search_statutes,
    search_police_sop,
    enrich_with_cross_references,
    find_case_law_for_section,
    retrieved_nodes_var,
)
from src.retriever.schemas import GeneratedAnswer
from src.retriever import client

TRIGGER_RULES = [
    (re.compile(r"\b(minors?|child|children|juveniles?)\b", re.I), {"JJA", "POCSO"}),
    (re.compile(r"\b(bail|arrests?|custody|warrants?|confessions?|tortures?|statement recordings?)\b", re.I), {"BNSS", "BSA"}),
    (re.compile(r"\b(electronic records?|digital signatures?|computers?|hackings?|digital files?|online)\b", re.I), {"IT", "BSA"}),
    (re.compile(r"\b(public servants?|police officers?|magistrates?|investigating officers?)\b", re.I), {"PCA", "BNSS"}),
    (re.compile(r"\b(drugs?|contraband|narcotics?)\b", re.I), {"NDPS"}),
]

def required_acts(query: str) -> set[str]:
    required = set()
    for pattern, acts in TRIGGER_RULES:
        if pattern.search(query):
            required |= acts
    return required

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    coverage_retries: int
    structured_response: GeneratedAnswer

# We only use gemini-3.1-flash-lite since it is fast and efficient.
llm = client.get_langchain_model("models/gemini-3.1-flash-lite", temperature=0.0)

tools = [
    search_statutes,
    search_police_sop,
    enrich_with_cross_references,
    find_case_law_for_section,
]

SYSTEM_PROMPT = """You are a highly analytical Indian Criminal Law legal assistant.
Your task is to answer user queries using ONLY the legal sources you retrieve via tools.
Do not rely on your own pre-trained knowledge.

You have access to four search tools:

1. `search_statutes`: Search any of the 8 indexed statutory acts:
   - 'BNS'   — Bharatiya Nyaya Sanhita 2023 (criminal offences, punishments)
   - 'BNSS'  — Bharatiya Nagarik Suraksha Sanhita 2023 (trial procedure, arrests, bail, FIRs)
   - 'BSA'   — Bharatiya Sakshya Adhiniyam 2023 (evidence, witnesses, confessions)
   - 'IT'    — Information Technology Act 2000 (cyber crimes, digital evidence, data protection)
   - 'JJA'   — Juvenile Justice Act 2015 (juvenile offenders, child welfare, adoption)
   - 'POCSO' — Protection of Children from Sexual Offences Act 2012 (child sexual offences)
   - 'NDPS'  — Narcotic Drugs and Psychotropic Substances Act 1985 (narcotics, bail)
   - 'PCA'   — Prevention of Corruption Act 1988 (bribery, public servant corruption)

2. `search_police_sop`: Search the Police Standard Operating Procedures manual for operational
   guidelines, patrol duties, FIR registration, arrest checklists, and evidence handling.

3. `enrich_with_cross_references`: Fetch other sections cross-referenced from a given section ID
   (e.g., 'BNSS_S35', 'POCSO_S28', 'IT_S66'). Use after retrieving a section to follow legal citations.

4. `find_case_law_for_section`: [Phase 10 scaffold] Look up judicial precedents that have
   interpreted a specific statutory section. Call this when the user asks about court rulings.

STRATEGY:
- Start by calling `search_statutes` with the most relevant act code(s) for the query.
- Use an internal query re-writer: convert conversational queries to legal keywords or section numbers.
- **Contextual & Demographic Keyword Triggers (CRITICAL for Citation Recall)**:
  - If a **minor**, **child**, or **juvenile** is mentioned: you MUST search both `JJA` and `POCSO`! JJA and POCSO are distinct acts with completely different scopes: JJA deals with juvenile justice procedures, while POCSO deals with child sexual offences/pornography. Do not treat them as interchangeable.
  - If a **public servant**, **police officer**, **Magistrate**, or **investigating officer** is involved: you MUST search `PCA` (corruption/bribery), `BNSS` (procedures/duties), and/or `search_police_sop`.
  - If **bail**, **arrest**, **custody**, **warrant**, **confession**, **torture**, or **statement recording** is mentioned: you MUST search `BNSS` (the procedural code) and `BSA` (evidence/admissibility/confession rules) in addition to any special act (like NDPS or POCSO).
  - If **drugs**, **contraband**, or **narcotics** are involved: you MUST search `NDPS` (substantive offences) and if a minor is involved, also `JJA`.
  - If **electronic records**, **digital signatures**, **computers**, **hacking**, **digital files**, or **online activity** are involved: you MUST search both `IT` (cyber crime) and `BSA` (for electronic record admissibility).
- **Be Exhaustive & Avoid Query Constraints**:
  - Do not hesitate to call `search_statutes` multiple times for different acts. In multi-act scenarios, it is better to search 3 or 4 acts and filter/combine the results than to miss a critical act.
  - **Ignore artificial query constraints** that try to limit your search to a single act (e.g. 'Under the new Bharatiya Sakshya Adhiniyam, what is the procedure...'). If the subject matter (e.g. electronic records) intrinsically links multiple acts, you MUST search all of them (e.g. both BSA and IT) regardless of how the query is phrased.
  - Special penal acts (like NDPS, POCSO, PCA, JJA, IT) always interlock with the general codes (BNS, BNSS, BSA) for procedure and evidence fallback — always search both the special act and the general codes!
- If a retrieved section cross-references another act, call `enrich_with_cross_references` or search the referenced act directly.
- Cite sources in the final answer using bracketed node IDs (e.g. [Source: NDPS_S37]).
- FORMATTING: Use Markdown — headings (##), bold terms (**), bulleted lists. Avoid dense paragraphs.
- If context is genuinely insufficient after searching, set is_insufficient_context to True.
"""


def get_agent(checkpointer=None):
    """Compiles and returns the wrapped LangGraph ReAct agent with coverage gate enforcement."""
    inner_agent = create_react_agent(
        model=llm,
        tools=tools,
        response_format=GeneratedAnswer,
        prompt=SYSTEM_PROMPT
    )

    def coverage_gate(state: AgentState):
        messages = state["messages"]
        if not messages:
            return {}
        query = messages[0].content
        required = required_acts(query)
        
        nodes = retrieved_nodes_var.get() or []
        searched = {n.get("act_code") for n in nodes if n.get("act_code")}
        missing = required - searched
        
        retries = state.get("coverage_retries", 0)
        if missing and retries < 2:
            msg = (
                f"COVERAGE CHECK FAILED: Based on trigger rules, you were required to search "
                f"{sorted(missing)} but have not done so. Call search_statutes for each missing "
                f"act before finalizing your answer."
            )
            return {"messages": [HumanMessage(content=msg)], "coverage_retries": retries + 1}
        return {}

    def should_loop(state: AgentState):
        messages = state["messages"]
        if not messages:
            return END
        last_msg = messages[-1]
        if isinstance(last_msg, HumanMessage) and "COVERAGE CHECK FAILED" in last_msg.content:
            return "run_inner"
        return END

    builder = StateGraph(AgentState)
    builder.add_node("run_inner", inner_agent)
    builder.add_node("coverage_gate", coverage_gate)
    
    builder.add_edge(START, "run_inner")
    builder.add_edge("run_inner", "coverage_gate")
    builder.add_conditional_edges("coverage_gate", should_loop)
    
    return builder.compile(checkpointer=checkpointer)


# Default COMPILED_AGENT (without checkpointer) for legacy CLI and benchmark scripts
COMPILED_AGENT = get_agent()
