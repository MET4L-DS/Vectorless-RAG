import os
import asyncio
import bm25s
from typing import List, Optional

from .corpus_index import CorpusIndex
from .state import RetrievedNode

class BM25Index:
    def __init__(self):
        self.retriever = None

    def load_or_build(self, corpus_index: CorpusIndex, save_dir: str = "tree/bm25_index"):
        """Loads from disk if exists, otherwise builds from CorpusIndex and saves."""
        if os.path.exists(save_dir):
            try:
                self.retriever = bm25s.BM25.load(save_dir, load_corpus=True)
                print(f"Loaded BM25 index from {save_dir}")
                return
            except Exception as e:
                print(f"Failed to load BM25 index: {e}. Rebuilding...")

        # Build it
        print("Building BM25 index...")
        leaves = corpus_index.get_flat_leaves()
        
        # We index title + summary to keep it clean and focused
        corpus = []
        payloads = []
        
        for leaf in leaves:
            title = leaf.get("title", "")
            summary = leaf.get("summary", "")
            corpus.append(f"{title}\n{summary}")
            
            payloads.append({
                "node_id": leaf["node_id"],
                "act_code": leaf.get("metadata", {}).get("act_code", "")
            })

        # Tokenize and create index
        corpus_tokens = bm25s.tokenize(corpus)
        self.retriever = bm25s.BM25(corpus=payloads)
        self.retriever.index(corpus_tokens)
        
        os.makedirs(save_dir, exist_ok=True)
        self.retriever.save(save_dir, corpus=payloads)
        print(f"Saved BM25 index to {save_dir}")

    async def search(
        self,
        query: str,
        corpus_index: CorpusIndex,
        top_k: int = 20,
        act_filter: Optional[List[str]] = None
    ) -> List[RetrievedNode]:
        if not self.retriever:
            print("Warning: BM25 index not loaded.")
            return []

        # We request more hits if filtering, to ensure we get top_k after filter
        fetch_k = top_k * 3 if act_filter else top_k
        query_tokens = await asyncio.to_thread(bm25s.tokenize, query)
        
        # bm25s returns (results, scores) where results are the payloads we saved
        results, scores = await asyncio.to_thread(self.retriever.retrieve, query_tokens, k=fetch_k)
        
        # bm25s retrieve returns batch-shaped arrays: results[0] and scores[0]
        hits = results[0]
        hit_scores = scores[0]
        
        retrieved_nodes = []
        # Normalization logic: scores can be > 1. Let's find max to normalize
        max_score = hit_scores[0] if len(hit_scores) > 0 and hit_scores[0] > 0 else 1.0

        for idx, payload in enumerate(hits):
            # Check act filter
            if act_filter and payload["act_code"] not in act_filter:
                continue
                
            node_id = payload["node_id"]
            node = corpus_index.get_node(node_id)
            if not node:
                continue
                
            norm_score = float(hit_scores[idx] / max_score)
                
            retrieved_node: RetrievedNode = {
                "node_id": node_id,
                "act_code": payload["act_code"],
                "title": node.get("title", ""),
                "summary": node.get("summary", ""),
                "content": node.get("content", ""),
                "score": norm_score,
                "node_type": node.get("node_type", "section"),
                "page_range": node.get("metadata", {}).get("page_range", []),
                "cross_act_refs": node.get("metadata", {}).get("cross_act_refs", []),
                "internal_refs": node.get("metadata", {}).get("internal_refs", []),
                "retrieval_method": "bm25"
            }
            retrieved_nodes.append(retrieved_node)
            
            if len(retrieved_nodes) >= top_k:
                break
                
        return retrieved_nodes
