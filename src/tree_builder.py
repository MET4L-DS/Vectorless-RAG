import os
import json
import hashlib
import pandas as pd

# ---------------------------------------------------------------------------
# Statute metadata registry
# Populated here for existing acts; Bucket 2 will extend this for new acts.
# ---------------------------------------------------------------------------
_STATUTE_METADATA: dict[str, dict] = {
    # Original corpora
    "BNS":   {"jurisdiction": "national", "status": "in_force", "enactment_date": "2024-07-01", "corpus_type": "statute"},
    "BNSS":  {"jurisdiction": "national", "status": "in_force", "enactment_date": "2024-07-01", "corpus_type": "statute"},
    "BSA":   {"jurisdiction": "national", "status": "in_force", "enactment_date": "2024-07-01", "corpus_type": "statute"},
    "SOP":   {"jurisdiction": "national", "status": "in_force", "enactment_date": "2023-01-01", "corpus_type": "sop"},
    # Phase 9 — Corpus expansion
    "IT":    {"jurisdiction": "national", "status": "in_force", "enactment_date": "2000-10-17", "corpus_type": "statute"},
    "JJA":   {"jurisdiction": "national", "status": "in_force", "enactment_date": "2016-01-15", "corpus_type": "statute"},
    "POCSO": {"jurisdiction": "national", "status": "in_force", "enactment_date": "2012-11-14", "corpus_type": "statute"},
    "NDPS":  {"jurisdiction": "national", "status": "in_force", "enactment_date": "1985-09-16", "corpus_type": "statute"},
    "PCA":   {"jurisdiction": "national", "status": "in_force", "enactment_date": "1988-09-09", "corpus_type": "statute"},
}

# Full titles for index.json generation (keyed by act_code)
ACT_FULL_TITLES: dict[str, str] = {
    "BNS":   "BHARATIYA NYAYA SANHITA, 2023",
    "BNSS":  "BHARATIYA NAGARIK SURAKSHA SANHITA, 2023",
    "BSA":   "BHARATIYA SAKSHYA ADHINIYAM, 2023",
    "SOP":   "Telangana Police Standard Operating Procedures",
    "IT":    "THE INFORMATION TECHNOLOGY ACT, 2000",
    "JJA":   "THE JUVENILE JUSTICE (CARE AND PROTECTION OF CHILDREN) ACT, 2015",
    "POCSO": "THE PROTECTION OF CHILDREN FROM SEXUAL OFFENCES ACT, 2012",
    "NDPS":  "THE NARCOTIC DRUGS AND PSYCHOTROPIC SUBSTANCES ACT, 1985",
    "PCA":   "THE PREVENTION OF CORRUPTION ACT, 1988",
}

# Reference page counts per act (used for index.json metadata)
ACT_PAGE_COUNTS: dict[str, int] = {
    "BNS":   112,
    "BNSS":  279,
    "BSA":   54,
    "SOP":   238,
    "IT":    41,
    "JJA":   48,
    "POCSO": 17,
    "NDPS":  54,
    "PCA":   20,
}

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
    Loads Parquet files and constructs the unsummarized tree structures for all acts present
    in the Parquet output (BNS, BNSS, BSA, SOP, and any new acts added in Bucket 2).
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

    # Auto-discover all acts present in the Parquet — no hardcoded list needed.
    # Known acts are ordered first so BNS/BNSS/BSA/SOP always appear before extension acts.
    _KNOWN_ORDER = ["BNS", "BNSS", "BSA", "SOP"]
    discovered = list(toc_df["act_code"].unique())
    acts = [a for a in _KNOWN_ORDER if a in discovered] + \
           [a for a in discovered if a not in _KNOWN_ORDER]
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
            
            # Retrieve static corpus metadata for this act (falls back to safe defaults)
            act_meta = _STATUTE_METADATA.get(act, {
                "jurisdiction": "national",
                "status": "in_force",
                "enactment_date": None,
                "corpus_type": "statute"
            })

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
                    "corpus_type": act_meta["corpus_type"],
                    "jurisdiction": act_meta["jurisdiction"],
                    "status": act_meta["status"],
                    "enactment_date": act_meta["enactment_date"],
                    "supersedes": [],       # Populated in Phase 11 for IPC→BNS / CrPC→BNSS transitions
                    "interpreted_by": [],   # Populated in Phase 10 when case law nodes are added
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
                        
                    bnss_meta = _STATUTE_METADATA.get("BNSS", {})
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
                            "corpus_type": bnss_meta.get("corpus_type", "statute"),
                            "jurisdiction": bnss_meta.get("jurisdiction", "national"),
                            "status": bnss_meta.get("status", "in_force"),
                            "enactment_date": bnss_meta.get("enactment_date"),
                            "supersedes": [],
                            "interpreted_by": [],
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
