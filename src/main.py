import os
import sys
import time
import pandas as pd

# Path injection for running directly as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import PDFParser
from src.sop_parser import SOPParser
from src.generic_parser import GenericPDFParser
from src.act_adapters import NEW_ACT_ADAPTERS, PDF_FILENAMES
from src.validation import validate_datasets

# Define paths
SOURCE_DIR = "source_documents"
OUTPUT_DIR = "output"

# Original acts parsed by the specialised parser
PDF_FILES = {
    "BNS":  os.path.join(SOURCE_DIR, "BNS.pdf"),
    "BNSS": os.path.join(SOURCE_DIR, "BNSS.pdf"),
    "BSA":  os.path.join(SOURCE_DIR, "BSA.pdf"),
    "SOP":  os.path.join(SOURCE_DIR, "Standard_Operating_Procedures.pdf"),
}


def main():
    print("==================================================================")
    print("             Vectorless-RAG Phase 1 Ingestion Pipeline           ")
    print("==================================================================")

    start_time = time.time()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_pages    = []
    all_lines    = []
    all_tocs     = []
    bnss_schedule_df = pd.DataFrame()

    # ------------------------------------------------------------------
    # 1. Parse original 4 corpora with specialised parsers
    # ------------------------------------------------------------------
    for act, path in PDF_FILES.items():
        if not os.path.exists(path):
            print(f"Error: Source PDF for {act} not found at {path}")
            continue

        print(f"\nParsing {act} from: {path}...")
        act_start = time.time()

        if act == "SOP":
            parser = SOPParser(path)
        else:
            parser = PDFParser(act, path)

        page_df, line_df, toc_df, schedule_df = parser.parse()

        print(f"Finished parsing {act} in {time.time() - act_start:.2f} seconds.")
        print(f"  Pages extracted: {len(page_df)}")
        print(f"  Lines extracted: {len(line_df)}")
        print(f"  TOC nodes: {len(toc_df)}")

        all_pages.append(page_df)
        all_lines.append(line_df)
        all_tocs.append(toc_df)

        if act == "BNSS":
            bnss_schedule_df = schedule_df

    # ------------------------------------------------------------------
    # 2. Parse 5 new acts with the generic parser
    # ------------------------------------------------------------------
    print("\n--- Phase 9: Parsing 5 new statutory acts ---")
    for adapter in NEW_ACT_ADAPTERS:
        pdf_filename = PDF_FILENAMES[adapter.act_code]
        path = os.path.join(SOURCE_DIR, pdf_filename)

        if not os.path.exists(path):
            print(f"Warning: PDF for {adapter.act_code} not found at {path} — skipping.")
            continue

        print(f"\nParsing {adapter.act_code} from: {path}...")
        act_start = time.time()

        parser = GenericPDFParser(adapter, path)
        page_df, line_df, toc_df, _ = parser.parse()

        print(f"Finished parsing {adapter.act_code} in {time.time() - act_start:.2f} seconds.")
        print(f"  Pages extracted: {len(page_df)}")
        print(f"  Lines extracted: {len(line_df)}")
        print(f"  TOC nodes: {len(toc_df)}")

        sections = toc_df[toc_df["node_type"] == "section"]
        chapters = toc_df[toc_df["node_type"] == "chapter"]
        print(f"  Chapters: {len(chapters)}, Sections: {len(sections)}")

        all_pages.append(page_df)
        all_lines.append(line_df)
        all_tocs.append(toc_df)

    # ------------------------------------------------------------------
    # 3. Combine and save
    # ------------------------------------------------------------------
    print("\nAssembling final unified datasets...")
    combined_page_df = pd.concat(all_pages, ignore_index=True)
    combined_line_df = pd.concat(all_lines, ignore_index=True)
    combined_toc_df  = pd.concat(all_tocs,  ignore_index=True)

    print(f"\nWriting Parquet datasets to '{OUTPUT_DIR}' directory...")
    combined_page_df.to_parquet(os.path.join(OUTPUT_DIR, "page_df.parquet"),  index=False)
    combined_line_df.to_parquet(os.path.join(OUTPUT_DIR, "line_df.parquet"),  index=False)
    combined_toc_df.to_parquet(os.path.join(OUTPUT_DIR, "toc_df.parquet"),    index=False)

    if not bnss_schedule_df.empty:
        bnss_schedule_df.to_parquet(
            os.path.join(OUTPUT_DIR, "schedule_df.parquet"), index=False
        )

    print("Success: All Parquet files saved.")

    # ------------------------------------------------------------------
    # 4. Validation
    # ------------------------------------------------------------------
    success = validate_datasets(
        combined_page_df,
        combined_line_df,
        combined_toc_df,
        bnss_schedule_df,
    )

    print("\n------------------------------------------------------------------")
    print(f"Pipeline completed in {time.time() - start_time:.2f} seconds.")
    print("==================================================================")


if __name__ == "__main__":
    main()
