# Component Implementation: Autonomous ReAct Agent Loop

The ReAct (Reasoning and Acting) Agent gives the LLM complete autonomy to decide what to search, in which order, and when to synthesize the final answer. It is implemented in the `src/react_agent/` package.

---

## 1. Orchestration Engine (`src/react_agent/agent.py`)

The orchestrator utilizes LangGraph's prebuilt `create_react_agent` class:
- **System Prompt**: Directs the agent to act as a legal assistant, search thoroughly, follow cross-references, cite exact section codes (e.g. `[Source: BNS_S303]`), and declare when context is insufficient.
- **Structured Final Output**: Specifying the `response_format=GeneratedAnswer` schema forces the agent to stop tool-calling and format its final output according to the requested Pydantic schema:
  ```python
  class GeneratedAnswer(BaseModel):
      answer_text: str = Field(description="The comprehensive cited legal answer...")
      key_provisions: list[str] = Field(description="List of key statutory clauses...")
      citations: list[str] = Field(description="Exact section IDs referenced...")
      is_insufficient_context: bool = Field(description="True if context is missing...")
  ```

---

## 2. Search Tools (`src/react_agent/tools.py`)

Three functions are decorated with `@tool` and exposed to the agent:

1. **`search_statutes`**:
   - Queries a specific act (`BNS`, `BNSS`, `BSA`).
   - Executes both `TreeNavigator` search and `BM25Index` keyword search, merging and deduplicating results.
2. **`search_police_sop`**:
   - Executes `SOPRetriever` to extract checklist items.
3. **`enrich_with_cross_references`**:
   - Hydrates a single node ID, calls `CrossRefLinker.enrich`, and returns cross-referenced statutes.

### Thread-Safe Context Tracking
To display retrieved nodes in the UI, the tools intercept search results using Python's `contextvars` library:
```python
# Thread-safe ContextVar
retrieved_nodes_var = contextvars.ContextVar("retrieved_nodes", default=None)

# Inside _format_nodes helper:
collected = retrieved_nodes_var.get()
if collected is not None:
    for node in nodes:
        if not any(x["node_id"] == node["node_id"] for x in collected):
            collected.append(node)
```

---

## 3. Streaming CLI (`src/react_agent/cli_react.py`)

Exposes a rich, trace-enabled CLI:
- **Reasoning Stream**: Uses `COMPILED_AGENT.astream(..., stream_mode="updates")` to display the agent's thought process step-by-step:
  - When `node == "agent"`: Extracts and prints thoughts and the tools selected.
  - When `node == "tools"`: Previews the formatted outputs returned by search tools.
- **Robust Parsing**:
  - Flattens message contents if they are returned as a list of dicts (common in modern Gemini outputs), preventing `.strip()` crashes.
  - Encodes metadata using safe ASCII strings (`[OK]`, `[FAIL]`) to avoid `UnicodeEncodeError` in Windows terminals.

---

## 4. Operational Safeguards

1. **Recursion Cap**: Executes with `config={"recursion_limit": 10}` to terminate runaway loops and protect Gemini API quotas.
2. **Deterministic Fallback**: In the event of a reasoning exception or tool failure, the agent returns a structured `GeneratedAnswer` declaring the error.
