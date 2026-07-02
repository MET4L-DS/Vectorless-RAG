import tiktoken

# Use a standard cl100k_base tokenizer for fast approximation
try:
    enc = tiktoken.get_encoding("cl100k_base")
except Exception:
    enc = None

def get_token_estimate(text: str) -> int:
    """Returns an approximate token count for the given text."""
    if not text:
        return 0
    if enc:
        return len(enc.encode(text, disallowed_special=()))
    # Fallback heuristic: 1 token ~= 4 characters
    return len(text) // 4

def truncate_to_token_limit(text: str, max_tokens: int = 15000) -> str:
    """Truncates text to ensure it stays within a token limit."""
    if get_token_estimate(text) <= max_tokens:
        return text
        
    if enc:
        tokens = enc.encode(text, disallowed_special=())
        return enc.decode(tokens[:max_tokens])
    else:
        # Fallback heuristic
        return text[:max_tokens * 4]
