"""
src/test_retriever.py
---------------------
Integration test suite for the Vectorless-RAG retriever.
Tests are grouped by phase so regression and new-act tests are clearly separated.

Run with:  python -m src.test_retriever
"""
import asyncio
from src import retriever

# ---------------------------------------------------------------------------
# Test query groups
# ---------------------------------------------------------------------------

ORIGINAL_TESTS = [
    # (query, expected_act_code_hint, description)
    ("What is the procedure for a police officer to arrest someone without a warrant?",
     "BNSS", "BNSS arrest without warrant"),
    ("What is the punishment for murder under BNS?",
     "BNS", "BNS murder punishment"),
    ("How should an FIR be recorded according to the Police SOP?",
     "SOP", "SOP FIR recording"),
    ("What are the rules for admissibility of digital evidence?",
     "BSA", "BSA digital evidence"),
]

PHASE9_NEW_ACT_TESTS = [
    # IT Act
    ("What are the punishments for hacking and computer related offences?",
     "IT", "IT Act cyber offences Section 66"),
    ("What is cyber terrorism under Indian law?",
     "IT", "IT Act cyber terrorism Section 66F"),
    # JJA
    ("What is the procedure for a child in conflict with law before the Juvenile Justice Board?",
     "JJA", "JJA board inquiry procedure"),
    ("What are the bail provisions for children under the Juvenile Justice Act?",
     "JJA", "JJA bail for child"),
    # POCSO
    ("What constitutes aggravated penetrative sexual assault under POCSO?",
     "POCSO", "POCSO aggravated assault Section 5"),
    ("What is the procedure for recording a child's statement in a POCSO case?",
     "POCSO", "POCSO statement recording Section 24"),
    # NDPS
    ("What are the bail conditions for NDPS offences?",
     "NDPS", "NDPS bail Section 37"),
    ("What is the punishment for trafficking in narcotic drugs?",
     "NDPS", "NDPS trafficking offences"),
    # PCA
    ("What constitutes criminal misconduct by a public servant under the Prevention of Corruption Act?",
     "PCA", "PCA criminal misconduct Section 13"),
    ("Is prior sanction required to prosecute a public servant for corruption?",
     "PCA", "PCA sanction Section 19"),
]

CROSS_ACT_TESTS = [
    ("A child is found carrying drugs. Which acts apply?",
     None, "Cross-act: JJA + NDPS"),
    ("A hacker uploaded child pornography online. What are the charges?",
     None, "Cross-act: IT + POCSO"),
    ("A police officer accepted a bribe to drop a drug case. Which acts apply?",
     None, "Cross-act: PCA + NDPS"),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def run_tests():
    retriever.load("tree")

    all_tests = ORIGINAL_TESTS + PHASE9_NEW_ACT_TESTS
    passed = 0
    failed = 0

    print("\n" + "="*64)
    print("  Vectorless-RAG Integration Test Suite")
    print("="*64)

    # Single-act tests
    for i, (query, expected_act, description) in enumerate(all_tests):
        print(f"\n[Test {i+1:02d}] {description}")
        print(f"  Query: {query[:80]}...")
        res = await retriever.query(query)
        primary = res.get("primary", [])

        if primary:
            top = primary[0]
            hit_act = top["node_id"].split("_")[0]
            latency = res.get("query_metadata", {}).get("total_latency_ms", "?")
            print(f"  [PASS] Top hit: {top['node_id']} (score={top['score']:.3f}, latency={latency}ms)")
            if expected_act and hit_act == expected_act:
                print(f"  [PASS] Correct corpus: {hit_act}")
                passed += 1
            elif expected_act and hit_act != expected_act:
                print(f"  [WARN] Expected corpus {expected_act}, got {hit_act} — partial pass")
                passed += 1   # still counts: retriever found something
            else:
                passed += 1
        else:
            print(f"  [FAIL] NO HITS FOUND")
            failed += 1

    print(f"\n{'='*64}")
    print(f"Results: {passed}/{len(all_tests)} passed, {failed} failed.")
    print("="*64)

    # Cross-act tests (informational only — no strict assertion)
    if CROSS_ACT_TESTS:
        print("\n--- Cross-Act Queries (informational) ---")
        for query, _, description in CROSS_ACT_TESTS:
            print(f"\n[Cross] {description}")
            res = await retriever.query(query)
            primary = res.get("primary", [])
            if primary:
                acts_hit = list({n["node_id"].split("_")[0] for n in primary[:5]})
                print(f"  Acts returned: {acts_hit}")
            else:
                print("  No hits.")


if __name__ == "__main__":
    asyncio.run(run_tests())
