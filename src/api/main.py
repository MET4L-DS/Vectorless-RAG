import os
import sys
# reload trigger 2
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Psycopg 3 async requires SelectorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src import retriever
from src.react_agent.agent import get_agent
from src.api.routes import router as chat_router

# Load environment variables (such as DATABASE_URL and GOOGLE_API_KEY)
load_dotenv()

async def check_db_connection(conn):
    """Verify that the checked-out connection is active."""
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load retrieval indices and BM25 search structures safely during startup
    retriever.load("tree")
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    # Establish persistent connection pool to Supabase with startup retry
    # This prevents the Space from hard-crashing if Supabase is still waking up
    pool = None
    last_exc = None
    startup_retries = 6
    startup_delay = 10  # seconds between retries (10, 20, 30, 40, 50, 60)

    for attempt in range(1, startup_retries + 1):
        try:
            print(f"[main.py] DB startup attempt {attempt}/{startup_retries}...")
            pool = AsyncConnectionPool(
                conninfo=database_url,
                min_size=0,
                max_size=10,
                max_lifetime=300,
                open=False,  # Don't open connections eagerly
                check=check_db_connection,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": None,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 3
                }
            )
            await pool.open(wait=True, timeout=20)

            # Verify we can actually query the DB
            async with pool.connection(timeout=10) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")

            print(f"[main.py] DB connection established on attempt {attempt}.")
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            print(f"[main.py] DB startup attempt {attempt} failed: {e}")
            if pool:
                try:
                    await pool.close()
                except Exception:
                    pass
                pool = None
            if attempt < startup_retries:
                wait_secs = startup_delay * attempt
                print(f"[main.py] Retrying in {wait_secs}s...")
                await asyncio.sleep(wait_secs)

    if pool is None or last_exc is not None:
        raise RuntimeError(
            f"Failed to connect to Supabase after {startup_retries} attempts. "
            f"Last error: {last_exc}"
        )

    async with pool:
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

@app.get("/health")
async def read_health(request: Request):
    db_status = "ok"
    pool = getattr(request.app.state, "pool", None)
    if pool:
        try:
            async with pool.connection(timeout=3) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
        except Exception as e:
            db_status = f"unreachable: {e}"
    else:
        db_status = "no_pool"

    if db_status != "ok":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "paused_or_unreachable",
                "service": "vectorless-rag",
                "detail": str(db_status)
            }
        )

    return {
        "status": "ok",
        "database": "connected",
        "service": "vectorless-rag"
    }


