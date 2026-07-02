import pandas as pd
import re
import json

# Expected chapter counts for the three Acts
EXPECTED_CHAPTERS = {
    "BNS": 20,    # Chapters I to XX
    "BNSS": 39,   # Chapters I to XXXIX (with Chapter V injected)
    "BSA": 12     # Chapters I to XII
}

def validate_datasets(page_df: pd.DataFrame, line_df: pd.DataFrame, toc_df: pd.DataFrame, schedule_df: pd.DataFrame):
    print("\n==================== Running Validation Checks ====================")
    errors = []
    
    # 1. Basic Shape and Nullity checks
    print(f"DataFrames shape: page_df={page_df.shape}, line_df={line_df.shape}, toc_df={toc_df.shape}")
    if not schedule_df.empty:
        print(f"schedule_df shape={schedule_df.shape}")
        
    for name, df in [("page_df", page_df), ("line_df", line_df), ("toc_df", toc_df)]:
        if df.empty:
            errors.append(f"Error: {name} is empty.")
            
    # 2. Orphans Checks
    # Every section_id in line_df must exist in toc_df
    toc_ids = set(toc_df["section_id"].unique())
    line_ids = set(line_df["section_id"].unique())
    orphans = line_ids - toc_ids
    if orphans:
        errors.append(f"Error: Orphans found! The following section_ids in line_df are not in toc_df: {orphans}")
    else:
        print("Success: No orphaned lines. Every line maps to a valid structural node in toc_df.")
        
    # 3. Chapter Structure Verification
    for act, expected in EXPECTED_CHAPTERS.items():
        act_toc = toc_df[toc_df["act_code"] == act]
        chapters = act_toc[act_toc["node_type"] == "chapter"]
        chapter_count = len(chapters)
        print(f"Act {act}: found {chapter_count} chapters (expected {expected}).")
        
        # Verify that chapter numbers are not duplicated
        chap_nos = chapters["chapter_no"].tolist()
        duplicates = set([x for x in chap_nos if chap_nos.count(x) > 1])
        if duplicates:
            errors.append(f"Error: Duplicate chapters in Act {act}: {duplicates}")
            
        if chapter_count != expected:
            errors.append(f"Error: Chapter count mismatch for {act}. Found {chapter_count}, expected {expected}.")
            
    # 4. Section Numbering Sequence Contiguity Check
    for act in EXPECTED_CHAPTERS.keys():
        act_toc = toc_df[(toc_df["act_code"] == act) & (toc_df["node_type"] == "section")]
        sections = act_toc["section_no"].dropna().tolist()
        
        # Parse section numbers to integers
        section_ints = []
        for s in sections:
            # Strip sub-sections (a), (b), etc.
            match = re.match(r'^(\d+)', str(s))
            if match:
                section_ints.append(int(match.group(1)))
                
        if not section_ints:
            errors.append(f"Error: No section numbers found in Act {act}.")
            continue
            
        max_sec = max(section_ints)
        min_sec = min(section_ints)
        
        # We expect sections to start at 1
        if min_sec != 1:
            errors.append(f"Warning: Act {act} sections start at {min_sec} instead of 1.")
            
        # Find gaps in the sequence
        expected_seq = set(range(1, max_sec + 1))
        actual_seq = set(section_ints)
        gaps = expected_seq - actual_seq
        
        # Find duplicates
        seen = set()
        dupes = set()
        for x in section_ints:
            if x in seen:
                dupes.add(x)
            seen.add(x)
            
        print(f"Act {act}: sections span from {min_sec} to {max_sec}.")
        if gaps:
            errors.append(f"Warning: Gaps found in section numbering for Act {act}: {sorted(list(gaps))}")
        if dupes:
            errors.append(f"Warning: Duplicate section numbers found in Act {act}: {sorted(list(dupes))}")
            
    # 5. BNSS Schedule Checks
    if not schedule_df.empty:
        # Check columns
        expected_cols = ["page_no", "section", "offence", "punishment", "cognizable", "bailable", "court"]
        for c in expected_cols:
            if c not in schedule_df.columns:
                errors.append(f"Error: Expected column '{c}' missing in schedule_df.")
                
        # Row count sanity
        rows_count = len(schedule_df)
        print(f"BNSS First Schedule classification table has {rows_count} rows.")
        if rows_count < 400:
            errors.append(f"Error: Unusually low row count in First Schedule ({rows_count} rows).")
            
        # Check that there are no remaining merged cells
        long_fields = []
        for idx, row in schedule_df.iterrows():
            for field in ["cognizable", "bailable", "court"]:
                val = str(row[field])
                if len(val) > 100:
                    long_fields.append((idx, row["section"], field, val[:30] + "..."))
        if long_fields:
            errors.append(f"Warning: Found fields in schedule_df that look like unmerged text: {long_fields[:5]}")
            
    # Summary of validation
    errors_only = [e for e in errors if e.startswith("Error")]
    warnings_only = [w for w in errors if w.startswith("Warning")]
    
    if warnings_only:
        print("\nValidation Warnings:")
        for warn in warnings_only:
            print(f"  - {warn}")
            
    if errors_only:
        print("\nValidation FAILED with the following errors:")
        for err in errors_only:
            print(f"  - {err}")
        return False
    else:
        print("\nSuccess: All core validation checks passed successfully!")
        return True
