from typing import List
from .corpus_index import CorpusIndex
from .state import RetrievedNode

class CrossRefLinker:
    def __init__(self, corpus_index: CorpusIndex):
        self.corpus_index = corpus_index

    def enrich(
        self,
        primary_nodes: List[RetrievedNode],
        max_links_per_node: int = 3
    ) -> List[RetrievedNode]:
        """
        Scans primary nodes for cross_act_refs and internal_refs.
        Resolves those nodes and adds them to a new list.
        Returns only the newly discovered cross-ref nodes.
        """
        # Keep track of what we already have to avoid duplicates
        existing_ids = {node["node_id"] for node in primary_nodes}
        cross_ref_hits = []
        
        for p_node in primary_nodes:
            added_for_this_node = 0
            
            # Cross Act Refs (e.g. from SOP to BNSS)
            cross_refs = p_node.get("cross_act_refs", [])
            for ref in cross_refs:
                if added_for_this_node >= max_links_per_node:
                    break
                    
                target_act = ref.get("act")
                target_section = ref.get("section")
                
                if target_act and target_section:
                    # Construct probable node_id
                    target_id = f"{target_act}_S{target_section}"
                    if target_id not in existing_ids:
                        target_node = self.corpus_index.get_node(target_id)
                        if target_node:
                            enriched_node = self._build_enriched_node(target_node, target_id, target_act, p_node["node_id"])
                            cross_ref_hits.append(enriched_node)
                            existing_ids.add(target_id)
                            added_for_this_node += 1
                            
            # We can also do internal refs if desired, e.g. "Section 45" inside BNSS
            internal_refs = p_node.get("internal_refs", [])
            for ref in internal_refs:
                if added_for_this_node >= max_links_per_node:
                    break
                target_id = f"{p_node['act_code']}_S{ref}"
                if target_id not in existing_ids:
                    target_node = self.corpus_index.get_node(target_id)
                    if target_node:
                        enriched_node = self._build_enriched_node(target_node, target_id, p_node["act_code"], p_node["node_id"])
                        cross_ref_hits.append(enriched_node)
                        existing_ids.add(target_id)
                        added_for_this_node += 1
                        
        return cross_ref_hits
        
    def _build_enriched_node(self, node: dict, target_id: str, act_code: str, source_node_id: str) -> RetrievedNode:
        return {
            "node_id": target_id,
            "act_code": act_code,
            "title": node.get("title", ""),
            "summary": node.get("summary", ""),
            "content": node.get("content", ""),
            "score": 0.8, # Good confidence for explicit citations
            "node_type": node.get("node_type", "section"),
            "page_range": node.get("metadata", {}).get("page_range", []),
            "cross_act_refs": node.get("metadata", {}).get("cross_act_refs", []),
            "internal_refs": node.get("metadata", {}).get("internal_refs", []),
            "retrieval_method": f"cross_ref_from_{source_node_id}"
        }
