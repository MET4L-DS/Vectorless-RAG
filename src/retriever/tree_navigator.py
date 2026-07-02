import json
import asyncio
from typing import List

from .corpus_index import CorpusIndex
from .state import RetrievedNode
from .client import call_model_with_retry
from .utils import get_token_estimate, truncate_to_token_limit

class TreeNavigator:
    def __init__(self, corpus_index: CorpusIndex):
        self.corpus_index = corpus_index

    async def navigate(
        self,
        query: str,
        act_code: str,
        top_chapters: int = 3,
        top_sections: int = 5
    ) -> List[RetrievedNode]:
        """
        Executes a 2-level tree navigation (Level 0: Chapters, Level 1: Sections) 
        guided by the LLM for a specific statute.
        """
        # Step 1: Chapter selection
        root_summary = self.corpus_index.get_root_summary(act_code)
        root_node_id = self.corpus_index._act_roots.get(act_code)
        
        if not root_node_id:
            return []
            
        chapters = self.corpus_index.get_children(root_node_id)
        if not chapters:
            # Maybe it's flat? Let's check leaves directly
            return []
            
        chapter_ids = await self._select_chapters(query, act_code, root_summary, chapters, top_chapters)
        
        if not chapter_ids:
            return []

        # Step 2: Section selection (done in parallel for selected chapters)
        tasks = []
        for chapter_id in chapter_ids:
            tasks.append(self._select_sections(query, chapter_id, act_code, top_sections))
            
        section_ids_lists = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_section_ids = set()
        for s_list in section_ids_lists:
            if isinstance(s_list, list):
                all_section_ids.update(s_list)
                
        # Step 3: Hydrate retrieved nodes
        retrieved_nodes = []
        for s_id in all_section_ids:
            node = self.corpus_index.get_node(s_id)
            if node:
                retrieved_node: RetrievedNode = {
                    "node_id": s_id,
                    "act_code": act_code,
                    "title": node.get("title", ""),
                    "summary": node.get("summary", ""),
                    "content": node.get("content", ""),
                    "score": 1.0, # Tree navigation implies high confidence
                    "node_type": node.get("node_type", "section"),
                    "page_range": node.get("metadata", {}).get("page_range", []),
                    "cross_act_refs": node.get("metadata", {}).get("cross_act_refs", []),
                    "internal_refs": node.get("metadata", {}).get("internal_refs", []),
                    "retrieval_method": "tree_navigation"
                }
                retrieved_nodes.append(retrieved_node)
                
        return retrieved_nodes

    async def _select_chapters(self, query: str, act_code: str, root_summary: str, chapters: List[dict], k: int) -> List[str]:
        chapter_catalog = []
        for ch in chapters:
            # Chapters might have sub-chapters, we just use their summary
            chapter_catalog.append(f"ID: {ch['node_id']}\nTitle: {ch.get('title', '')}\nSummary: {ch.get('summary', '')}\n---")
            
        catalog_str = "\n".join(chapter_catalog)
        catalog_str = truncate_to_token_limit(catalog_str, max_tokens=15000)
        
        prompt = f"""You are a legal routing expert analyzing the '{act_code}'.
Act Summary:
{root_summary}

User Query: "{query}"

Below are the chapters in this act:
{catalog_str}

Select up to {k} chapter IDs that are most likely to contain the answer to the user's query.
Return your answer AS A JSON ARRAY of strings (the IDs only). For example: ["BNSS_C1", "BNSS_C5"]
Do not return anything other than the JSON array.
"""
        response = await call_model_with_retry(prompt, json_mode=True)
        if response.startswith("```json"): response = response[7:]
        if response.startswith("```"): response = response[3:]
        if response.endswith("```"): response = response[:-3]
        response = response.strip()
        try:
            selected = json.loads(response)
            if isinstance(selected, list):
                mapped_titles = []
                for cid in selected[:k]:
                    node = self.corpus_index.get_node(cid)
                    title = node.get("title", cid) if node else cid
                    mapped_titles.append(f"{cid} ({title})")
                print(f"[Tree Nav] Act {act_code}: Chapter selection LLM selected: {', '.join(mapped_titles)}")
                return selected[:k]
        except json.JSONDecodeError:
            print(f"Failed to decode chapter selection JSON: {response}")
            
        return []
        
    async def _select_sections(self, query: str, chapter_id: str, act_code: str, k: int) -> List[str]:
        chapter = self.corpus_index.get_node(chapter_id)
        if not chapter:
            return []
            
        sections = self.corpus_index.get_children(chapter_id)
        
        # BNSS has Chapter V -> Parts -> Sections. We need to get flat leaves under the chapter.
        # Let's write a small helper to get all leaves under a node
        def get_all_leaves(node_id):
            leaves = []
            children = self.corpus_index.get_children(node_id)
            if not children:
                return [self.corpus_index.get_node(node_id)]
            for child in children:
                leaves.extend(get_all_leaves(child["node_id"]))
            return leaves
            
        all_sections = get_all_leaves(chapter_id)
        
        section_catalog = []
        for sec in all_sections:
            if sec:
                section_catalog.append(f"ID: {sec['node_id']}\nTitle: {sec.get('title', '')}\nSummary: {sec.get('summary', '')}\n---")
                
        catalog_str = "\n".join(section_catalog)
        catalog_str = truncate_to_token_limit(catalog_str, max_tokens=15000)
        
        prompt = f"""You are a legal routing expert.
Chapter Title: {chapter.get('title', '')}
Chapter Summary: {chapter.get('summary', '')}

User Query: "{query}"

Below are the sections in this chapter:
{catalog_str}

Select up to {k} section IDs that are most likely to answer the user's query.
Return your answer AS A JSON ARRAY of strings (the IDs only). For example: ["BNSS_S1", "BNSS_S5"]
Do not return anything other than the JSON array.
"""
        response = await call_model_with_retry(prompt, json_mode=True)
        if response.startswith("```json"): response = response[7:]
        if response.startswith("```"): response = response[3:]
        if response.endswith("```"): response = response[:-3]
        response = response.strip()
        try:
            selected = json.loads(response)
            if isinstance(selected, list):
                mapped_titles = []
                for sid in selected[:k]:
                    node = self.corpus_index.get_node(sid)
                    title = node.get("title", sid) if node else sid
                    mapped_titles.append(f"{sid} ({title})")
                print(f"[Tree Nav] Act {act_code}: Section selection LLM selected: {', '.join(mapped_titles)}")
                return selected[:k]
        except json.JSONDecodeError:
            print(f"Failed to decode section selection JSON: {response}")
            
        return []
