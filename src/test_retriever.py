import asyncio
from src import retriever

async def run_tests():
    retriever.load("tree")
    
    test_queries = [
        "What is the procedure for a police officer to arrest someone without a warrant?",
        "What is the punishment for murder under BNS?",
        "How should an FIR be recorded according to the Police SOP?"
    ]
    
    success = 0
    for i, q in enumerate(test_queries):
        print(f"\n--- Test {i+1} ---")
        print(f"Query: {q}")
        res = await retriever.query(q)
        print(f"Target Corpora: {res['query_metadata']['target_corpora']}")
        
        if len(res['primary']) > 0:
            print(f"Top Hit: {res['primary'][0]['node_id']} (Score: {res['primary'][0]['score']})")
            print(f"Latency: {res['query_metadata']['total_latency_ms']}ms")
            success += 1
        else:
            print(f"NO HITS FOUND! Result dict: {res}")
            
    print(f"\nIntegration Tests: {success}/{len(test_queries)} Passed.")

if __name__ == "__main__":
    asyncio.run(run_tests())
