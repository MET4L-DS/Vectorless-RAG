# Phase 1 Implementation Plan — Ingestion & Parsing Pipeline
*Solo-project version, scoped to the actual pilot corpus: BNS.pdf, BNSS.pdf, BSA.pdf*

---

## 0. Re-scoping Phase 1 for a solo project

The original plan sized Phase 1 for a small team (1–2 engineers, 4–6 weeks, +4–6 weeks for a vision fallback). As a solo builder, two things change the math a lot in your favor:

1. **Your actual corpus doesn't need the hard parts.** BNS, BNSS, and BSA (the Bharatiya Nyaya Sanhita, Bharatiya Nagarik Suraksha Sanhita, and — presumably — Bharatiya Sakshya Adhiniyam) are **born-digital, machine-readable, government-typeset Acts** with:
   - A clean `ARRANGEMENT OF SECTIONS` table of contents on the first few pages of each Act.
   - Rigidly consistent numbering: `CHAPTER I` → sub-heading → `1. Short title...—` style section headers, sub-sections as `(1)`, `(2)`, clauses as `(a)`, `(b)`, explanations/illustrations as their own labeled blocks.
   - No scanned pages, no handwriting, no rotated pages, no multi-column layout.
   - Heavy, explicit **cross-references between the three Acts** ("under section 173 of the Bharatiya Nagarik Suraksha Sanhita, 2023", "as defined in section 2 of the Bharatiya Nyaya Sanhita, 2023") — this is a gift for your `metadata.cross_references` field later.
   - One genuinely hard element: the **First Schedule classification table** in BNSS (a 6-column table: Section / Offence / Punishment / Cognizable / Bailable / Court) spanning ~50 pages, and the **Second Schedule** (a set of legal *forms*, not prose).

   This means you can **skip the vision/M3DocDep track and the "HiPS as a literal CV pipeline" framing entirely** for Phase 1. Regex- and font-metadata-based structural detection (PyMuPDF `"dict"` output) will get you correct hierarchy on ~95%+ of these documents on the first pass. Budget the vision fallback as a Phase 1.5 you probably never need to build.

2. **No team coordination overhead.** No handoff docs, no API contracts between engineers, no parallel-workstream scheduling. You can build vertically (one Act end-to-end) instead of horizontally (all four DataFrames across all documents at once), which surfaces bugs faster.

**Revised Phase 1 scope, solo:** build the four DataFrames (`line_df`, `toc_df`, `page_df`, `image_df`) for BNS, BNSS, and BSA, with stable `section_id`s and cross-reference extraction, validated against each Act's own printed table of contents. Vision fallback and general HiPS heading-classifier ML training are explicitly **out of scope** — deferred until/unless you feed the pipeline a scanned or badly-OCR'd document.

**Revised estimate: 4–6 focused working days**, not 4–6 weeks, split as below. (If you can only do evenings/weekends, spread this over ~2–3 weeks elapsed time — the point is the *work*, not the calendar.)

---

## 1. Tooling decisions

| Need | Choice | Why |
|---|---|---|
| PDF text + font/layout extraction | **PyMuPDF** (`pip install pymupdf`) | Fastest native-PDF extractor, gives per-span font name/size/flags/bbox via `page.get_text("dict")`, has a built-in table finder (`page.find_tables()`) for the First Schedule. Confirmed current on PyPI, wheels for Python 3.10–3.14. |
| Table extraction (First/Second Schedule) | `page.find_tables().to_pandas()` (PyMuPDF), fallback to `pdfplumber` if a table's borders confuse PyMuPDF | Schedule I is a bordered table; PyMuPDF's table finder handles bordered tables well. |
| Data storage for the four DataFrames | **pandas + Parquet** (or just SQLite if you want to query with SQL later) | Solo project — no need for a real database yet. Parquet keeps `line_df` (thousands of rows) fast to reload. |
| Stable IDs | `hashlib.sha1` over `(act_short_code, chapter_no, section_no, title)` | Survives re-ingestion; human-debuggable if you also keep a readable ID like `BNS_S64` alongside the hash. |
| Licensing note | PyMuPDF is AGPL-3.0. For a **personal, non-distributed project this is a non-issue** — AGPL only bites when you distribute/host the software for others. Flag it in your notes in case this ever leaves "personal project" status. |

You do **not** need Elasticsearch, a graph DB, or an LLM API key for Phase 1 — that's Phase 4/5. Phase 1 is pure parsing and is fully offline.

---

## 2. Target output contract (recap, made concrete for this corpus)

| DataFrame | Grain | Key columns for this corpus |
|---|---|---|
| `page_df` | 1 row/page | `act_code, page_no, page_text_raw, header_text, footer_text` (footers here are just page numbers — trivial to strip) |
| `line_df` | 1 row/text line | `act_code, page_no, line_no, text, bbox, font_name, font_size, is_bold, section_id` (FK into `toc_df`) |
| `toc_df` | 1 row/structural node | `section_id, act_code, level, parent_id, title, chapter_no, section_no, start_page, end_page, node_type` (`chapter`/`section`/`subsection`/`schedule`) |
| `image_df` | 1 row/figure | Expected to be **empty** for these three Acts — no embedded images/diagrams. Still build the extractor so the pipeline is general, but don't spend time debugging on zero rows. |

`node_type` is worth adding beyond the original design doc's schema — these Acts have five structurally distinct node kinds you'll want to tell apart later when building the tree: `chapter`, `section`, `illustration`, `explanation/proviso`, `schedule_table_row`.

---

## 3. Step-by-step build plan

### Day 1 — Raw extraction + line_df / page_df
1. Load each PDF with PyMuPDF; iterate pages; call `page.get_text("dict", sort=True)` to get blocks→lines→spans with bbox/font/size/flags.
2. Flatten to one row per line in `line_df`: concatenate span text within a line, keep the **dominant span's** font size/bold flag (headings in these Acts are single-font per line, so this is safe — verify on a sample).
3. Strip running headers/footers: in this corpus the only per-page cruft is a bare page number (e.g., a lone `"42"` line near the top or bottom, matching `^\d{1,3}$`) — drop those from `line_df` into a `page_df.footer_text` field instead of treating them as content.
4. Build `page_df` by grouping `line_df` per page.
5. **Sanity check:** page count and total line count roughly match a manual `pdftotext`/`page.get_text()` dump — catches encoding or extraction failures early.

### Day 2 — Heading detection (the HiPS-style subtasks, regex-first)
This corpus's headings are *extremely* regular — lean on that instead of a general classifier.

1. **Chapter detection:** lines matching `^CHAPTER\s+[IVXLCM]+$` (all-caps, roman numeral) immediately followed by an all-caps title line (e.g., `OF PUNISHMENTS`). These are `level=1` nodes.
2. **Section detection:** lines matching `^(\d{1,3})\.\s+(.+?)\.\s*[—-]` — i.e., `63. Rape.—` or `4. Punishments. —`. Capture the section number and the short title text before the em/en-dash. These are `level=2` nodes, child of the most recently seen chapter.
3. **Sub-heading detection** (the italic-ish "Of sexual offences" style lines that sit between a chapter title and its first section, e.g. in BNS Chapter V): these are un-numbered, title-case or small-caps lines between a chapter header and a section number — treat as `level=1.5` grouping nodes ("Of X") if you want the tree to mirror the printed TOC exactly, or fold them into the chapter node's summary if you want to keep the tree shallower. **Recommendation for a solo pilot: fold them in** — they add tree depth without much retrieval benefit, and you can always add them back later.
4. **Sub-section / clause detection:** `^\(\d+\)` and `^\([a-z]+\)` and `^\([ivx]+\)` at line start — these become `level=3` nodes or, more practically, are just kept as structured text *within* the parent section's `content`, not separate tree nodes. (PageIndex-style trees generally don't need a tree node per sub-clause — that's what the leaf `content` field is for.)
5. **Illustration/Explanation/Proviso blocks:** lines starting with `Illustration.`, `Illustrations.`, `Explanation.—`, `Explanation 1.—`, `Proviso`, `Exception` — tag these with a `block_type` field on the relevant `line_df` rows so they can be optionally excluded or specially formatted in leaf-node summaries later. Don't make them separate tree nodes.
6. **Section boundary assignment:** a section's `end_page`/end-line is simply "the line before the next detected section/chapter/schedule heading." Because numbering is monotonic and unbroken (1, 2, 3, ... 358 in BNS; no gaps), you get a **free validation check**: after parsing, assert the detected section numbers form a contiguous run 1..N with no duplicates or gaps. Any break means a mis-parsed heading (e.g., a cross-reference like "under section 84 of..." inside body text got mis-detected as a new heading — this *will* happen, see §5).

### Day 3 — Cross-reference extraction (the part generic HiPS doesn't cover, but your corpus rewards)
This is genuinely valuable for you later (Phase 3/4 — Arbiter and graph edges) and it's cheap to do now while you're already walking every line.

1. Regex for in-Act references: `\bsection\s+(\d+[A-Za-z]?)\b` (careful: only tag as a cross-reference when not immediately preceded by a section-heading pattern, to avoid self-references).
2. Regex for cross-Act references: `\bsection\s+(\d+)\s+of\s+(?:the\s+)?(Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita|Bharatiya Sakshya Adhiniyam)\b` (and common abbreviations `BNS`, `BNSS`, `BSA` if they appear).
3. Store matches as a list in `toc_df.metadata.cross_references` for the owning section (e.g., BNSS §193(6)(h) → references BNS §§64–71; BNSS §233(1) references BSA §148 and §26 — these are real examples already in your text).
4. This gives you, for free, a first-pass **citation graph edge list** you'll reuse almost as-is in Phase 3 (IRAC/Precedent graph) — worth doing now rather than re-deriving it later.

### Day 4 — Schedule/table handling
1. BNSS's **First Schedule** (classification table) is the one place `page.find_tables()` earns its keep. Extract it as its own `toc_df` node (`node_type="schedule"`, `level=1`), and store the parsed rows separately (e.g., `schedule_df`) rather than trying to force tabular data into `line_df`'s line-grain model — a table row isn't a "line" in the same sense.
2. Validate table extraction against the printed column headers (`Offence | Section | Punishment | Cognizable or Non-cognizable | Bailable or Non-bailable | By what Court triable`) — spot-check ~10 rows against the source text.
3. The **Second Schedule** (legal forms — summonses, warrants, bonds) is unstructured prose-with-blanks, not a table. Treat each `FORM No. N` as its own leaf node under a `schedule` chapter; don't try to over-structure the blank fields.
4. `image_df` extractor: run it, confirm it returns 0 rows for all three Acts (no embedded figures), and move on — don't over-invest here.

### Day 5 — Stable IDs, assembly, and validation harness
1. Assign `section_id` as e.g. `BNS_S64`, `BNSS_S193`, `BSA_S148` for human readability, plus a secondary `stable_hash` column (sha1 of act+chapter+section+title) matching the design doc's stability requirement in case titles ever get corrected on re-ingestion.
2. Assemble the final `toc_df` tree: `parent_id` links (section → chapter), `children` list per node.
3. **Automated validation checks** (this is your real Phase 1 "done" signal, not a subjective read-through):
   - Every section number 1..N appears exactly once per Act (catches false-positive/false-negative heading detection).
   - Every chapter in the extracted tree matches a chapter listed in that Act's own printed `ARRANGEMENT OF SECTIONS` (you have this ground truth already, in the first few pages of each PDF — diff your parsed TOC against it).
   - No `line_df` row is orphaned (every line maps to a `section_id`).
   - Spot-check 15–20 sections per Act by eye against the source PDF text (you already have the full text — this is fast).
4. Write the validation script so it's re-runnable — you'll want it again in Phase 2 once PageIndex consumes this output, and again anytime you add a fourth Act later.

### Day 6 (buffer / optional) — Second document type dry run
If you finish early, don't start Phase 2 yet — instead feed the pipeline one deliberately messier input (e.g., a scanned/rotated PDF, or a contract with non-numeric headings) just to see where the regex-first approach breaks. This tells you, cheaply, whether you actually need the HiPS "font-size clustering" fallback or the vision track at all before you build either — don't build either speculatively.

---

## 4. Concrete regex/heuristic cheat-sheet for this corpus

```python
import re

CHAPTER_RE = re.compile(r'^CHAPTER\s+([IVXLCM]+)$')
SECTION_RE = re.compile(r'^(\d{1,3}[A-Z]?)\.\s*(.+?)\.\s*[—-]\s*')
SUBSECTION_RE = re.compile(r'^\((\d+)\)')
CLAUSE_RE = re.compile(r'^\(([a-z]+)\)')
ILLUS_RE = re.compile(r'^Illustrations?\.')
EXPL_RE = re.compile(r'^Explanation\s*\d*\.\s*[—-]')
PROVISO_RE = re.compile(r'^Provided\s+(that|further|also)')
XREF_INTERNAL_RE = re.compile(r'\bsection\s+(\d+[A-Za-z]?)\b', re.IGNORECASE)
XREF_CROSSACT_RE = re.compile(
    r'\bsection\s+(\d+[A-Za-z]?)\s+of\s+(?:the\s+)?'
    r'(Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita|'
    r'Bharatiya Sakshya Adhiniyam)',
    re.IGNORECASE,
)
PAGE_NUM_NOISE_RE = re.compile(r'^\d{1,3}$')
```

Use font size/boldness only as a **tiebreaker**, not the primary signal — e.g., confirming that a `CHAPTER` line and its title really are larger/bolder than body text before trusting the regex match, which protects you from a stray body-text sentence that happens to start with a number.

---

## 5. Known traps specific to this corpus (worth pre-empting, not discovering at 11pm)

- **False-positive section headers from cross-references.** Body text like *"...under section 84 of Bharatiya Nagarik Suraksha Sanhita, 2023"* will not match `SECTION_RE` (no trailing `.—` on its own line) — but watch for edge cases like `"209. Non-appearance in response to a proclamation under section 84 of Bharatiya Nagarik Suraksha Sanhita, 2023."` where a genuine heading also *contains* a cross-reference in its own title. Your contiguous-numbering validation check (§3 Day 5) will catch any real breakage here.
- **Multi-line section titles.** Some titles wrap across two PDF lines before the dash (e.g., `"116. Grievous hurt.—The following kinds..."` is fine on one line, but a longer title might not be). Test the regex against joined-line text within a block, not raw single lines.
- **The Explanation/Illustration numbering resets per section** (`Explanation 1`, `Explanation 2` inside section 2, then `Explanation 1` again inside section 3) — don't treat these as globally unique IDs; scope them under their parent `section_id`.
- **"CHAPTER XX REPEAL AND SAVINGS"** appears in both BNS and BNSS as the final chapter — trivial, but make sure your end-of-document boundary logic doesn't drop the last section because there's no "next heading" to close it against (use EOF as an implicit boundary).
- **Preliminary front matter** (List of Abbreviations, Statement of Objects and Reasons, the Act's enactment preamble) isn't part of the numbered-section structure — bucket it into a synthetic `front_matter` node rather than discarding it, since it contains definitions and dates you may want retrievable later.

---

## 6. Definition of done for Phase 1 (solo)

- [ ] `page_df`, `line_df`, `toc_df` populated for BNS, BNSS, BSA and saved as Parquet.
- [ ] `toc_df` chapter list matches each Act's printed `ARRANGEMENT OF SECTIONS` 1:1.
- [ ] Section numbering validated contiguous with no gaps/dupes across all three Acts.
- [ ] Cross-reference list extracted (internal + cross-Act) and spot-checked against ~15 known examples (e.g., BNSS §193 → BNS §§103–332 list; BNSS §173 proviso → BNS §§64–79, 124).
- [ ] First Schedule table parsed into its own structure with header row verified.
- [ ] Validation script committed and re-runnable in under a few seconds (this corpus is small — under ~1,000 sections total across all three Acts).
- [ ] A short `README` note on what was deliberately *not* built (vision fallback, general ML heading classifier) and why, so future-you doesn't wonder if it was forgotten.

**What's explicitly deferred to later phases, not Phase 1:** feeding `toc_df`/`line_df` into PageIndex for tree summarization (Phase 2), any LLM calls at all (Phase 2 onward — Phase 1 is 100% deterministic/offline), and the IRAC graph population (Phase 3, though your Day 3 cross-reference extraction gives Phase 3 a running start).
