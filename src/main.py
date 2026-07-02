import os
import time
import pandas as pd
from parser import PDFParser
from validation import validate_datasets

# Define paths
SOURCE_DIR = "source_documents"
OUTPUT_DIR = "output"

PDF_FILES = {
    "BNS": os.path.join(SOURCE_DIR, "BNS.pdf"),
    "BNSS": os.path.join(SOURCE_DIR, "BNSS.pdf"),
    "BSA": os.path.join(SOURCE_DIR, "BSA.pdf")
}

def main():
    print("==================================================================")
    print("             Vectorless-RAG Phase 1 Ingestion Pipeline           ")
    print("==================================================================")
    
    start_time = time.time()
    
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    all_pages = []
    all_lines = []
    all_tocs = []
    bnss_schedule_df = pd.DataFrame()
    
    for act, path in PDF_FILES.items():
        if not os.path.exists(path):
            print(f"Error: Source PDF for {act} not found at {path}")
            continue
            
        print(f"\nParsing {act} Act from: {path}...")
        act_start = time.time()
        
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
            
    # Combine data from all Acts
    print("\nAssembling final unified datasets...")
    combined_page_df = pd.concat(all_pages, ignore_index=True)
    combined_line_df = pd.concat(all_lines, ignore_index=True)
    combined_toc_df = pd.concat(all_tocs, ignore_index=True)
    
    # Save datasets as Parquet
    print(f"\nWriting Parquet datasets to '{OUTPUT_DIR}' directory...")
    
    combined_page_df.to_parquet(os.path.join(OUTPUT_DIR, "page_df.parquet"), index=False)
    combined_line_df.to_parquet(os.path.join(OUTPUT_DIR, "line_df.parquet"), index=False)
    combined_toc_df.to_parquet(os.path.join(OUTPUT_DIR, "toc_df.parquet"), index=False)
    
    if not bnss_schedule_df.empty:
        bnss_schedule_df.to_parquet(os.path.join(OUTPUT_DIR, "schedule_df.parquet"), index=False)
        
    print("Success: All Parquet files saved.")
    
    # Run validation harness
    success = validate_datasets(
        combined_page_df, 
        combined_line_df, 
        combined_toc_df, 
        bnss_schedule_df
    )
    
    print("\n------------------------------------------------------------------")
    print(f"Pipeline completed in {time.time() - start_time:.2f} seconds.")
    print("==================================================================")

if __name__ == "__main__":
    main()
