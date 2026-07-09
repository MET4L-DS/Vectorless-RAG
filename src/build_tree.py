import os
import json
import time
import asyncio
import pandas as pd

from src.tree_builder import build_unsummarized_trees, ACT_FULL_TITLES, ACT_PAGE_COUNTS
from src.summarizer import (
    run_summarization_pipeline,
    new_calls_count,
    model_calls_tracker
)
from src.validation import validate_completed_trees

def main():
    print("==================================================================")
    print("             Vectorless-RAG Phase 2 Tree Construction            ")
    print("==================================================================")

    tree_dir = "tree"
    os.makedirs(tree_dir, exist_ok=True)

    # 1. Build unsummarized trees from Parquets
    print("Step 1: Assembling unsummarized tree structures...")
    try:
        trees = build_unsummarized_trees("output")
    except Exception as e:
        print(f"Error during tree assembly: {e}")
        return

    # 2. Run summarization pipeline (async LLM calls + cache)
    print("\nStep 2: Starting Leaf and Roll-up Summarization...")
    start_time = time.time()
    try:
        asyncio.run(run_summarization_pipeline(trees))
    except Exception as e:
        print(f"Error during summarization pipeline: {e}")
        return
    elapsed_time = time.time() - start_time

    # 3. Write individual Act trees to JSON
    print("\nStep 3: Saving Act tree files...")
    for act, root_node in trees.items():
        act_file = os.path.join(tree_dir, f"{act}.json")
        with open(act_file, "w", encoding="utf-8") as f:
            json.dump(root_node, f, indent=2, ensure_ascii=False)
        print(f"  Saved tree for {act} to {act_file}")

    # 4. Save corpus index file (index.json) — dynamically built from all acts in trees
    print("Step 4: Creating corpus index.json...")
    index_file = os.path.join(tree_dir, "index.json")
    index_data = {
        "corpus": "Indian Legal Corpus — Vectorless RAG",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "acts": {}
    }
    for act_code, root_node in trees.items():
        # Count leaf sections (node_type == 'section') for metadata
        section_count = 0
        def _count_sections(node):
            nonlocal section_count
            if node.get("node_type") == "section":
                section_count += 1
            for child in node.get("children", []):
                _count_sections(child)
        _count_sections(root_node)

        index_data["acts"][act_code] = {
            "path":           f"tree/{act_code}.json",
            "full_title":     ACT_FULL_TITLES.get(act_code, act_code),
            "total_sections": section_count,
            "total_pages":    ACT_PAGE_COUNTS.get(act_code, 0),
            "summary":        root_node.get("summary", ""),
        }
        # Reset for next act
        section_count = 0
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved index.json to {index_file} ({len(index_data['acts'])} acts)")

    # 5. Save fixed regression spot check list
    print("Step 5: Writing spot check registration list...")
    spot_check_file = os.path.join(tree_dir, "spot_check_ids.json")
    spot_check_ids = [
        # Original regression IDs
        "BNS_S101", "BNS_S63", "BNSS_S193", "BNS_S356", "BSA_S57",
        "BNS_S1",   "BNS_S2",  "BNS_S4",   "BNS_S85",  "BNS_S143",
        "BNSS_S35", "BNSS_S63","BNSS_S173","BNSS_S210","BNSS_S359","BNSS_S531",
        "BSA_S1",   "BSA_S2",  "BSA_S24",  "BSA_S104",
        # Phase 9 — New act spot checks
        "IT_S66",   "IT_S66F", "IT_S43",   "IT_S79",
        "JJA_S4",   "JJA_S12", "JJA_S15",  "JJA_S56",
        "POCSO_S3", "POCSO_S5","POCSO_S19","POCSO_S28",
        "NDPS_S15", "NDPS_S27","NDPS_S37", "NDPS_S68A",
        "PCA_S7",   "PCA_S13", "PCA_S17",  "PCA_S19",
    ]
    with open(spot_check_file, "w", encoding="utf-8") as f:
        json.dump(spot_check_ids, f, indent=2)
    print(f"  Saved spot_check_ids.json to {spot_check_file}")

    # 6. Save execution run log
    print("Step 6: Writing run log stats...")
    
    total_nodes = 0
    def count_nodes(node):
        nonlocal total_nodes
        total_nodes += 1
        for child in node["children"]:
            count_nodes(child)
    for root in trees.values():
        count_nodes(root)

    run_log_file = os.path.join(tree_dir, "run_log.json")
    run_log = {
        "total_nodes": total_nodes,
        "total_calls": new_calls_count,
        "model_calls_per_model": model_calls_tracker,
        "wall_clock_s": elapsed_time,
        "new_calls": new_calls_count
    }
    with open(run_log_file, "w", encoding="utf-8") as f:
        json.dump(run_log, f, indent=2)
    print(f"  Saved run_log.json to {run_log_file}")

    # 7. Run validation checks
    print("\nStep 7: Initiating structural tree validation...")
    validation_success = validate_completed_trees(tree_dir, "output")
    
    print("\n------------------------------------------------------------------")
    if validation_success:
        print(f"Tree construction completed successfully in {elapsed_time:.2f} seconds!")
    else:
        print("Tree construction finished, but structural validation FAILED.")
    print("==================================================================")

if __name__ == "__main__":
    main()
