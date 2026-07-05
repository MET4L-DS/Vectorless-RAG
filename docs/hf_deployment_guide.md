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
