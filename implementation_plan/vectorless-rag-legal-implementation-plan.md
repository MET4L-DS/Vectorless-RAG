# Vectorless RAG for Legal Document Analysis — Implementation Plan

*Validated against the current (mid-2026) state of the vectorless-RAG ecosystem*

## 0. How this plan relates to the source design doc

Before laying out a build plan, it's worth separating what's industry-standard today from what's proprietary framing in the original design doc, so the team doesn't waste time trying to source components that don't exist as named products.

| Concept in the design doc | Status as of July 2026 |
|---|---|
| Vectorless, tree-based, reasoning-driven retrieval | **Real and mainstream.** This is exactly the architecture behind **PageIndex** (VectifyAI), an MIT-licensed, open-source framework with ~30k+ GitHub stars, a Python + TypeScript SDK, a cloud API, MCP support, and an OCR-free vision pipeline. The "two-call retrieval, tree index, no vector DB" workflow described in the doc is a description of PageIndex's actual architecture, not a hypothetical. |
| 98.7% on FinanceBench | **Real, vendor-reported number**, achieved by VectifyAI's "Mafin 2.5" system built on PageIndex. Treat it the way you'd treat any vendor benchmark — real, but optimized for a benchmark the vendor also popularized. Independent write-ups note the number holds up for structured, long single documents and degrades for broad multi-document corpora, where vector search's speed/scale advantage still matters. |
| M3DocDep, SoftROI, biaffine dependency scoring, MST decoding | **Real 2026 paper** (arXiv, CVPR 2026) — this is legitimate recent research, not a fabricated citation. It's early-stage academic work, not a maintained library, so plan to reimplement the pipeline yourself rather than `pip install` it. |
| HiPS ("Hierarchical PDF Segmentation") as a named framework | Not a standard, citable industry term as far as current sources show. Treat the three subtasks described (title detection, level allocation, boundary assignment) as a sound **design pattern** to implement, not a library to import. |
| Arbiter Pattern, IRAC-as-knowledge-graph, Graph-Constrained Generation/Verifier Agent | Sound architectural ideas consistent with how production legal-AI and GraphRAG systems are built in 2026, but they are **this document's own synthesis**, not an off-the-shelf pattern with a name recognized elsewhere. Build them as custom components.
| FalkorDB / Neo4j for the graph layer | Both real, both viable, and this is a genuine current trade-off (see §4 below) — not outdated advice. |
| "Legal RAG Bench" | Could not confirm this as an established public benchmark. Don't budget evaluation time assuming it exists; plan to build a proprietary eval set instead (see §7). |

**Bottom line:** the architecture is sound and matches where the industry has actually moved by mid-2026. The main implementation decision is **build vs. adopt**: PageIndex already solves tree construction and tree-search retrieval. The genuinely novel, legal-specific work is the IRAC knowledge graph, the Arbiter consolidation layer, and the Verifier Agent — that's where your engineering budget should concentrate.

---

## 1. Recommended build-vs-buy stance

Don't reimplement the tree-index engine from scratch. Adopt it, then build the legal reasoning layer on top:

- **Adopt:** PageIndex (self-hosted OSS for the tree construction + tree-search retrieval core, or the cloud API/enterprise VPC tier if you need managed OCR quality on scanned filings).
- **Build in-house:** the HiPS-style structural parser (only needed as a fallback when PDFs lack clean native outlines), the IRAC knowledge graph and its population pipeline, the Arbiter consolidation layer, and the Verifier Agent.
- **Evaluate, don't assume:** whether you need the M3DocDep-style vision pipeline at all. It's justified only for heavily scanned, non-native-PDF corpora (old case law scans, faxed filings). For born-digital contracts and filings, PageIndex's standard text-based tree construction is cheaper and sufficient.

This reframes the project from "build a vectorless RAG engine" (large, risky, redundant with existing OSS) to "build a legal-domain reasoning and verification layer on top of a proven vectorless retrieval core" (smaller, higher-value, differentiated).

---

## 2. Phase 1 — Ingestion & Parsing Pipeline

**Goal:** produce the four DataFrames (`line_df`, `toc_df`, `page_df`, `image_df`) plus a decision on whether a document needs the vision fallback.

1. **Native-outline extraction first (cheapest path).** Attempt to pull TOC/bookmarks directly from PDF metadata (PyMuPDF/`pikepdf`). Most native-digital contracts and statutes have partial outlines — use them as seed hypotheses, not ground truth.
2. **HiPS-style structural detection as the default fallback.**
   - Section Title Detection: font size, bold spans, and bounding boxes from a layout parser (PyMuPDF `get_text("dict")`, or a document-layout model) plus dot-leader heuristics for TOC pages.
   - Hierarchy Level Allocation: numbering-pattern classifiers (regex + small classifier for "Article I" vs "Section 1.01" vs "(a)(i)" nesting typical of contracts).
   - Section Boundary Assignment: align detected headings back to the line stream to close out `toc_df` start/end page ranges.
   - This is realistically a 3–5 week build for a small team using existing layout-detection models (e.g., a fine-tuned layout model or an LLM-assisted heading classifier) rather than a from-scratch CV system.
3. **Vision fallback (M3DocDep-style) only for scanned/irregular documents.** Budget this as a separate, optional track: SharedDet-style page canvas → LVLM block embeddings (Qwen2.5-VL or similar) → biaffine parent-child scoring → MST decode. This is genuinely research-grade engineering; scope it after the text-based path is in production, not before.
4. **Output contract:** every row in every DataFrame must carry a stable `section_id`/`node_id` that survives re-ingestion (hash of title + page range + document version), since the tree schema and the knowledge graph both depend on ID stability.

**Team:** 1–2 backend/ML engineers, 4–6 weeks for the text-based path; +4–6 weeks if the vision fallback is in scope.

---

## 3. Phase 2 — Tree Construction (adopt PageIndex)

1. Stand up PageIndex self-hosted (Python) for the initial pilot corpus; move to the cloud/enterprise tier if OCR quality on scanned filings becomes the bottleneck, or if you need VPC/on-prem for client confidentiality (common requirement in legal).
2. Wire your `toc_df`/`line_df` output as the input to leaf-node summarization, or use PageIndex's own PDF parsing if your HiPS layer isn't ready yet — don't block the pilot on the custom parser.
3. Enforce the JSON schema exactly as specified in the design doc (`node_id`, `level`, `title`, `summary`, `content`, `children`, `metadata`), and strip `content` at query time so only the ~3–4k-token scaffold goes into the navigation call. This matches PageIndex's actual design and is the main reason it stays cheap at query time.
4. For enterprise scale (many thousands of documents), add a file-level index on top of the per-document trees — a lightweight registry mapping document → root node → matter/client metadata is sufficient; don't over-invest in a bespoke "wiki" layer for the pilot.

**Team:** 1 engineer integrating PageIndex, 2–3 weeks for pilot corpus.

---

## 4. Phase 3 — IRAC Knowledge Graph

This is the most legally-differentiated, and most expensive, part of the system.

**Database choice — real trade-off, decide deliberately:**

| | Neo4j | FalkorDB |
|---|---|---|
| Query language | Cypher (mature ecosystem, APOC procedures, most legal-tech GraphRAG tooling assumes it) | Cypher-compatible (openCypher), lighter feature set |
| Latency | Solid for moderate graphs; can become a bottleneck on deep multi-hop traversal at scale | Consistently benchmarked faster on multi-hop/traversal-heavy workloads (sub-140ms p99 vendor figures; independent third-party benchmarks also show FalkorDB ahead on most traversal query types) |
| Licensing | GPL/commercial (AuraDB managed tier is well-established) | Source-available (SSPL); confirm this is acceptable for your deployment model before committing |
| Native vector index | Via plugin | Built-in HNSW — convenient if you keep a *small* embedding-based fallback detector (see §5) in the same store |
| Best fit here | If you want the most mature tooling and don't need extreme multi-hop latency | If traversal latency (overruling checks, conflict detection across long citation chains) is the binding constraint, which it plausibly is for the Verifier Agent's real-time checks |

Recommendation: **prototype on Neo4j** (ecosystem maturity, easier hiring, more legal-tech precedent) and **load-test FalkorDB** once the Verifier Agent's traversal patterns are known, since its multi-hop conflict/overruling checks are exactly the workload FalkorDB is positioned for. Don't commit irreversibly at the pilot stage.

**Population pipeline:**
1. Extract `Case`, `LegalIssue`, `Rule`, `Argument`, `Outcome` nodes per judgment using an LLM extraction pass over each leaf node's raw text (not the tree summaries — you need full fidelity for graph population). This is a structured-extraction task: prompt for a fixed JSON schema, validate against it, reject and retry on schema violations.
2. Populate the Procedural layer (`ProceduralEvent` chains) from procedural-history sections specifically — these are usually clearly delimited in judgments and filings, making them a good target for a narrower, higher-precision extractor than the general IRAC pass.
3. Populate the Precedent/Statutory layer (`CITES`, `DISTINGUISHES`, `OVERRULES`, `GOVERNED_BY`) — citation extraction is a well-studied NLP task; use a citation-parsing library (e.g., a legal citation parser suited to your jurisdiction) as a first pass, then LLM-verify the *semantic* relationship (cites approvingly vs. distinguishes vs. overrules), since citation form alone doesn't tell you the relationship type.
4. **Human-in-the-loop QA is not optional here.** Automatically extracted `OVERRULES` edges are exactly the kind of claim that, if wrong, causes the liability scenario the design doc is trying to prevent. Budget for a legal-reviewer QA pass on a sample of extracted edges before trusting the graph for the Verifier Agent's hard vetoes.

**Team:** 1 ML engineer + 1 domain-knowledgeable reviewer (ideally someone with legal training), 6–10 weeks for a first working ontology on a pilot jurisdiction/practice area — this should not be attempted across all practice areas at once.

---

## 5. Phase 4 — Retrieval Subsystem: Detectors + Arbiter

1. **TOC/title match detector:** trivial — string/keyword match against `toc_df.title`. Zero-cost, always on.
2. **Co-occurrence / full-text detector:** stand up Elasticsearch or OpenSearch over `line_df`; use `function_score` with `boost_mode: multiply` as specified, not additive `should` clauses — this is correct current practice for combining lexical signals without scale instability.
3. **Optional embedding fallback:** keep this genuinely optional and small in scope — a single embedding index (even reusing FalkorDB's built-in HNSW if you chose FalkorDB, to avoid running two separate stores) for fuzzy conceptual queries only. Don't let this quietly turn into a second full RAG pipeline; its job is narrow-recall, not primary retrieval.
4. **Arbiter (your own component, not an off-the-shelf pattern):** implement as a single structured-output LLM call per query that takes the `CandidateBrief` JSON and returns role assignments (`Primary`/`Supporting`/`Tangential`/`Discarded`) with justification strings. Use tool-use/structured-output mode (JSON schema-constrained generation) rather than free-text parsing, to keep this reliable in production. Log every Arbiter decision — this becomes your audit trail and your eval labels.

**Team:** 1–2 engineers, 4–6 weeks, largely parallel with Phase 3.

---

## 6. Phase 5 — Graph-Constrained Generation & Verifier Agent

1. Draft generation: standard RAG generation call over the Arbiter's `Primary`/`Supporting` candidates.
2. Verifier Agent: parse claims/citations out of the draft (structured extraction again), then run three graph checks against the IRAC graph — path existence, overruling checks (traverse for `OVERRULES` edges from higher/coordinate courts), statute freshness (`REPEALED`/`STALE` properties). Implement each as a parameterized Cypher query, not a generic "ask the LLM if this is true" — the whole point is that this check is deterministic and graph-grounded, not another probabilistic hop.
3. Revision loop: on `INVALID`/`STALE`, feed the explicit rejection reason back to the generator; cap at two revision attempts, then abstain (`"Information Not Found"`) rather than loop indefinitely or silently ship an unverified claim.
4. Conflict handling: on unresolved `CONFLICTS_WITH` with no `RESOLVED_BY`, short-circuit straight to surfacing both sides to the user — this should be a hard branch in the code path, not something you hope the LLM does consistently on its own.

**Team:** 1–2 engineers, 4–6 weeks, depends on Phase 3 graph being populated and QA'd first.

---

## 7. Phase 6 — Deployment & Evaluation

**Deployment:**
- Expose via MCP for agentic integrations (Claude Desktop, Cursor, internal chatbots) using the standard `mcpServers` HTTP config shown in the design doc — this matches how PageIndex itself is already integrated via MCP, so reuse that pattern rather than inventing a new one.
- Agent tool surface: mirror PageIndex's own recommended agentic pattern — `get_document_structure()`, `get_page_content(pages)` — plus your own `query_irac_graph()` tool for the Verifier checks, and `get_case_conflicts()` for surfacing doctrinal splits.
- Support self-hosted VPC/on-prem deployment as a first-class option, not an afterthought — this is typically a hard requirement for enterprise legal clients handling privileged material.

**Evaluation — build your own benchmark, don't assume a public "Legal RAG Bench" exists:**
1. Curate a jurisdiction- and practice-area-specific eval set (e.g., 150–300 question/answer pairs with ground-truth citations, drawn from real matters with client consent or synthetic/public case law) before claiming any accuracy numbers.
2. Track precision, recall, and citation-validity rate separately — citation-validity (does the cited case/section actually exist and say what's claimed) is the metric that matters most for liability exposure, more than raw answer accuracy.
3. Track latency at p50/p95 explicitly. Expect the two-call tree-search plus Arbiter plus Verifier pipeline to run meaningfully slower than a single vector lookup (industry cross-domain comparisons put vector RAG around ~1.6s average vs. roughly 2x that for tree-reasoning approaches) — this is a known, accepted trade-off in the current literature for precision-critical domains, not a sign something is broken.
4. Re-run the eval set after any change to the IRAC extraction prompts or the Verifier's graph queries — these are the two components most likely to silently regress.

---

## 8. Suggested timeline (single pilot practice area / jurisdiction)

| Phase | Duration | Can run in parallel with |
|---|---|---|
| 1. Ingestion & parsing (text path) | 4–6 wks | — |
| 2. Tree construction (PageIndex integration) | 2–3 wks | tail end of Phase 1 |
| 3. IRAC graph + population + QA | 6–10 wks | Phases 1–2 |
| 4. Detectors + Arbiter | 4–6 wks | Phase 3 |
| 5. Verifier Agent + graph-constrained generation | 4–6 wks | after Phase 3 graph is QA'd |
| 6. Deployment (MCP/API) + eval harness | 3–4 wks | overlapping with Phase 5 |

Realistic end-to-end for a working pilot on one practice area: **~4–5 months** with a team of 4–6 (2 ingestion/parsing engineers, 1–2 ML/backend engineers on graph + retrieval, 1 engineer on generation/verification, 1 legal domain reviewer). The vision/M3DocDep track and multi-jurisdiction scale-out are follow-on phases, not part of this pilot.

---

## 9. Key risks to flag now

- **Citation-relationship extraction accuracy directly gates the Verifier Agent's trustworthiness.** If `OVERRULES`/`CITES` edges are noisy, the Verifier will confidently validate bad claims or veto good ones. This is the single highest-leverage place to invest human QA time.
- **PageIndex is a young, fast-moving OSS project** (first released Sept 2025) — pin versions, don't auto-update in production, and budget time to track breaking changes to its tree schema/API.
- **FalkorDB's license (SSPL) may not clear legal/procurement review** for some enterprise clients even though it's free to self-host — confirm this early rather than after the graph layer is built on it.
- **Latency stacking:** tree navigation (2 calls) + Arbiter (1 call) + generation (1 call) + Verifier extraction (1 call) + possible revision loop (up to 2 more) can mean 5–8 sequential LLM calls per query. Parallelize where the dependency graph allows (e.g., detectors run concurrently), and set explicit latency SLAs before this surprises anyone in a demo.
