from typing import List, Dict
from src.retriever.client import call_model_with_retry
from src.generator.context_router import format_history

async def generate_answer(
    query: str, 
    history: List[Dict[str, str]], 
    context_str: str, 
    retry_feedback: str | None = None
) -> str:
    """
    Synthesizes a response using gemini-3.1-flash-lite.
    Enforces strict grounding and formatting.
    """
    history_str = format_history(history)
    
    prompt = f"""You are an expert legal assistant specializing in Indian Criminal Law (BNS, BNSS, BSA, and Police SOP).
Your task is to answer the user query based ONLY on the legal sources provided below.
DO NOT use any external knowledge.

If the provided legal context does not contain enough information to answer the query, you must start your response with the word: INSUFFICIENT_CONTEXT
Otherwise, answer the query comprehensively and include detailed inline citations for every factual claim.

CONSTRAINTS:
- Use inline citations like [Source: node_id] (e.g. [Source: BNSS_S35]).
- Provide both inline citations and a footnote-style "References" section at the end mapping each citation to its descriptive title.
- Do not cite documents that are not in the context.

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

    prompt += """
Format your output EXACTLY as:
[Answer]
(Your natural language response with inline citations, e.g. [Source: BNSS_S35].)

[Key Provisions]
- Bullet point 1 [Source: BNSS_S35]
- Bullet point 2 [Source: SOP_S13]

[References]
[1] BNSS_S35: 35. When police may arrest without warrant
[2] SOP_S13: SOP on Arrest
"""

    # We enforce models/gemini-3.1-flash-lite as the default generator
    response = await call_model_with_retry(prompt, model_name="models/gemini-3.1-flash-lite")
    return response.strip()
