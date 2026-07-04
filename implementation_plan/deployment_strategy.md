Here is the updated, final deployment blueprint for your `Vectorless-RAG` system using the **Vercel + Supabase Auth + HF Spaces** zero-spend architecture.

### The Updated "Zero-Spend" Portfolio Architecture

**1. The Database & Auth Layer: Supabase**

- **Purpose:** Handles all user authentication via its built-in GoTrue service, issues JWTs natively, and stores LangGraph's long-term conversational memory (`threads` and `checkpoints`) in the Postgres database.
- **Execution:** Create a free Supabase project. You will use the `@supabase/ssr` package in your Next.js frontend to handle login screens and session management. You will point your LangGraph `PostgresSaver` directly to the provided Supabase PostgreSQL connection string.
- **The Catch (The 7-Day Pause):** Supabase pauses free databases after 7 days of inactivity.
- **The Fix:** Set up a free GitHub Action cron job to run a simple `SELECT 1` query against the database every 3 days to keep it permanently awake.

**2. The Frontend Layer: Vercel**

- **Purpose:** Hosts the Next.js UI, manages routing, and securely passes the Supabase JWT to the backend.
- **Execution:** Deploy your Next.js app to Vercel.
- **The Cross-Origin Fix:** When a user asks a question, your Next.js API route will extract the user's Supabase access token (JWT) from the session and pass it in the `Authorization: Bearer <token>` header to your Python backend.

**3. The Edge Protection Layer: Upstash (Redis)**

- **Purpose:** Blocks malicious bots from draining your Gemini API quota and caches deterministic state-machine routing.

- **Execution:** Implement `@upstash/ratelimit` inside Vercel's `middleware.ts`. This blocks spammers at the edge network in single-digit milliseconds before they can ever trigger a billable LLM call.

**4. The AI Backend Layer: Hugging Face Spaces + FastAPI**

- **Purpose:** Hosts the ReAct agent, the JSON hierarchical index, and the BM25 search index.

- **Execution:** Create a Docker Space on Hugging Face. Load your `tree/` directory into memory and connect LangGraph's `PostgresSaver` to your Supabase URL.

- **The JWT Verification Fix:** In FastAPI, you must verify the JWT token without making a slow database lookup to Supabase. You will use the `python-jose` or `pyjwt` library. Supabase exposes a public JSON Web Key Set (JWKS) URL for your project (`https://[project-id].supabase.co/auth/v1/.well-known/jwks.json`). Your FastAPI dependency will use this endpoint to instantly and securely verify the incoming token's signature.
- **The Space Restrictions Fixes:**
- Expose port 7860 in your Dockerfile (`CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]`).
- Route frontend API traffic strictly to the direct iframe URL (`[https://yourname-yourspace.hf.space](https://yourname-yourspace.hf.space)`).
- Map all caches to the temporary disk by adding `ENV HF_HOME=/tmp/huggingface` to your Dockerfile to avoid Permission Denied errors.

This updated architecture completely removes the need for custom `jwks` migrations.
