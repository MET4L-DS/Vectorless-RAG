from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from src.react_agent.agent import get_agent
from src.api.routes import router as chat_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup AsyncSqliteSaver for the local async FastAPI runtime environment
    async with AsyncSqliteSaver.from_conn_string("local_agent_memory.db") as memory:
        # Compile agent with the persistent async checkpointer
        app.state.agent = get_agent(memory)
        yield

app = FastAPI(
    title="Vectorless-RAG API Backend",
    description="Local FastAPI backend serving the LangGraph ReAct Legal Assistant",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Next.js frontend calls on localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the routes
app.include_router(chat_router, prefix="/api")

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Vectorless-RAG Legal Assistant API is fully operational locally."
    }
