from contextlib import asynccontextmanager
from typing import List, Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel
from src import retriever
from src import generator

@asynccontextmanager
async def lifespan(app: FastAPI):
    retriever.load()
    yield

app = FastAPI(title="Vectorless-RAG Legal Retrieval & Generative API", lifespan=lifespan)

class QueryRequest(BaseModel):
    question: str

class ChatRequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []
    last_retrieval: Dict[str, Any] | None = None

@app.post("/query")
async def query(request: QueryRequest):
    """Raw retrieval endpoint (Phase 3)."""
    result = await retriever.query(request.question)
    return result

@app.post("/chat")
async def chat(request: ChatRequest):
    """Stateful generative & verified chat endpoint (Phase 4)."""
    result = await generator.generate(
        query=request.question,
        history=request.history,
        last_retrieval=request.last_retrieval
    )
    return result

@app.get("/health")
async def health():
    return {"status": "ok", "corpora": retriever.list_loaded_acts()}

@app.post("/reload/{act_code}")
async def reload_corpus(act_code: str):
    """Hot-reload a single corpus tree."""
    retriever.reload(act_code)
    return {"reloaded": act_code}
