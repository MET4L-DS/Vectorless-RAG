import json
from typing import List

from .corpus_index import CorpusIndex
from .state import RetrievedNode
from .client import call_model_with_retry
from .utils import truncate_to_token_limit

class SOPRetriever:
    def __init__(self, corpus_index: CorpusIndex):
        self.corpus_index = corpus_index

    async def retrieve(
        self,
        query: str,
        top_k: int = 5
    ) -> List[RetrievedNode]:
        """
        Executes a 1-level flat scan over all SOP procedures.
        """
        act_code = "SOP"
        root_summary = self.corpus_index.get_root_summary(act_code)
        
        # SOP procedures are leaves
        procedures = self.corpus_index.get_flat_leaves(act_code)
        if not procedures:
            return []
            
        procedure_catalog = []
        for p in procedures:
            procedure_catalog.append(f"ID: {p['node_id']}\nTitle: {p.get('title', '')}\nSummary: {p.get('summary', '')}\n---")
            
        catalog_str = "\n".join(procedure_catalog)
        catalog_str = truncate_to_token_limit(catalog_str, max_tokens=20000)
        
        prompt = f"""You are a legal routing expert analyzing the Police Standard Operating Procedures (SOP).
SOP Overview:
{root_summary}

User Query: "{query}"

Below are the procedures available in the SOP:
{catalog_str}

Select up to {top_k} procedure IDs that are most likely to provide the operational steps to answer the user's query.
Return your answer AS A JSON ARRAY of strings (the IDs only). For example: ["SOP_Procedure_12", "SOP_Procedure_15"]
Do not return anything other than the JSON array.
"""
        response = await call_model_with_retry(prompt, json_mode=True)
        if response.startswith("```json"): response = response[7:]
        if response.startswith("```"): response = response[3:]
        if response.endswith("```"): response = response[:-3]
        response = response.strip()
        selected_ids = []
        try:
            selected = json.loads(response)
            if isinstance(selected, list):
                selected_ids = selected[:top_k]
                mapped_titles = []
                for sid in selected_ids:
                    node = self.corpus_index.get_node(sid)
                    title = node.get("title", sid) if node else sid
                    mapped_titles.append(f"{sid} ({title})")
                print(f"[Tree Nav] SOP: Procedure selection LLM selected: {', '.join(mapped_titles)}")
        except json.JSONDecodeError:
            print(f"Failed to decode SOP selection JSON: {response}")
            
        retrieved_nodes = []
        for s_id in selected_ids:
            node = self.corpus_index.get_node(s_id)
            if node:
                retrieved_node: RetrievedNode = {
                    "node_id": s_id,
                    "act_code": act_code,
                    "title": node.get("title", ""),
                    "summary": node.get("summary", ""),
                    "content": node.get("content", ""),
                    "score": 1.0, 
                    "node_type": node.get("node_type", "procedure"),
                    "page_range": node.get("metadata", {}).get("page_range", []),
                    "cross_act_refs": node.get("metadata", {}).get("cross_act_refs", []),
                    "internal_refs": node.get("metadata", {}).get("internal_refs", []),
                    "retrieval_method": "tree_navigation"
                }
                retrieved_nodes.append(retrieved_node)
                
        return retrieved_nodes
