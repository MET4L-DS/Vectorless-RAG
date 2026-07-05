import os
from huggingface_hub import HfApi

def main():
    print("Initializing Hugging Face API...")
    api = HfApi()
    
    repo_id = "Ayanshu/Legal-Vectorless-RAG-HF"
    print(f"Uploading current directory to Space: {repo_id}...")
    
    # Upload folder bypassing local git history and ignoring local files/folders
    api.upload_folder(
        folder_path=".",
        repo_id=repo_id,
        repo_type="space",
        ignore_patterns=[
            ".venv/*",
            ".git/*",
            "__pycache__/*",
            "*.db",
            "*.db-wal",
            "*.db-shm",
            "output/*",
            "tree/bm25_index/*",
            ".env",
            "scratch/*",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "deploy.py",
            "test_args.py",
        ]
    )
    print("Deployment completed successfully!")

if __name__ == "__main__":
    main()
