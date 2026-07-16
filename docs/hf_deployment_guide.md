# Hugging Face Space Deployment Guide

When your project contains large binary files (like `.parquet`, `.npy`, `.db`), pushing to a Hugging Face Space via standard Git can result in rejections because Git pushes your entire history, including commits where those binaries were added before being ignored.

To permanently avoid Git history rejections and deploy effortlessly, use the **Hugging Face CLI** instead of `git push`.

## 1. Authentication (First Time Only)

Make sure you are authenticated with your Hugging Face account:

```bash
huggingface-cli login
```
*(You will need to provide your Hugging Face Access Token)*

## 2. Deploying to the Space

Instead of committing and running `git push hf main`, simply use the `upload` command from your project root:

```bash
huggingface-cli upload Ayanshu/Legal-Vectorless-RAG-HF . --repo-type space
```

### Why this is the best approach:
1. **Ignores Git History:** The CLI acts like an FTP client. It looks at your current files and syncs them directly to the space, bypassing your local Git commits entirely.
2. **Respects `.gitignore`:** It automatically ignores files specified in your `.gitignore`, ensuring your local vector index or SQLite databases don't get uploaded.
3. **Resumable & Fast:** It handles large uploads efficiently without the overhead of Git delta compressions.

You can continue using `git` normally for your own local version control or pushing to GitHub!

---

## 3. Handling Container Sleep & Stale Database Connections

Since free-tier Hugging Face Spaces sleep after 48 hours of inactivity, you should plan for cold starts:

1. **Uptime Warm Pings (Recommended)**: Set up a free service like [UptimeRobot](https://uptimerobot.com/) or [Better Stack Uptime](https://betterstack.com/) to ping the root `/` or `/api/health` endpoint of your Space every 30 minutes. This prevents the Space container from going to sleep.
2. **Database Connection checkout check**: The backend pool is configured with `check=check_db_connection` in `AsyncConnectionPool` inside `main.py`. This runs a lightweight `SELECT 1` ping query whenever a connection is checked out. If the Space was sleeping and the connection socket died on the Supabase/database side, psycopg will transparently discard the stale connection and open a new one rather than raising a 500 error.
3. **Frontend Retries**: The Next.js frontend employs retry logic with exponential backoff on primary fetching routes (`/api/chats/sessions` and `/api/chats/{thread_id}/history`) to gracefully handle container wakeup delays if the Space does enter a sleep state.
