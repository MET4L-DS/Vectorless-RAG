from fastapi import FastAPI
from pydantic import BaseModel
from src import retriever

app = FastAPI(title="Vectorless-RAG Legal Retrieval API")

class QueryRequest(BaseModel):
    question: str

@app.on_event("startup")
async def startup():
    retriever.load()

@app.post("/query")
async def query(request: QueryRequest):
    result = await retriever.query(request.question)
    return result

@app.get("/health")
async def health():
    return {"status": "ok", "corpora": retriever.list_loaded_acts()}

@app.post("/reload/{act_code}")
async def reload_corpus(act_code: str):
    """Hot-reload a single corpus tree (e.g., after adding new sections)."""
    retriever.reload(act_code)
    return {"reloaded": act_code}
