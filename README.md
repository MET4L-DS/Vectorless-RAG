# Vectorless-RAG — Ingestion & Parsing Pipeline (Phase 1)

This project contains the ingestion and parsing pipeline for Phase 1 of the Vectorless-RAG project. It converts the three Bharatiya Nyaya Sanhita Acts (BNS, BNSS, BSA) from PDF format into structured Parquet datasets.

## Project Structure

- `source_documents/`: Directory containing the source PDF documents (`BNS.pdf`, `BNSS.pdf`, `BSA.pdf`).
- `src/`: Core Python modules.
  - `parser.py`: PDF text layout extractor, heading parser, Chapter V injected correction, and coordinate-based First Schedule table parser.
  - `validation.py`: Re-runnable validation harness verifying dataset shape, orphans, contiguity, and chapter counts.
  - `main.py`: Coordinator that runs the pipeline and exports Parquet datasets.
- `output/`: Directory where parsed Parquet files are saved:
  - `page_df.parquet`: Page-grain text and metadata.
  - `line_df.parquet`: Line-grain layout, font information, and mapping to section IDs.
  - `toc_df.parquet`: Tree-structured Table of Contents (TOC) hierarchy.
  - `schedule_df.parquet`: Parsed classification table of the First Schedule of BNSS.
- `requirements.txt`: Python dependencies.

## Setup and Execution

1. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Run the ingestion pipeline:
   ```powershell
   python src/main.py
   ```

3. Verification:
   The pipeline prints detailed validation summary statistics upon completion. It ensures:
   - Every line maps to a valid structural node (no orphans).
   - Chapters match printed TOC expectations (20 for BNS, 39 for BNSS, 12 for BSA).
   - Section numbers form unbroken contiguous runs (1..358 for BNS, 1..531 for BNSS, 1..170 for BSA).
   - The BNSS First Schedule table contains all 445 offence rows.
