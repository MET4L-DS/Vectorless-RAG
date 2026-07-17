# Project Memory & Context

## 🚀 Current Mission / Core Objective

**Vectorless-RAG** is a precision legal assistant for Indian Criminal Law. It indexes statutory legal texts (BNS, BNSS, BSA, SOP, and 5 auxiliary acts: IT, JJA, POCSO, NDPS, PCA) into hierarchical JSON trees (Act → Chapter → Section), then resolves user queries via guided LLM tree traversal, BM25 keyword search, and a ReAct agent loop — entirely without vector embeddings — producing grounded, cited Markdown answers.

**Current expansion goal:** Extend database entity relationships by implementing Case Law nodes (Phase 11) and Transitional Law mapping (Phase 12) between the new statutes and older equivalents (IPC/CrPC).

---

## 🏗️ System Architecture & Stack

- **Backend:** Python 3.10+ / FastAPI (served via `uvicorn src.api.main:app`)
- **Agent Framework:** LangGraph `create_react_agent` + 4 tools (search_statutes, search_police_sop, enrich_with_cross_references, find_case_law_for_section)
- **LLM Platform:**
  - **Summarization (tree build):** Google Gemma API — round-robin `models/gemma-4-26b-a4b-it` + `models/gemma-4-31b-it` (rate-limited to 10 RPM each via async leaky bucket)
  - **Retrieval / Agent:** `models/gemini-3.1-flash-lite` (hardcoded in `src/react_agent/agent.py`)
  - **Deterministic pipeline:** round-robin pool of all 3 models (configured in `src/retriever/client.py`)
- **Indexing:**
  - `tree/*.json` — per-act hierarchical tree files (BNS, BNSS, BSA, SOP + 5 new: IT, JJA, POCSO, NDPS, PCA)
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

### Database & PgBouncer Compatibility
- **[2026-07] Switch to Transaction Pooling (Port 6543):** Changed connection string port from `5432` (Session mode) to `6543` (Transaction mode). Session pooling has a strict limit of 15 concurrent clients on Supabase which led to connection exhaustion hangs (`EMAXCONNSESSION`) under parallel request and process-reloading conditions.
- **[2026-07] Disabling Prepared Statements:** Configured `"prepare_threshold": None` in psycopg3 connection pool `kwargs` to prevent prepared statement and pipeline mode conflicts, which are not supported by PgBouncer in transaction mode.
- **[2026-07] TCP Keepalives & Lifetime Configuration:** Added TCP keepalive parameters (`keepalives=1`, `keepalives_idle=30`) and `max_lifetime=300` to the pool configuration to prevent PgBouncer/Supabase from silently severing idle sockets and producing stale socket reads (`unexpected eof while reading`).
- **[2026-07] Database Connection Pool Validation on Checkout:** Added a `check_db_connection` function executing a simple `SELECT 1` ping query and passed it to `check=check_db_connection` in `AsyncConnectionPool`. This ensures stale database connection pool sockets after periods of container sleep/hibernation are verified and discarded automatically, preventing 500 database errors on wakeup.

### Security & Authentication
- **[2026-07] Locked JWKS Fetching with httpx:** Added an `asyncio.Lock` inside [auth.py](file:///c:/Met4l.DSCode/Projects/Vectorless-RAG/src/api/auth.py) to prevent concurrent guest/user requests from triggering parallel network fetches for Supabase public keys. Refactored the fetcher to use `httpx` instead of `urllib.request` to support async natively, prevent thread pool bottlenecks, and improve network timeout logging.

### Ingestion Quirks
- **BNSS Chapter V Injection:** The source PDF is missing Chapter V ("ARREST OF PERSONS") in its TOC. The parser injects it synthetically at Section 35 via regex heuristic.
- **BNSS First Schedule:** The borderless multi-page offence classification table is parsed using horizontal coordinate thresholds, not text delimiters. Each row becomes a `schedule_row` leaf node.
- **`SOP` detection in `tree_builder.py`:** The SOP act is auto-detected from Parquet if `"SOP"` appears in `toc_df["act_code"]` — no hardcoded list.

### CLI & API Execution
- **`ModuleNotFoundError: No module named 'src'`:** Run ALL CLI scripts with `sys.path` injection. This has already been patched in `src/cli.py`, `src/react_agent/cli_react.py`, and `src/react_agent/benchmark.py`. Do NOT run scripts via `python -m` unless using the `$env:PYTHONPATH="."` prefix.
- **Thread ID scoping:** All threads are namespaced as `f"{user_sub}:{thread_id}"` in `routes.py`. This prevents cross-user history leakage.
- **Chat title is set from `GeneratedAnswer.chat_title`:** Only updated on the first turn when the DB shows title is still `"New Legal Chat"`.
- **CORS:** Origin whitelist is loaded from `ALLOWED_ORIGINS` env var (comma-separated). Falls back to `"*"` if not set.

### Deployment
- **Do NOT use `git push hf main`** — HF rejects because binary files (`.parquet`, `.npy`, `.db`) appear in git history. Always use `python deploy.py` instead.
- **`.huggingfaceignore` excludes:** `.venv/`, `.git/`, `.env`, `output/`, `local_agent_memory.db`, `__pycache__/`

---

## 🏁 Progress Checklist

### ✅ Completed Phases
- [x] **Phase 1 — Ingestion & Parsing:** BNS, BNSS, BSA, and Police SOP parsed with zero orphans.
- [x] **Phase 2 — Tree Construction:** Bottom-up Gemma summarization of 1,582 nodes. Trees stored in `tree/*.json`.
- [x] **Phase 3 — LangGraph Retrieval Subsystem:** `TreeNavigator`, `BM25Index`, `SOPRetriever`, `CrossRefLinker`.
- [x] **Phase 4 — Generator & Groundedness:** Deterministic pipeline with `ContextRouter`, `GeneratorAgent`, `VerifierAgent`.
- [x] **Phase 4.5 — LangChain Structured Outputs Migration:** All LLM calls use `.with_structured_output()` with Pydantic schemas.
- [x] **Phase 4.6 — CLI Aesthetics Upgrade:** Rich-powered terminal UIs.
- [x] **Phase 5 — ReAct Agent:** `create_react_agent` with 3 tools.
- [x] **Phase 6 — FastAPI Production Backend:** SSE streaming, Supabase Postgres checkpointer, JWT auth.
- [x] **Phase 7 — Frontend:** Next.js client with reasoning accordion, citation panels.
- [x] **Phase 8 — Deployment:** HF Spaces deployment via `deploy.py`. Frontend on Vercel.
- [x] **Phase 9 — Accuracy Benchmark & Optimization:** Created 15-case golden dataset. Optimized agent system prompt with multi-act exhaustiveness. Citation Recall at 86.7%, Substantive Completeness at 53.3%.
- [x] **Phase 10 — UI Polish, Streaming & Connection Resilience (July 2026):** 
  - Refactored routes to support granular streaming updates.
  - Implemented smooth, lock-to-bottom scroll viewports using `MutationObserver` on both the main chat window and internal accordion reasoning logs.
  - [x] Refactored routes to support granular streaming updates.
  - [x] Implemented smooth, lock-to-bottom scroll viewports using `MutationObserver` on both the main chat window and internal accordion reasoning logs.
  - [x] Delayed rendering of supplementary cards (provisions, action items) until the answer typing reveal animation completes.
  - [x] Enforced 1st-person query gating for Action Items in the Pydantic schema.
  - [x] Decoupled citation processing on the frontend to render distinct clickable chips for comma-separated outputs.
  - [x] Added API call count, total run-time, latency, and tok/sec metrics to CLI debuggers.
  - [x] Resolved `EMAXCONNSESSION` database deadlock and SSL EOF issues by configuring the pooler for PgBouncer transaction mode (port 6543), setting `prepare_threshold=None`, and setting up TCP keepalives.
  - [x] Resolved Hugging Face Space cold-start / sleep failures by implementing backend database connection pool validation (`check=check_db_connection`) on connection checkout, and client-side HTTP request retry loops with exponential backoff on the Next.js frontend (for sessions fetching and history loading) to gracefully await backend container wakeup.
  - [x] Migrated Server-Sent Events (SSE) streaming endpoint from raw `StreamingResponse` to `sse-starlette`'s `EventSourceResponse` to add standardized headers (`Cache-Control: no-cache`, `X-Accel-Buffering: no`) and automatic 20s keep-alive heartbeats to protect against proxy drops on Hugging Face Spaces.
  - [x] Refactored frontend SSE consumer transport from Axios `fetch` adapter to native browser `fetch` and `ReadableStream` reader to improve bundle footprint and prevent multibyte chunk-splitting errors.
  - [x] Cleaned up Python global `ContextVar` (`retrieved_nodes_var`) side-channels in the LangGraph agent by establishing a state-based `retrieved_nodes` channel in `AgentState` and using LangGraph's native `Command` object to return tool output results and graph state updates simultaneously.
  - [x] Resolved backend concurrency and event loop bottlenecks by refactoring rate-limiting locks to be initialized lazily on-demand inside the active event loop, and wrapping synchronous CPU-bound `bm25s` search queries in `asyncio.to_thread` workers.
  - [x] Fixed multi-tenant security vulnerability by enforcing JWT authentication in the token verification layer, removing the unsafe shared static `"guest"` namespace fallback for unauthenticated requests.
  - [x] Optimized server container boot performance by moving blocking in-memory index/tree loader out of the router module import path into FastAPI's native lifespan startup handler.
  - [x] Cleaned up deprecated `@app.on_event("startup")` hooks in legacy startup scripts in favor of standardized `lifespan` context managers.
  - [x] Refactored statutory summarizer data pipeline to initialize rate-limiting locks lazily, use Google GenAI's first-class async clients (`client.aio`), and offload disk cache writes (`save_cache()`) to threadpools to prevent blocking event loop execution.

### 🔄 In Progress
*None*

### 📋 Upcoming
- [ ] **Phase 11 — Case Law Nodes:** `JudgementParser` + `INTERPRETS/CITES` relationship edges
- [ ] **Phase 12 — Transitional Law Reasoning:** IPC/CrPC corpus + `AMENDS/REPEALS` edges
- [ ] **Phase 13 — Knowledge Graph Upgrade (optional at scale):** Neo4j migration if node count exceeds practical in-memory limits

---

## 📁 Key File Map

| File | Role |
|---|---|
| `src/parser.py` | BNS/BNSS/BSA PDF → Parquet dataframes |
| `src/sop_parser.py` | SOP PDF → Parquet dataframes |
| `src/generic_parser.py` | Configurable parser for new acts; driven by ActAdapter |
| `src/act_adapters/__init__.py` | ActAdapter configs for IT, JJA, POCSO, NDPS, PCA |
| `src/tree_builder.py` | Parquet → unsummarized JSON tree (has `_STATUTE_METADATA` registry) |
| `src/summarizer.py` | Async Gemma summarization + cache |
| `src/build_tree.py` | Orchestrates build + validation pipeline |
| `src/validation.py` | Structural correctness checks (dynamic, works for any N acts) |
| `src/retriever/corpus_index.py` | In-memory node map loaded from `tree/*.json` |
| `src/retriever/tree_navigator.py` | Guided 2-level chapter → section traversal |
| `src/retriever/bm25_index.py` | BM25s sparse keyword search |
| `src/retriever/cross_ref_linker.py` | Programmatic citation graph resolver |
| `src/retriever/client.py` | Rate-limited round-robin Gemini/Gemma pool + latency logging |
| `src/retriever/graph.py` | Deterministic LangGraph state machine |
| `src/react_agent/agent.py` | ReAct agent (Gemini Flash-Lite), 4 tools, 8-act system prompt |
| `src/react_agent/tools.py` | 4 LangChain tools: search_statutes, search_police_sop, enrich_with_cross_references, find_case_law_for_section |
| `src/api/main.py` | FastAPI lifespan + PgBouncer-compliant Postgres pool + CORS |
| `src/api/routes.py` | SSE streaming, history, session, chat management |
| `src/api/auth.py` | Supabase JWKS JWT verification (safe httpx + lock) |
| `deploy.py` | HF Spaces upload via `huggingface_hub` SDK |
| `tree/index.json` | Corpus registry (which acts are indexed) |
| `tree/summary_cache.json` | Gemma summarization cache |
