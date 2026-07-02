import re
from typing import List, Dict, Tuple, Any
from src.retriever.client import call_model_with_retry
from src.retriever.state import RetrievalResult, RetrievedNode
from src.generator.state import Citation, VerificationReport

def split_sentences(text: str) -> List[str]:
    """Splits text into sentences, avoiding abbreviations like Sec., §, etc."""
    # Simple regex splitting on punctuation followed by space
    # Handles abbreviations by looking at typical boundaries
    sentence_end = re.compile(r'(?<!\bSec)(?<!\bSOP)(?<!\bAct)(?<!\bVol)(?<!\bpp)(?<!\bRef)\.\s+(?=[A-Z0-9])')
    # Clean answer segment (strip sections like [References])
    cleaned_text = text.split("[References]")[0]
    cleaned_text = cleaned_text.replace("[Answer]", "").replace("[Key Provisions]", "")
    
    raw_sentences = sentence_end.split(cleaned_text)
    sentences = []
    for s in raw_sentences:
        s_clean = s.strip()
        if len(s_clean) > 8: # Filter out short layout fragments
            sentences.append(s_clean)
    return sentences

def extract_brackets(text: str) -> List[str]:
    """Finds all bracketed content [...] in the string."""
    return re.findall(r'\[(.*?)\]', text)

def match_citation_to_node(bracket_text: str, retrieved_nodes: List[RetrievedNode]) -> RetrievedNode | None:
    """
    Attempts to match bracketed text (e.g. 'Source: BNSS_S35' or 'BNSS §35')
    to one of the retrieved nodes.
    """
    bracket_clean = bracket_text.lower().replace("source:", "").strip()
    
    # Try exact node_id match
    for node in retrieved_nodes:
        n_id = node["node_id"].lower()
        if n_id in bracket_clean:
            return node
            
    # Try mapping abbreviation + number (e.g., 'bnss 35' or 'bnss §35' to BNSS_S35)
    # Extract alpha and digit blocks
    alpha_part = "".join(re.findall(r'[a-zA-Z]+', bracket_clean))
    digit_part = "".join(re.findall(r'\d+', bracket_clean))
    
    if alpha_part and digit_part:
        for node in retrieved_nodes:
            n_id = node["node_id"].lower()
            if alpha_part in n_id and digit_part in n_id:
                return node
                
    return None

async def verify_answer(
    raw_answer: str,
    retrieval_result: RetrievalResult,
    context_str: str
) -> Tuple[VerificationReport, List[Citation]]:
    """
    Performs a 2-stage grounding verification check on the generated answer.
    """
    retrieved_nodes = retrieval_result.get("primary", []) + retrieval_result.get("supporting", [])
    sentences = split_sentences(raw_answer)
    
    grounded_claims = 0
    ungrounded_claims = 0
    issues = []
    citations_found: Dict[str, Citation] = {}
    
    for sentence in sentences:
        # Check if sentence has brackets containing a valid citation
        brackets = extract_brackets(sentence)
        citation_node = None
        for b in brackets:
            matched = match_citation_to_node(b, retrieved_nodes)
            if matched:
                citation_node = matched
                break
                
        if citation_node:
            grounded_claims += 1
            # Add to structured citation list
            node_id = citation_node["node_id"]
            if node_id not in citations_found:
                citations_found[node_id] = {
                    "node_id": node_id,
                    "act_code": citation_node.get("act_code", ""),
                    "title": citation_node.get("title", ""),
                    "quoted_text": sentence,
                    "page_range": citation_node.get("page_range", [])
                }
        else:
            # Stage 2: Ask LLM if this uncited claim is supported by context
            is_grounded = await check_groundedness_via_llm(sentence, context_str)
            if is_grounded:
                grounded_claims += 1
            else:
                ungrounded_claims += 1
                issues.append(f"Ungrounded Claim: '{sentence}'")
                
    total_claims = grounded_claims + ungrounded_claims
    score = (grounded_claims / total_claims) if total_claims > 0 else 1.0
    
    passed = score >= 0.90
    
    report: VerificationReport = {
        "passed": passed,
        "score": round(score, 3),
        "grounded_claims": grounded_claims,
        "ungrounded_claims": ungrounded_claims,
        "issues": issues
    }
    
    return report, list(citations_found.values())

async def check_groundedness_via_llm(sentence: str, context_str: str) -> bool:
    """
    Calls Gemini Flash-Lite to verify if a single claim is grounded in the context.
    """
    # Keep prompt minimal to reduce latency
    prompt = f"""You are a strict legal editor.
Review if the claim is fully supported by the legal context. Do not allow any extrapolation.

LEGAL CONTEXT:
{context_str}

CLAIM:
"{sentence}"

Is this claim fully supported by the context? Answer ONLY with YES or NO.
"""
    try:
        response = await call_model_with_retry(prompt, model_name="models/gemini-3.1-flash-lite")
        cleaned = response.strip().upper()
        if "YES" in cleaned:
            return True
    except Exception as e:
        print(f"[Verifier] Error in LLM grounding check: {e}")
        
    return False
