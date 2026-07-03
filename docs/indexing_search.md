# Component Implementation: Hierarchical Indexing & Retrieval

Vectorless-RAG replaces vector similarity matches with hierarchical structures and guided tree traversal.

---

## 1. Hierarchical Index Construction (`src/tree_builder.py`, `src/build_tree.py`)

- **JSON Node Trees**: Converts Parquet tables into JSON structures mapped in `tree/`.
  Each node contains:
  - `node_id`: Structural key (e.g. `BNS_CII`, `BNS_S4`).
  - `title`: Header title.
  - `summary`: Descriptive snippet (automatically populated).
  - `content`: Complete body text (present on leaf nodes).
  - `children`: List of child nodes.
- **LLM Summary Builder (`src/summarizer.py`)**:
  - Hierarchical RAG requires summaries of higher-level nodes (Chapters) to help the navigator guide searches.
  - Generates summaries for each Chapter by feeding child section titles and content blocks into a summarization LLM call.

---

## 2. In-Memory Search Index (`src/retriever/corpus_index.py`)

The `CorpusIndex` class acts as the in-memory store:
- Loads tree JSON files (`BNS_tree.json`, `BNSS_tree.json`, `BSA_tree.json`, `SOP_tree.json`).
- Flattens leaves for rapid dictionary access via `get_node(node_id)`.

---

## 3. BM25 Index (`src/retriever/bm25_index.py`)

Exposes keyword search using the lightweight, fast `bm25s` library:
- **Index Scope**: Indexes the concatenated `title` and `summary` of all leaf nodes.
- **Scoring**: Computes BM25 query relevance. Normalized by dividing by the maximum score returned for the batch.
- **Filtering**: Supports act-filtering (e.g. searching only BNS or BNSS).

---

## 4. Tree Navigation (`src/retriever/tree_navigator.py`)

Performs structured, top-down LLM routing:
1. **Chapter Selection**: Evaluates the user query against the list of Chapter names and summaries using a structured LLM call (`call_model_structured`). It outputs `ChapterSelection` containing a list of chapter IDs.
2. **Section Selection**: For each selected Chapter, it retrieves all child Section titles. Another structured LLM call evaluates which specific sections match the query, outputting `SectionSelection` containing section IDs.
3. **Retrieval**: Hydrates the selected section IDs with full body contents.

---

## 5. Standard Operating Procedures (SOP) Retrieval (`src/retriever/sop_retriever.py`)

Handles checklist-centric SOP retrieval:
1. Calls the LLM to identify the target police procedures or guidelines.
2. Evaluates procedures using `call_model_structured` matching `NodeSelection` schemas.
3. Selects the most relevant SOP checklist blocks to include in the context.

---

## 6. Cross-Reference Resolution (`src/retriever/cross_ref_linker.py`)

Legal sections frequently cite other sections. The `CrossRefLinker` performs context enrichment:
- **Extraction**: Reads metadata cross-references (`cross_act_refs` and `internal_refs`) extracted during PDF ingestion.
- **Enrichment**: Resolves the target IDs (e.g., if a BNS section references a BNSS procedure) and appends their node contents to the retrieval package.
- **Metadata**: Labels resolved nodes with `retrieval_method = "cross_ref_from_<source_id>"` for complete auditability.
