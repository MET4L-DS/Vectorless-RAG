from typing import List, Dict
from src.retriever.client import call_model_structured
from src.retriever.schemas import GeneratedAnswer
from src.generator.context_router import format_history

async def generate_answer(
    query: str, 
    history: List[Dict[str, str]], 
    context_str: str, 
    retry_feedback: str | None = None
) -> GeneratedAnswer:
    """
    Synthesizes a response using gemini-3.1-flash-lite.
    Enforces strict grounding and formatting via GeneratedAnswer schema.
    """
    history_str = format_history(history)
    
    prompt = f"""You are an expert legal assistant specializing in Indian Criminal Law (BNS, BNSS, BSA, and Police SOP).
Your task is to answer the user query based ONLY on the legal sources provided below.
DO NOT use any external knowledge.

If the provided legal context does not contain enough information to answer the query, set is_insufficient_context to True.
Otherwise, answer the query comprehensively and include detailed inline citations for every factual claim.

CONSTRAINTS:
- Use inline citations in the narrative and key provisions like [Source: node_id] (e.g. [Source: BNSS_S35]).
- Do not cite documents that are not in the context.
- Populate the citations field with the exact list of node IDs referenced (e.g., ["BNSS_S35", "SOP_S13"]).

CONVERSATION HISTORY:
{history_str}

LEGAL CONTEXT:
{context_str}

USER QUERY:
{query}
"""
    
    if retry_feedback:
        prompt += f"""
WARNING: Your previous answer was flagged by the verifier for containing unsupported claims:
{retry_feedback}
Please rewrite the answer, ensuring that every claim is strictly grounded in the context. If you cannot support a claim, remove it completely from your answer!
"""

    # We enforce models/gemini-3.1-flash-lite as the default generator
    response: GeneratedAnswer = await call_model_structured(
        prompt, 
        GeneratedAnswer, 
        model_name="models/gemini-3.1-flash-lite"
    )
    return response

