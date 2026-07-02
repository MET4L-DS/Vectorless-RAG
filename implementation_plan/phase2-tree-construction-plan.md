# Phase 2 Implementation Plan — Tree Construction
*Solo-project version, builds directly on your validated Phase 1 outputs (`page_df`, `line_df`, `toc_df`, `schedule_df`)*

---

## 0. Framing: build the tree yourself, reuse PageIndex's schema and algorithm

The original plan said "adopt PageIndex" for tree construction. For your corpus specifically, adopt the **idea**, not the **ingestion pipeline**:

| What PageIndex's own PDF path would do | What you should do instead |
|---|---|
| Re-parse BNS/BNSS/BSA from scratch with its own TOC/heading detector | Reuse your already-validated `toc_df` — it's corpus-tuned (Chapter V fix, schedule handling, cross-refs) in a way PageIndex's generic parser has no way to know about |
| Summarize nodes bottom-up via LLM | **Keep this part** — it's the genuinely valuable piece: bottom-up leaf → section → chapter → root summarization |
| Emit a JSON tree (`node_id`, `title`, `summary`, `content`, `children`, `metadata`) | **Keep this schema** — it's the interchange format the rest of your system (retrieval, MCP tools) will expect |

So Phase 2 is: **write your own small tree-builder + summarizer script** that consumes your Parquet files and emits the PageIndex-style JSON tree, rather than installing the `pageindex` package and feeding it raw PDFs. This is less code than it sounds — the hard part (structure) is already done.

If you later want to compare against PageIndex's own output as a sanity check, that's a good Day 6 stretch task, not a dependency.

---

## 1. Target output contract

One JSON tree per Act, plus a thin top-level index tying the three together (they're one legal corpus, cross-referencing each other constantly).

```
BNS_root
├── metadata: {act_code, full_title, total_sections, total_pages}
├── summary: "..."               (root-level, generated last)
├── children: [chapter nodes]
    ├── CH_I (level=1)
    │   ├── summary: "..."
    │   ├── children: [section nodes]
    │       ├── S1 (level=2, leaf)
    │       │   ├── title, summary, content (raw text)
    │       │   ├── metadata: {page_range, cross_references, node_type: "section"}
    │       └── S2 ...
    └── CH_XX ...
```

Plus a **corpus-level `index.json`**: `{"BNS": "<path>", "BNSS": "<path>", "BSA": "<path>"}` with each act's root summary inlined — this is what a future "which Act does this question belong to" routing step will read first, before descending into any one tree.

**Node types to handle** (from your Phase 1 `node_type` column): `chapter`, `section`, `schedule`, `front_matter`. Each needs slightly different summarization treatment (see §3).

**Strip rule:** `content` is populated **only on leaf nodes** (sections, schedule rows, form entries). Chapter and root nodes carry `summary` but `content: null` — this is what keeps the navigation-time payload small (your target: whole 3-Act scaffold under ~10–12k tokens, matching the ~3–4k-tokens-per-300-page-doc figure from the design doc, scaled to your ~445-page combined corpus).

---

## 2. Tooling decisions

| Need | Choice | Why |
|---|---|---|
| LLM for summarization | **Claude Haiku 4.5** via Anthropic API, or GPT-4.1-mini/gpt-4o-mini via OpenAI — pick whichever you already have a key for | Summarization is a bulk, low-complexity task across ~1,100+ nodes; you want the cheapest model that stays faithful to legal text (don't paraphrase away numbers/thresholds). Avoid using a frontier/expensive model for this pass — save that budget for Phase 4/5 reasoning calls. |
| Provider abstraction | `litellm` (optional) if you want to swap providers without rewriting call sites | Not required for a single-provider solo project — add it only if you're already unsure which model you'll settle on. |
| Caching / idempotency | A local `summary_cache.json` (or a `cached` SQLite table) keyed by `section_id + content_hash` | You will re-run this script. LLM calls cost money and time — never re-summarize a node whose underlying text hasn't changed. This is the single highest-leverage thing to build first. |
| Concurrency | `asyncio` + a semaphore (e.g., 5–10 concurrent calls) | ~1,100 leaf-level summarization calls run serially would take a long time; light concurrency gets you through the corpus in minutes, not hours. Respect provider rate limits. |
| Output storage | Same JSON tree files on disk, `tree/BNS.json`, `tree/BNSS.json`, `tree/BSA.json`, `tree/index.json` | Matches the design doc's schema and is what Phase 4/5 (Arbiter, Verifier) will load directly — no DB needed yet. |

---

## 3. Step-by-step build plan

### Day 1 — Tree assembly from `toc_df` (no LLM yet)
1. Load `toc_df`, `line_df`, `schedule_df` from your Phase 1 Parquet output.
2. Walk `toc_df` and build the parent→children structure purely from `parent_id`/`level`, with `node_id` reused as-is from Phase 1 (you already made these stable — don't regenerate them here).
3. For every leaf node (`node_type == "section"`), populate `content` by concatenating the corresponding `line_df` rows for that `section_id`, in page/line order, **including** sub-sections/clauses/illustrations/explanations as running text (these were tagged, not dropped, in Phase 1 — now's where that pays off).
4. For `schedule` nodes: each row of `schedule_df` (offence classification table) becomes its own tiny leaf under a `Schedule I` chapter node; each `FORM No. N` block becomes its own leaf under a `Schedule II` chapter node. Don't summarize table rows individually yet — flag them as `node_type: "schedule_row"` so §3 Day 3 can batch them differently.
5. Serialize the *unsummarized* skeleton (title/content/metadata present, `summary: null` everywhere) to JSON and eyeball it. This alone is a useful checkpoint — if the tree shape is wrong, you want to know before spending any LLM budget.

### Day 2 — Cross-reference and metadata wiring
1. Attach the `cross_references` list you extracted in Phase 1 to each section node's `metadata` field, split into `internal_refs` (same Act) and `cross_act_refs` (with target act code + section number).
2. Add `page_range: [start_page, end_page]` to every node from `toc_df`.
3. Add `token_estimate` per node (rough: `len(content) // 4`) — you'll want this in Day 3 to decide summary length targets and to catch any pathologically long leaf (e.g., section 143 Trafficking, which has many sub-sections) that might need special handling.
4. Re-run your Phase 1 validation harness against the assembled tree as a structural regression check: every `section_id` from `toc_df` should appear exactly once as a tree node with non-null `content`.

### Day 3 — Leaf summarization (the first real LLM pass)
1. Write the leaf summarizer: one call per section, prompt roughly —
   > "Summarize this section of the [Act name] in 2–4 sentences. Preserve exact numbers, thresholds, punishments, and defined terms verbatim. Do not add interpretation. Section text: {content}"
2. **This is legal text — precision matters more than fluency.** Don't let the model round "not less than seven years" into "several years," don't let it drop exceptions/provisos. Add an explicit instruction against paraphrasing numeric penalties, and spot-check ~20 summaries against source text for exactly this failure mode before trusting the rest.
3. Batch schedule rows differently: rather than one LLM call per First Schedule row (445 rows — wasteful and low-value), summarize the *table as a whole* per chapter grouping (e.g., "Offences under Chapter V (sexual offences) and their classification") and let individual rows keep only their raw structured data (offence, section, punishment, cognizability, bailability, court) with no separate LLM summary — a table row doesn't need prose summarization, the row *is* the content.
4. Run with concurrency + cache. Expect this to be the most expensive and slowest step in Phase 2 (~1,100 section leaves, worth checking actual cost after the first ~50 calls before letting it run unattended on the rest).
5. Spot-check: pull 15–20 summaries at random across all three Acts, compare against source. Specifically check sections with unusual structure (e.g., BNS §101 Murder with its five Exceptions, BNS §63 Rape with its Explanations) — these are exactly where naive summarization drops nuance.

### Day 4 — Roll-up summarization (chapter and root levels)
1. For each chapter node, generate a summary from its **children's summaries** (not raw content) — this is the "roll-up" step from the design doc, and it's cheap since chapter-level input is now just a handful of short summaries, not thousands of words of statute text.
2. For `front_matter` nodes (List of Abbreviations, Statement of Objects and Reasons, enactment preamble), summarize once — low priority, don't over-invest.
3. For each Act's root node, generate a one-paragraph document-level summary from all chapter summaries — this becomes what your corpus-level `index.json` uses for Act-routing later.
4. Re-run the token-budget check: confirm the fully-stripped (content-free) tree for a single Act is a few thousand tokens, and the three-Act combined navigation scaffold is comfortably within a single context window with room to spare for the query and system prompt.

### Day 5 — Validation, cost log, and freeze
1. **Structural validation** (extends Phase 1's harness): every node has non-null `summary`; every leaf has non-null `content`; every non-leaf has `content: null`; `children` arrays match `toc_df` parent/child relationships exactly; no orphan or duplicate `node_id`s across the merged corpus.
2. **Summary quality validation**: run your ~20-sample manual spot-check from Day 3 as a fixed regression set — save the section IDs you checked so you can re-diff summaries after any prompt change.
3. **Cost/latency log**: record total LLM calls, total tokens, total $ spent, and wall-clock time for the full run. You'll want this baseline before Phase 3 (which is a heavier, more expensive LLM phase — graph population).
4. Commit `tree/BNS.json`, `tree/BNSS.json`, `tree/BSA.json`, `tree/index.json`, and the `summary_cache` alongside them, so a re-run without content changes costs nothing.

### Day 6 (buffer / optional) — Compare against upstream PageIndex
If you have time, run the actual `pageindex` self-hosted package against one Act's raw PDF and diff its tree shape against yours. This isn't required for the pipeline to work, but it's a cheap way to confirm your hand-built tree isn't missing something PageIndex's more general heuristics would have caught — and it gives you a concrete answer to "why didn't I just use PageIndex directly" if you ever need to justify the custom build.

---

## 4. Concrete schema (recap, made concrete for this corpus)

```python
{
  "node_id": "BNS_S64",                # reused from Phase 1, unchanged
  "level": 2,                          # 0=root, 1=chapter, 2=section
  "node_type": "section",              # chapter | section | schedule | schedule_row | front_matter
  "title": "Punishment for rape",
  "summary": "...",                    # always populated
  "content": "(1) Whoever, except...", # populated ONLY on leaves
  "children": [],                      # empty for leaves
  "metadata": {
    "act_code": "BNS",
    "page_range": [37, 37],
    "internal_refs": ["S63", "S66"],
    "cross_act_refs": [{"act": "BNSS", "section": "173"}],
    "token_estimate": 210
  }
}
```

---

## 5. Known traps specific to this step

- **Don't let the LLM "fix" what it thinks are errors in the statute text.** Legal text has deliberately repetitive, overlapping definitions (e.g., BNS §63's seven circumstances of rape) — a summarizer optimizing for concision will want to compress these into one clause and lose a legally material distinction. Explicit prompt guardrails + spot-checking is the mitigation, not a smarter model.
- **Cross-references inside `content` will confuse a naive summarizer into thinking a section is "about" another section.** E.g., BNSS §193 lists ~30 BNS section numbers verbatim (the ones subject to mandatory reporting) — a summary might wrongly imply §193 defines those offences itself. Consider a light post-processing check: if a summary asserts something only true of a cross-referenced section, that's a sign the prompt needs a clarifying instruction ("this section may reference other sections without incorporating their content").
- **Schedule I (445 rows) is not statute prose** — resist the urge to summarize it like the sections. It's already structured data; treat the "summary" as a short description of what the *chapter grouping* of rows covers, not a per-row narrative.
- **Re-running the whole pipeline without a cache will re-spend your LLM budget every time** you tweak an unrelated part of the script. Build the cache in Day 1–2, not as an afterthought in Day 5.
- **Token estimates using `len(content)//4` are rough for legal English** (lots of numbers, section-symbol punctuation, capitalized defined terms) — treat it as a guardrail for catching outliers, not a precise budget; if you want precision later, swap in the actual tokenizer for whichever model you use.

---

## 6. Definition of done for Phase 2 (solo)

- [ ] `tree/BNS.json`, `tree/BNSS.json`, `tree/BSA.json` generated, matching the schema in §4.
- [ ] `tree/index.json` corpus-level file with all three root summaries.
- [ ] Every `section_id` from Phase 1's `toc_df` appears exactly once as a leaf with non-null `content` and non-null `summary`.
- [ ] Every chapter/root node has a non-null `summary` and `content: null`.
- [ ] Cross-references from Phase 1 attached to node `metadata`, split into internal vs. cross-Act.
- [ ] Content-free (summary-only) tree for the combined 3-Act corpus fits comfortably in a single LLM context window — measured, not assumed.
- [ ] Summary cache in place and confirmed to make re-runs free (test by running the script twice and confirming zero new LLM calls on the second run).
- [ ] ~20-section manual spot-check of leaf summaries against source text, saved as a fixed regression list for future prompt changes.
- [ ] Cost/latency log committed (total calls, tokens, $, wall-clock time).

**What's explicitly deferred to later phases:** the IRAC knowledge graph and its population (Phase 3), the TOC/keyword/full-text detectors and the Arbiter consolidation logic (Phase 4), and any query-time retrieval at all — Phase 2 only builds the static tree artifact, it doesn't yet answer questions.
