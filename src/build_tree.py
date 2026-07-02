import os
import json
import time
import asyncio
import pandas as pd

from src.tree_builder import build_unsummarized_trees
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

    # 4. Save corpus index file (index.json)
    print("Step 4: Creating corpus index.json...")
    index_file = os.path.join(tree_dir, "index.json")
    index_data = {
        "corpus": "Bharatiya Nyaya Sanhita Corpus",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "acts": {
            "BNS": {
                "path": "tree/BNS.json",
                "full_title": "BHARATIYA NYAYA SANHITA, 2023",
                "total_sections": 358,
                "total_pages": 112,
                "summary": trees["BNS"]["summary"]
            },
            "BNSS": {
                "path": "tree/BNSS.json",
                "full_title": "BHARATIYA NAGARIK SURAKSHA SANHITA, 2023",
                "total_sections": 531,
                "total_pages": 279,
                "summary": trees["BNSS"]["summary"]
            },
            "BSA": {
                "path": "tree/BSA.json",
                "full_title": "BHARATIYA SAKSHYA ADHINIYAM, 2023",
                "total_sections": 170,
                "total_pages": 54,
                "summary": trees["BSA"]["summary"]
            }
        }
    }
    if "SOP" in trees:
        index_data["acts"]["SOP"] = {
            "path": "tree/SOP.json",
            "full_title": "Telangana Police Standard Operating Procedures",
            "total_sections": len([c for c in trees["SOP"]["children"] if c["node_type"] != "front_matter"]),
            "total_pages": 238,
            "summary": trees["SOP"]["summary"]
        }
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved index.json to {index_file}")

    # 5. Save fixed regression spot check list
    print("Step 5: Writing spot check registration list...")
    spot_check_file = os.path.join(tree_dir, "spot_check_ids.json")
    spot_check_ids = [
        "BNS_S101",
        "BNS_S63",
        "BNSS_S193",
        "BNS_S356",
        "BSA_S57",
        "BNS_S1",
        "BNS_S2",
        "BNS_S4",
        "BNS_S85",
        "BNS_S143",
        "BNSS_S35",
        "BNSS_S63",
        "BNSS_S173",
        "BNSS_S210",
        "BNSS_S359",
        "BNSS_S531",
        "BSA_S1",
        "BSA_S2",
        "BSA_S24",
        "BSA_S104"
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
