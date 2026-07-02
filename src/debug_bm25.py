import bm25s
from src import retriever

retriever.load("tree")

print(f"Total leaves: {len(retriever._corpus_index.get_flat_leaves())}")

query_str = "What is the procedure for a police officer to arrest someone without a warrant?"
query_tokens = bm25s.tokenize(query_str)
results, scores = retriever._bm25_index.retriever.retrieve(query_tokens, k=5)

print(f"Results: {results}")
print(f"Scores: {scores}")

# Also test the main query function
import asyncio
res = asyncio.run(retriever.query(query_str))
print(f"Primary hits: {len(res['primary'])}")
