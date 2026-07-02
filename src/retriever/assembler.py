from typing import List, Dict, Any
from .state import RetrievedNode, RetrievalResult

class Assembler:
    def __init__(self):
        pass

    def assemble(
        self,
        bm25_hits: List[RetrievedNode],
        tree_hits: List[RetrievedNode],
        cross_ref_hits: List[RetrievedNode]
    ) -> RetrievalResult:
        
        merged_nodes: Dict[str, RetrievedNode] = {}
        
        # Helper to merge nodes and compute composite scores
        def add_node(node: RetrievedNode, source_score: float, is_tree: bool = False, is_cross_ref: bool = False):
            n_id = node["node_id"]
            if n_id not in merged_nodes:
                # Make a copy so we don't mutate state history
                merged_nodes[n_id] = node.copy()
                merged_nodes[n_id]["score"] = 0.0 # reset for composite calculation
                merged_nodes[n_id]["_bm25_score"] = 0.0
                merged_nodes[n_id]["_is_tree"] = False
                merged_nodes[n_id]["_is_cross_ref"] = False
                
            if is_tree:
                merged_nodes[n_id]["_is_tree"] = True
            elif is_cross_ref:
                merged_nodes[n_id]["_is_cross_ref"] = True
            else:
                # BM25
                merged_nodes[n_id]["_bm25_score"] = max(merged_nodes[n_id].get("_bm25_score", 0.0), source_score)

        # Merge them all
        for hit in bm25_hits:
            add_node(hit, hit["score"])
            
        for hit in tree_hits:
            add_node(hit, 1.0, is_tree=True)
            
        for hit in cross_ref_hits:
            add_node(hit, 0.8, is_cross_ref=True)
            
        # Compute final scores
        # final_score = (0.5 × bm25_score) + (0.4 × tree_nav_score) + (0.1 × cross_ref_bonus)
        for n_id, node in merged_nodes.items():
            bm25 = node.get("_bm25_score", 0.0)
            tree = 1.0 if node.get("_is_tree") else 0.0
            cross = 1.0 if node.get("_is_cross_ref") else 0.0
            
            final_score = (0.5 * bm25) + (0.4 * tree) + (0.1 * cross)
            node["score"] = round(final_score, 3)
            
            # Clean up temporary fields
            node.pop("_bm25_score", None)
            node.pop("_is_tree", None)
            node.pop("_is_cross_ref", None)
            
        # Sort by final score
        sorted_nodes = sorted(merged_nodes.values(), key=lambda x: x["score"], reverse=True)
        
        primary = sorted_nodes[:5]
        supporting = sorted_nodes[5:15]
        
        citations = []
        sources = []
        for n in primary + supporting:
            act = n.get("act_code", "")
            if n["node_type"] == "section":
                title_clean = n["title"].split(".")[0] if "." in n["title"] else n["title"]
                c_str = f"{act} {title_clean}"
                s_str = f"{act} {n['title']}"
            else:
                c_str = f"{act} {n['node_type']} (ID: {n['node_id']})"
                s_str = f"{act} {n.get('title', n['node_id'])}"
                
            if c_str not in citations:
                citations.append(c_str)
            if s_str not in sources:
                sources.append(s_str)
                
        return {
            "primary": primary,
            "supporting": supporting,
            "citations": citations[:10],
            "sources": sources,
            "query_metadata": {
                "total_unique_hits": len(sorted_nodes),
                "bm25_hits": len(bm25_hits),
                "tree_hits": len(tree_hits),
                "cross_ref_hits": len(cross_ref_hits)
            }
        }
