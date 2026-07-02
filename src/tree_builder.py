import os
import json
import hashlib
import pandas as pd

def process_xrefs(xref_str, current_act):
    """
    Process cross_references JSON string from Phase 1.
    Splits into internal_refs (e.g. 'S64') and cross_act_refs (e.g. {'act': 'BNSS', 'section': '173'}).
    """
    internal = []
    cross = []
    if not xref_str:
        return internal, cross
    try:
        refs = json.loads(xref_str)
    except Exception:
        refs = []
    for ref in refs:
        if ref.startswith(f"{current_act}_"):
            # Internal reference, strip act prefix (e.g. 'BNS_S85' -> 'S85')
            stripped = ref[len(current_act)+1:]
            internal.append(stripped)
        else:
            # Cross-act reference (e.g. 'BNSS_S173' -> {'act': 'BNSS', 'section': '173'})
            parts = ref.split("_", 1)
            if len(parts) == 2:
                act, sec = parts
                if sec.startswith("S"):
                    sec = sec[1:]
                cross.append({"act": act, "section": sec})
    return internal, cross

def build_unsummarized_trees(output_dir="output"):
    """
    Loads Parquet files and constructs the unsummarized tree structures for BNS, BNSS, and BSA.
    Returns a dict mapping act_code -> root_node_dict.
    """
    toc_path = os.path.join(output_dir, "toc_df.parquet")
    line_path = os.path.join(output_dir, "line_df.parquet")
    schedule_path = os.path.join(output_dir, "schedule_df.parquet")

    if not os.path.exists(toc_path) or not os.path.exists(line_path):
        raise FileNotFoundError("Required Parquet files are missing in output directory.")

    toc_df = pd.read_parquet(toc_path)
    line_df = pd.read_parquet(line_path)
    schedule_df = pd.read_parquet(schedule_path) if os.path.exists(schedule_path) else pd.DataFrame()

    # Concatenate text per section_id in line_df
    print("Concatenating section line contents...")
    section_texts = line_df.groupby("section_id")["text"].apply(lambda lines: " ".join(lines)).to_dict()

    acts = ["BNS", "BNSS", "BSA"]
    if "SOP" in toc_df["act_code"].values:
        acts.append("SOP")
    trees = {}

    for act in acts:
        print(f"Building skeleton tree for {act}...")
        act_toc = toc_df[toc_df["act_code"] == act].copy()
        
        # Instantiate all nodes as dicts
        node_map = {}
        root_node = None
        
        for _, row in act_toc.iterrows():
            node_id = row["section_id"]
            level = int(row["level"])
            node_type = row["node_type"]
            title = row["title"]
            
            # Content population
            content = None
            if node_type in ["section", "sop_procedure", "sop_form", "sop_reference", "sop_table"]:
                content = section_texts.get(node_id, "")
                
            # Cross references
            internal_refs, cross_act_refs = process_xrefs(row["cross_references"], act)
            
            token_est = len(content) // 4 if content else 0
            
            node = {
                "node_id": node_id,
                "level": level,
                "node_type": node_type,
                "title": title,
                "summary": None,
                "content": content,
                "children": [],
                "metadata": {
                    "act_code": act,
                    "page_range": [int(row["start_page"]), int(row["end_page"])],
                    "internal_refs": internal_refs,
                    "cross_act_refs": cross_act_refs,
                    "token_estimate": token_est,
                    "stable_hash": row["stable_hash"]
                }
            }
            
            node_map[node_id] = node
            if level == 0 and node_type == "root":
                root_node = node

        # Build parent-child relationships
        for _, row in act_toc.iterrows():
            node_id = row["section_id"]
            parent_id = row["parent_id"]
            
            if pd.isna(parent_id) or parent_id is None:
                continue
                
            if parent_id in node_map and node_id in node_map:
                node_map[parent_id]["children"].append(node_map[node_id])
            else:
                print(f"Warning: parent_id {parent_id} or node_id {node_id} not found in node_map.")

        # Special schedule handling for BNSS
        if act == "BNSS" and not schedule_df.empty:
            schedule_node_id = "BNSS_SCH1"
            if schedule_node_id in node_map:
                print("Appending First Schedule table rows as leaf nodes...")
                for idx, row in schedule_df.iterrows():
                    row_content = (
                        f"Section: {row['section']}\n"
                        f"Offence: {row['offence']}\n"
                        f"Punishment: {row['punishment']}\n"
                        f"Cognizable: {row['cognizable']}\n"
                        f"Bailable: {row['bailable']}\n"
                        f"Court: {row['court']}"
                    )
                    
                    row_id = f"BNSS_SCH1_R{idx}"
                    
                    # Try to parse section number for internal reference
                    section_num = str(row['section']).strip()
                    internal_refs = []
                    if section_num:
                        internal_refs.append(f"S{section_num}")
                        
                    row_node = {
                        "node_id": row_id,
                        "level": 2,
                        "node_type": "schedule_row",
                        "title": f"Schedule Row: Offence under Section {row['section']}",
                        "summary": None,
                        "content": row_content,
                        "children": [],
                        "metadata": {
                            "act_code": "BNSS",
                            "page_range": [int(row["page_no"]), int(row["page_no"])],
                            "internal_refs": internal_refs,
                            "cross_act_refs": [],
                            "token_estimate": len(row_content) // 4,
                            "stable_hash": hashlib.sha1(row_id.encode()).hexdigest()
                        }
                    }
                    
                    node_map[schedule_node_id]["children"].append(row_node)

        if root_node:
            trees[act] = root_node
        else:
            raise ValueError(f"Root node for {act} was not found in TOC.")

    return trees
