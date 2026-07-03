# Component Implementation: Ingestion & Layout-Aware Parsing

The ingestion pipeline transforms unstructured Indian Legal Act PDFs (BNS, BNSS, BSA) and the Police Standard Operating Procedures (SOP) into highly structured, schema-compliant Parquet datasets.

---

## 1. Statutory Acts Parsing (`src/parser.py`)

The statutory PDF parser is implemented via the `PDFParser` class. It utilizes `PyMuPDF` (`fitz`) to read text elements, layout metrics, and fonts, mapping the document into structural nodes.

### Structural Extraction & Heading Recognition
The parser identifies hierarchical boundaries using regular expressions:
- **Chapters**: Matched via `^CHAPTER\s+([IVXLCM]+)$` (e.g., *CHAPTER V*).
- **Sections**: Matched via `^(\d{1,3}[A-Z]?)\s*\.\s*(.+)$` (e.g., *35. When police may arrest without warrant*).
- Chapters and sections partition the document's text lines into logical nodes.

### The Chapter V Correction Edge-Case
In the BNSS PDF, the text layout on the Chapter V start page causes the word `CHAPTER V` to appear in a separate reading block below the chapter name, resulting in a parsing misclassification. The parser implements a hardcoded state machine override:
```python
# Hardcoded Chapter V correction for BNSS
if self.act_code == "BNSS" and page_idx == 15 and not injected_chapter_v:
    current_chapter_no = "V"
    current_chapter_title = "ARREST OF PERSONS"
    current_chapter_id = "BNSS_CV"
    injected_chapter_v = True
```

### Coordinate-Based BNSS First Schedule Parser
The First Schedule of BNSS contains a multi-page table classifying offences (Cognizable/Non-Cognizable, Bailable/Non-Bailable, etc.).
- **Detection**: Triggered when `page_idx` is between `172` and `218` (inclusive).
- **Coordinate Grouping**: Extracts character spans using `page.get_text("dict")` and groups them by horizontal columns based on precise coordinate ranges:
  - *Column 1 (Section)*: `x` between `0` and `80`.
  - *Column 2 (Offence)*: `x` between `80` and `250`.
  - *Column 3 (Punishment)*: `x` between `250` and `350`.
  - *Column 4 (Cognizable)*: `x` between `350` and `420`.
  - *Column 5 (Bailable)*: `x` between `420` and `480`.
  - *Column 6 (Triable Court)*: `x` between `480` and `580`.
- **Text Reconstruction**: Spans within the same vertical row tolerance are concatenated to yield 445 contiguous schedule rows.

---

## 2. Police SOP Parsing (`src/sop_parser.py`)

The SOP parser is implemented in `SOPParser` to extract operational tasks, station instructions, and workflow checklists.

### Layout Blocks & Multi-line Header Merging
The SOP document's index spans pages 8 to 10. The parser groups horizontal lines within a vertical tolerance of `4.0` points, resolving multi-line headers and linking topics to their corresponding page offsets.

### Workflow Checklist Extraction
- Identifies checklist rows containing specific prefixes (e.g., `[ ]`, `Action Item`, or numeric steps).
- Maps each procedure to its parent chapter based on layout indentation and visual font sizes.

---

## 3. Data Schema and Parquet Storage

Parsed elements are exported under the `output/` directory as Apache Parquet files:

1. **`page_df.parquet`**:
   - `act_code`: `BNS`, `BNSS`, `BSA`, or `SOP`.
   - `page_number`: 1-based page index.
   - `text`: Extracted clean text of the page.
2. **`line_df.parquet`**:
   - `line_id`: Unique global index identifier.
   - `text`: Raw line content.
   - `font_size`, `font_name`: Style metrics used to recognize headings and weight nodes.
   - `section_id`: Structural mapping (links line to its section).
3. **`toc_df.parquet`**:
   - `section_id`: Primary key (e.g., `BNSS_S35`).
   - `parent_id`: Parent key for tree nesting.
   - `level`: Structural depth (0: Root, 1: Chapter, 2: Section).
   - `title`: Headings/Section title.
   - `node_type`: `root`, `chapter`, `section`, `schedule`, or `procedure`.
4. **`schedule_df.parquet`**:
   - `section_no`: Section reference.
   - `offence`, `punishment`, `cognizable`, `bailable`, `court_triable`: Classifications.
