import os
import json
from typing import Optional, List, Dict, Any

class CorpusIndex:
    def __init__(self, tree_dir: str = "tree"):
        self.tree_dir = tree_dir
        self._node_map: Dict[str, dict] = {}
        self._children_map: Dict[str, list] = {}
        self._act_roots: Dict[str, str] = {}
        
        # We also want to map child->parent to trace path_to_root easily
        self._parent_map: Dict[str, str] = {}
        
        self._load_all()

    def _load_all(self):
        """Loads all acts referenced in index.json into memory."""
        index_path = os.path.join(self.tree_dir, "index.json")
        if not os.path.exists(index_path):
            print(f"Warning: No index.json found at {index_path}. CorpusIndex is empty.")
            return

        with open(index_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        acts_dict = registry.get("acts", {})
        for act_code in acts_dict.keys():
            self.reload(act_code)

    def reload(self, act_code: str):
        """Loads or reloads a specific JSON tree."""
        file_path = os.path.join(self.tree_dir, f"{act_code}.json")
        if not os.path.exists(file_path):
            print(f"Warning: {file_path} not found.")
            return
            
        with open(file_path, "r", encoding="utf-8") as f:
            root_node = json.load(f)
            
        # First, remove existing nodes for this act to avoid stale data on hot-reload
        if act_code in self._act_roots:
            self._remove_act_nodes(act_code)
            
        self._act_roots[act_code] = root_node["node_id"]
        self._register_node(root_node, parent_id=None, act_code=act_code)
        
    def _remove_act_nodes(self, act_code: str):
        """Removes all nodes belonging to a given act_code from the indices."""
        nodes_to_remove = []
        for node_id, node in self._node_map.items():
            if node.get("metadata", {}).get("act_code") == act_code or node.get("node_id", "").startswith(act_code):
                nodes_to_remove.append(node_id)
                
        for node_id in nodes_to_remove:
            self._node_map.pop(node_id, None)
            self._children_map.pop(node_id, None)
            self._parent_map.pop(node_id, None)

    def _register_node(self, node: dict, parent_id: Optional[str], act_code: str):
        """Recursively registers a node and its children into the flat lookup maps."""
        node_id = node["node_id"]
        
        # Ensure act_code is in metadata for fast filtering later
        if "metadata" not in node:
            node["metadata"] = {}
        if "act_code" not in node["metadata"]:
            node["metadata"]["act_code"] = act_code
            
        self._node_map[node_id] = node
        
        if parent_id:
            self._parent_map[node_id] = parent_id
            
        children = node.get("children", [])
        self._children_map[node_id] = [child["node_id"] for child in children]
        
        for child in children:
            self._register_node(child, parent_id=node_id, act_code=act_code)

    def get_node(self, node_id: str) -> Optional[dict]:
        """Returns the node dictionary for a given node_id, without its children array to save memory/output."""
        node = self._node_map.get(node_id)
        if not node:
            return None
        # Return a shallow copy excluding children to keep context tight
        return {k: v for k, v in node.items() if k != "children"}

    def get_children(self, node_id: str) -> List[dict]:
        """Returns the lightweight dictionaries of all immediate children."""
        child_ids = self._children_map.get(node_id, [])
        return [self.get_node(cid) for cid in child_ids if self.get_node(cid) is not None]

    def get_path_to_root(self, node_id: str) -> List[dict]:
        """Returns the hierarchy path from the root down to (and including) this node."""
        path = []
        current = node_id
        while current:
            node = self.get_node(current)
            if node:
                path.insert(0, node)
            current = self._parent_map.get(current)
        return path

    def list_acts(self) -> List[str]:
        """Returns a list of all loaded act codes."""
        return list(self._act_roots.keys())

    def get_root_summary(self, act_code: str) -> str:
        """Returns the summary of the root node of an act."""
        root_id = self._act_roots.get(act_code)
        if not root_id:
            return ""
        node = self.get_node(root_id)
        return node.get("summary", "") if node else ""

    def get_flat_leaves(self, act_code: Optional[str] = None) -> List[dict]:
        """Returns all leaf nodes (nodes without children). Used for BM25 indexing."""
        leaves = []
        for node_id, child_ids in self._children_map.items():
            if len(child_ids) == 0:
                node = self.get_node(node_id)
                if node:
                    if act_code is None or node.get("metadata", {}).get("act_code") == act_code:
                        leaves.append(node)
        return leaves
