import os
import sys
# reload trigger 2
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Psycopg 3 async requires SelectorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.react_agent.agent import get_agent
from src.api.routes import router as chat_router

# Load environment variables (such as DATABASE_URL and GOOGLE_API_KEY)
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    # Establish persistent connection pool to Supabase
    async with AsyncConnectionPool(
        conninfo=database_url,
        max_size=10,
        max_lifetime=300,  # 5 minutes connection lifetime to refresh before idle timeouts
        kwargs={
            "autocommit": True,
            "prepare_threshold": None,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3
        }
    ) as pool:
        app.state.pool = pool
        checkpointer = AsyncPostgresSaver(pool)
        # Create checkpoint tables if they don't exist (migrations)
        await checkpointer.setup()
        
        # Create custom chat_sessions table for thread names
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        thread_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id_updated_at 
                    ON chat_sessions (user_id, updated_at DESC)
                """)
        
        # Compile agent with the persistent Postgres checkpointer
        app.state.agent = get_agent(checkpointer)
        yield

app = FastAPI(
    title="Vectorless-RAG API Backend",
    description="Local FastAPI backend serving the LangGraph ReAct Legal Assistant",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Next.js frontend calls
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if allowed_origins_env.strip() == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [
        o.strip() for o in allowed_origins_env.split(",") if o.strip()
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
