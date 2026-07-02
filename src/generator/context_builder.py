from src.retriever.state import RetrievalResult, RetrievedNode
from src.retriever.utils import get_token_estimate

def build_context(retrieval_result: RetrievalResult, max_tokens: int = 20000) -> str:
    """
    Formates primary and supporting nodes into a unified context string.
    Ensures the total size does not exceed max_tokens.
    """
    formatted_nodes = []
    current_tokens = 0
    
    # 1. Primary nodes first (Full Content)
    for node in retrieval_result.get("primary", []):
        text_body = node.get("content") or node.get("summary") or ""
        formatted_node = f"[Source {node['node_id']}: {node['title']}]\n{text_body}\n"
        node_tokens = get_token_estimate(formatted_node)
        
        if current_tokens + node_tokens <= max_tokens:
            formatted_nodes.append(formatted_node)
            current_tokens += node_tokens
        else:
            # We hit the cap. Don't add more nodes.
            break
            
    # 2. Supporting nodes second (Summary only)
    for node in retrieval_result.get("supporting", []):
        text_body = node.get("summary") or ""
        formatted_node = f"[Source {node['node_id']} (Supporting): {node['title']}]\n{text_body}\n"
        node_tokens = get_token_estimate(formatted_node)
        
        if current_tokens + node_tokens <= max_tokens:
            formatted_nodes.append(formatted_node)
            current_tokens += node_tokens
        else:
            # Hit the cap.
            break
            
    return "\n".join(formatted_nodes)
