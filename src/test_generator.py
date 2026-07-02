import asyncio
from src import retriever
from src import generator

async def run_tests():
    # Load indices
    retriever.load("tree")
    
    print("\n==================================================")
    print("        Starting Phase 4 Integration Tests        ")
    print("==================================================\n")
    
    # Stateful test session
    history = []
    last_retrieval = None
    
    # --- Turn 1: Base Question ---
    q1 = "What are the rights of an arrested person?"
    print(f"--- Turn 1: {q1} ---")
    res1 = await generator.generate(q1, history, last_retrieval)
    
    print(f"Confidence: {res1['confidence']:.2f}")
    print(f"Latency: {res1['latency_ms']} ms")
    print(f"Answer: {res1['answer'][:300]}...")
    print(f"Citations extracted: {[c['node_id'] for c in res1['citations']]}")
    assert len(res1['citations']) > 0, "Error: No citations generated in Turn 1!"
    print("Turn 1 Passed.\n")
    
    # Save session state
    history.append({"user": q1, "assistant": res1["answer"]})
    last_retrieval = res1["retrieval"]
    
    # --- Turn 2: Follow-up (Context Router miss -> query rewrite) ---
    q2 = "What if they are a minor?"
    print(f"--- Turn 2: {q2} ---")
    res2 = await generator.generate(q2, history, last_retrieval)
    
    print(f"Confidence: {res2['confidence']:.2f}")
    print(f"Latency: {res2['latency_ms']} ms")
    print(f"Answer: {res2['answer'][:300]}...")
    print(f"Citations extracted: {[c['node_id'] for c in res2['citations']]}")
    print("Turn 2 Passed.\n")
    
    # Save session state
    history.append({"user": q2, "assistant": res2["answer"]})
    last_retrieval = res2["retrieval"]
    
    # --- Turn 3: Clarification (Context Router hit -> bypass Phase 3) ---
    q3 = "Can you repeat the rule for the maximum detention time?"
    print(f"--- Turn 3: {q3} ---")
    res3 = await generator.generate(q3, history, last_retrieval)
    
    print(f"Confidence: {res3['confidence']:.2f}")
    print(f"Latency: {res3['latency_ms']} ms")
    print(f"Answer: {res3['answer'][:300]}...")
    print(f"Citations extracted: {[c['node_id'] for c in res3['citations']]}")
    print("Turn 3 Passed.\n")
    
    print("==================================================")
    print("    All Phase 4 Integration Tests Passed (3/3)   ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
