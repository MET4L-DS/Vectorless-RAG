# Project Memory & Context

## 🚀 Current Mission / Core Objective

**Vectorless-RAG** is a precision legal assistant for Indian Criminal Law. It indexes statutory legal texts (BNS, BNSS, BSA, SOP) into hierarchical JSON trees (Act → Chapter → Section), then resolves user queries via guided LLM tree traversal, BM25 keyword search, and a ReAct agent loop — entirely without vector embeddings — producing grounded, cited Markdown answers.

**Current expansion goal:** Scale the corpus from 3 acts to 8 acts by ingesting IT Act 2000, JJ Act 2015, POCSO 2012, NDPS Act 1985, and Prevention of Corruption Act 1988 from `./source_documents/`.

---

## 🏗️ System Architecture & Stack

- **Backend:** Python 3.10+ / FastAPI (served via `uvicorn src.api.main:app`)
- **Agent Framework:** LangGraph `create_react_agent` + 3 tools (search_statutes, search_police_sop, enrich_with_cross_references)
- **LLM Platform:**
  - **Summarization (tree build):** Google Gemma API — round-robin `models/gemma-4-26b-a4b-it` + `models/gemma-4-31b-it` (rate-limited to 10 RPM each via async leaky bucket)
  - **Retrieval / Agent:** `models/gemini-3.1-flash-lite` (hardcoded in `src/react_agent/agent.py`)
  - **Deterministic pipeline:** round-robin pool of all 3 models (configured in `src/retriever/client.py`)
- **Indexing:**
  - `tree/*.json` — per-act hierarchical tree files (BNS.json, BNSS.json, BSA.json, SOP.json)
  - `tree/index.json` — corpus registry loaded by `CorpusIndex`
  - `tree/bm25_index/` — pre-tokenized BM25s sparse index
  - `tree/summary_cache.json` — persistent LLM summarization cache (avoids repeat calls)
- **Database:** Supabase PostgreSQL (async via `psycopg_pool.AsyncConnectionPool`)
  - `AsyncPostgresSaver` for LangGraph checkpoint storage
  - `chat_sessions` custom table for per-user session title tracking
- **Auth:** Supabase JWT (RS256/ES256) via JWKS endpoint, cached with 1-hour TTL
- **Frontend:** Next.js (hosted on Vercel: `https://legal-assist-agent.vercel.app/`)
- **Hosting (Backend):** Hugging Face Spaces (`Ayanshu/Legal-Vectorless-RAG-HF`)
- **Deployment Script:** `deploy.py` using `huggingface_hub` SDK (bypasses Windows CLI globbing)

---

## 🛠️ Key Technical Decisions & Quirks

### Architecture Decisions
- **[2026-07] No vector embeddings (intentional):** BM25 + guided tree traversal is more precise for structured statutory text than approximate nearest-neighbor vector search. This is a core design principle, not a limitation.
- **[2026-07] Two parallel retrieval pipelines:** Deterministic State Machine (`src/retriever/graph.py`) and ReAct Agent (`src/react_agent/agent.py`). The ReAct agent is used in production; the deterministic pipeline is retained for benchmarking.
- **[2026-07] `AsyncPostgresSaver` over `AsyncSqliteSaver`:** Chose Supabase Postgres instead of local SQLite for checkpoint persistence so the deployed HF Spaces backend can maintain multi-user session state without local disk dependency.
- **[2026-07] Gemma for summarization, Gemini for inference:** Gemma 26B/31B models are used only during the offline one-time tree build (slow, 18s–55s per call). Gemini Flash-Lite is used for all live query inference (fast, ~1.3s).

### Ingestion Quirks
- **BNSS Chapter V Injection:** The source PDF is missing Chapter V ("ARREST OF PERSONS") in its TOC. The parser injects it synthetically at Section 35 via regex heuristic.
- **BNSS First Schedule:** The borderless multi-page offence classification table is parsed using horizontal coordinate thresholds, not text delimiters. Each row becomes a `schedule_row` leaf node.
- **`SOP` detection in `tree_builder.py`:** The SOP act is auto-detected from Parquet if `"SOP"` appears in `toc_df["act_code"]` — no hardcoded list.

### CLI Execution Quirk
- **`ModuleNotFoundError: No module named 'src'`:** Run ALL CLI scripts with `sys.path` injection. This has already been patched in `src/cli.py`, `src/react_agent/cli_react.py`, and `src/react_agent/benchmark.py`. Do NOT run scripts via `python -m` unless using the `$env:PYTHONPATH="."` prefix.
- Correct command pattern: `python ./src/react_agent/cli_react.py` (the path injection handles it)

### API Quirks
- **Thread ID scoping:** All threads are namespaced as `f"{user_sub}:{thread_id}"` in `routes.py`. This prevents cross-user history leakage.
- **Chat title is set from `GeneratedAnswer.chat_title`:** Only updated on the first turn when the DB shows title is still `"New Legal Chat"`.
- **CORS:** Origin whitelist is loaded from `ALLOWED_ORIGINS` env var (comma-separated). Falls back to `"*"` if not set.

### Deployment
- **Do NOT use `git push hf main`** — HF rejects because binary files (`.parquet`, `.npy`, `.db`) appear in git history. Always use `python deploy.py` instead.
- **`.huggingfaceignore` excludes:** `.venv/`, `.git/`, `.env`, `output/`, `local_agent_memory.db`, `__pycache__/`

---

## 🏁 Progress Checklist

### ✅ Completed Phases
- [x] **Phase 1 — Ingestion & Parsing:** `parser.py` parses BNS (358s), BNSS (531s), BSA (170s). `sop_parser.py` parses Police SOP. All validated with zero orphans.
- [x] **Phase 2 — Tree Construction:** Bottom-up Gemma summarization of 1,582 nodes. Trees stored in `tree/*.json`. Summary cache prevents repeat LLM calls. 191,252 token navigation scaffold.
- [x] **Phase 3 — LangGraph Retrieval Subsystem:** `TreeNavigator`, `BM25Index`, `SOPRetriever`, `CrossRefLinker`, LangGraph State Machine orchestrator.
- [x] **Phase 4 — Generator & Groundedness:** Deterministic pipeline with `ContextRouter`, `GeneratorAgent`, `VerifierAgent`. Structured `GeneratedAnswer` Pydantic output.
- [x] **Phase 4.5 — LangChain Structured Outputs Migration:** All LLM calls use `.with_structured_output()` with Pydantic schemas. Zero fragile JSON parsing.
- [x] **Phase 4.6 — CLI Aesthetics Upgrade:** Rich-powered terminal UIs for both CLIs.
- [x] **Phase 5 — ReAct Agent:** `create_react_agent` with 3 tools, streamed Thought→Action→Observation, benchmarked vs. deterministic pipeline.
- [x] **Phase 6 — FastAPI Production Backend:** SSE streaming, Supabase Postgres checkpointer, JWT auth, session metadata.
- [x] **Phase 7 — Frontend:** Next.js client with reasoning accordion, citation panels, suggested questions, action items.
- [x] **Phase 8 — Deployment:** HF Spaces deployment via `deploy.py`. Frontend on Vercel.

### 🔄 In Progress
- [/] **Phase 9 — Corpus Expansion (5 new acts):** Adding IT Act, JJ Act, POCSO, NDPS, PoC Act.
  - Bucket 1: Metadata enrichment of existing statute nodes
  - Bucket 2: Generic parser for new act PDFs
  - Bucket 3: Tree integration + BM25 re-indexing
  - Bucket 4: `search_statutes` tool expansion + `find_case_law_for_section` scaffold
  - Bucket 5: Validation + benchmark across all 8 corpora

### 📋 Upcoming
- [ ] **Phase 10 — Case Law Nodes:** `JudgementParser` + `INTERPRETS/CITES` relationship edges
- [ ] **Phase 11 — Transitional Law Reasoning:** IPC/CrPC corpus + `AMENDS/REPEALS` edges
- [ ] **Phase 12 — Knowledge Graph Upgrade (optional at scale):** Neo4j migration if node count exceeds practical in-memory limits

---

## 📁 Key File Map

| File | Role |
|---|---|
| `src/parser.py` | BNS/BNSS/BSA PDF → Parquet dataframes |
| `src/sop_parser.py` | SOP PDF → Parquet dataframes |
| `src/tree_builder.py` | Parquet → unsummarized JSON tree |
| `src/summarizer.py` | Async Gemma summarization + cache |
| `src/build_tree.py` | Orchestrates build + validation pipeline |
| `src/validation.py` | Structural correctness checks |
| `src/retriever/corpus_index.py` | In-memory node map loaded from `tree/*.json` |
| `src/retriever/tree_navigator.py` | Guided 2-level chapter → section traversal |
| `src/retriever/bm25_index.py` | BM25s sparse keyword search |
| `src/retriever/cross_ref_linker.py` | Programmatic citation graph resolver |
| `src/retriever/client.py` | Rate-limited round-robin Gemini/Gemma pool |
| `src/retriever/graph.py` | Deterministic LangGraph state machine |
| `src/react_agent/agent.py` | ReAct agent (Gemini Flash-Lite) |
| `src/react_agent/tools.py` | 3 LangChain tools for the ReAct agent |
| `src/api/main.py` | FastAPI lifespan + Postgres pool + CORS |
| `src/api/routes.py` | SSE streaming, history, session, chat management |
| `src/api/auth.py` | Supabase JWKS JWT verification |
| `deploy.py` | HF Spaces upload via `huggingface_hub` SDK |
| `tree/index.json` | Corpus registry (which acts are indexed) |
| `tree/summary_cache.json` | Gemma summarization cache |
