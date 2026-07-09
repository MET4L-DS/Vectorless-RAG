from pydantic import BaseModel, Field
from typing import Literal, List, Optional

class IntentClassification(BaseModel):
    target_corpora: List[Literal["BNS", "BNSS", "BSA", "SOP", "IT", "JJA", "POCSO", "NDPS", "PCA"]] = Field(
        description="List of Indian legal documents containing potential answers (BNS, BNSS, BSA, SOP, IT, JJA, POCSO, NDPS, PCA)"
    )
    reasoning: str = Field(description="Brief reasoning for choosing these target corpora")

class NodeSelection(BaseModel):
    selected_ids: List[str] = Field(
        description="List of selected chapter or section IDs, or empty if none are relevant"
    )

class CacheDecision(BaseModel):
    can_reuse: bool = Field(
        description="Whether the query can be fully and accurately answered using ONLY the already retrieved legal nodes"
    )
    reasoning: str = Field(description="Brief reasoning for the cache decision")

class RewrittenQuery(BaseModel):
    standalone_query: str = Field(
        description="The reformulated standalone search query containing all context, names, and legal terms"
    )

class GroundednessCheck(BaseModel):
    is_grounded: bool = Field(
        description="Whether the claim is fully supported by the legal context without extrapolation"
    )
    reasoning: str = Field(description="Explanation of the grounding decision")

class GeneratedAnswer(BaseModel):
    answer_text: str = Field(
        description="The detailed response. MUST be formatted using Markdown (bullet points, line breaks, bold text) for high readability. Do NOT write a single dense paragraph. Always include inline citations in [Source: ID] format."
    )
    key_provisions: List[str] = Field(
        default_factory=list,
        description="List of key provisions or points. Cite their source in [Source: ID] format."
    )
    citations: List[str] = Field(
        default_factory=list,
        description="List of exact node IDs referenced in the answer (e.g. ['BNS_S64'])"
    )
    is_insufficient_context: bool = Field(
        default=False,
        description="True if the context is insufficient to answer the query"
    )
    chat_title: Optional[str] = Field(
        default=None,
        description="A concise 3-4 word title for this conversation if this is the first turn. Leave null otherwise."
    )
    suggested_follow_up_questions: List[str] = Field(
        default_factory=list,
        description="3-4 relevant, concise questions the user might want to ask next."
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="List of tasks or follow-up actions identified for the user (e.g., 'File an FIR', 'Consult a lawyer'). Leave empty if not applicable or not necessary for the query."
    )
