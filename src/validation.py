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

    # 3b. Root & Hierarchy Structure Verification
    roots = toc_df[toc_df["node_type"] == "root"]
    if len(roots) != 3:
        errors.append(f"Error: Expected exactly 3 root nodes, found {len(roots)}: {roots['section_id'].tolist()}")
    else:
        for act in EXPECTED_CHAPTERS.keys():
            act_root = roots[roots["act_code"] == act]
            if act_root.empty:
                errors.append(f"Error: Missing root node for Act {act}.")
            else:
                row = act_root.iloc[0]
                if row["level"] != 0 or not pd.isna(row["parent_id"]):
                    errors.append(f"Error: Act {act} root node has invalid level ({row['level']}) or parent_id ({row['parent_id']}).")
                    
    # Check that all chapters point to their Act's root
    for act in EXPECTED_CHAPTERS.keys():
        act_toc = toc_df[toc_df["act_code"] == act]
        chapters = act_toc[act_toc["node_type"] == "chapter"]
        for _, chap in chapters.iterrows():
            expected_parent = f"{act}_root"
            if chap["parent_id"] != expected_parent:
                errors.append(f"Error: Chapter {chap['section_id']} has invalid parent_id: expected {expected_parent}, got {chap['parent_id']}.")
            if chap["level"] != 1:
                errors.append(f"Error: Chapter {chap['section_id']} has invalid level: expected 1, got {chap['level']}.")
                
        # Check front_matter
        front = act_toc[act_toc["node_type"] == "front_matter"]
        if not front.empty:
            frow = front.iloc[0]
            expected_parent = f"{act}_root"
            if frow["parent_id"] != expected_parent:
                errors.append(f"Error: Front matter of {act} has invalid parent_id: expected {expected_parent}, got {frow['parent_id']}.")
            if frow["level"] != 1:
                errors.append(f"Error: Front matter of {act} has invalid level: expected 1, got {frow['level']}.")
            
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
        expected_cols = ["act_code", "page_no", "section", "offence", "punishment", "cognizable", "bailable", "court"]
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

def validate_completed_trees(tree_dir="tree", output_dir="output"):
    import os
    import json
    import pandas as pd
    
    print("\n==================== Running Tree Validation Checks ====================")
    errors = []
    
    # 1. Check index.json
    index_path = os.path.join(tree_dir, "index.json")
    if not os.path.exists(index_path):
        errors.append(f"Error: index.json is missing in {tree_dir}.")
        return False
        
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        errors.append(f"Error: Failed to parse index.json: {e}")
        return False
        
    acts = ["BNS", "BNSS", "BSA"]
    for act in acts:
        if act not in index_data.get("acts", {}):
            errors.append(f"Error: Act {act} is missing in index.json.")
        else:
            act_info = index_data["acts"][act]
            if not act_info.get("summary"):
                errors.append(f"Error: Summary for Act {act} is missing or empty in index.json.")
            if not act_info.get("path"):
                errors.append(f"Error: Path for Act {act} is missing in index.json.")
                
    # 2. Check each Act's JSON tree
    all_nodes_flat = []
    
    for act in acts:
        act_path = os.path.join(tree_dir, f"{act}.json")
        if not os.path.exists(act_path):
            errors.append(f"Error: {act}.json is missing in {tree_dir}.")
            continue
            
        try:
            with open(act_path, "r", encoding="utf-8") as f:
                root_node = json.load(f)
        except Exception as e:
            errors.append(f"Error: Failed to parse {act}.json: {e}")
            continue
            
        # Collect all nodes recursively
        act_nodes = []
        def traverse(node):
            act_nodes.append(node)
            for child in node.get("children", []):
                traverse(child)
        traverse(root_node)
        all_nodes_flat.extend(act_nodes)
        
        # Verify root properties
        if root_node.get("level") != 0 or root_node.get("node_type") != "root":
            errors.append(f"Error: Root node for {act} has invalid level ({root_node.get('level')}) or node_type ({root_node.get('node_type')}).")
        if not root_node.get("summary"):
            errors.append(f"Error: Root node for {act} has empty or missing summary.")
        if root_node.get("content") is not None:
            errors.append(f"Error: Root node for {act} has non-null content.")
            
        # Verify node-specific properties
        for node in act_nodes:
            nid = node.get("node_id")
            ntype = node.get("node_type")
            level = node.get("level")
            summary = node.get("summary")
            content = node.get("content")
            children = node.get("children", [])
            
            # Every node must have a non-empty summary
            if not summary:
                errors.append(f"Error: Node {nid} has an empty or missing summary.")
                
            # Leaf nodes (node_type == "section" or "schedule_row")
            if ntype in ["section", "schedule_row"]:
                if content is None or len(content) == 0:
                    errors.append(f"Error: Leaf node {nid} has null or empty content.")
                if len(children) > 0:
                    errors.append(f"Error: Leaf node {nid} has children.")
            else:
                # Non-leaf nodes
                if content is not None:
                    errors.append(f"Error: Non-leaf node {nid} ({ntype}) has non-null content.")
                    
            # Check metadata fields
            meta = node.get("metadata", {})
            if not meta:
                errors.append(f"Error: Node {nid} is missing metadata.")
            else:
                for field in ["act_code", "page_range", "internal_refs", "cross_act_refs", "token_estimate", "stable_hash"]:
                    if field not in meta:
                        errors.append(f"Error: Node {nid} metadata is missing field '{field}'.")
                        
    # 3. Check duplicate node_ids across all acts
    node_ids = [n.get("node_id") for n in all_nodes_flat if n.get("node_id")]
    if len(node_ids) != len(set(node_ids)):
        seen = set()
        dupes = set()
        for x in node_ids:
            if x in seen:
                dupes.add(x)
            seen.add(x)
        errors.append(f"Error: Duplicate node_ids found: {dupes}")
        
    # 4. Check that combined nav scaffold fits within token budget (< 250,000 tokens)
    total_nav_tokens = sum(len(n.get("summary", "")) // 4 for n in all_nodes_flat)
    print(f"Total navigation scaffold token estimate: {total_nav_tokens} tokens (limit 250,000).")
    if total_nav_tokens >= 250000:
        errors.append(f"Error: Combined nav scaffold token count ({total_nav_tokens}) exceeds the 250,000 token limit.")
        
    # Summary of validation
    errors_only = [e for e in errors if e.startswith("Error")]
    warnings_only = [w for w in errors if w.startswith("Warning")]
    
    if warnings_only:
        print("\nTree Validation Warnings:")
        for warn in warnings_only:
            print(f"  - {warn}")
            
    if errors_only:
        print("\nTree Validation FAILED with the following errors:")
        for err in errors_only:
            print(f"  - {err}")
        return False
    else:
        print("\nSuccess: All tree validation checks passed successfully!")
        return True
