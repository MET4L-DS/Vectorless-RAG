# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/tmp/huggingface

# Create a non-root user (UID 1000) required by HF Spaces
RUN useradd -m -u 1000 user
USER user

# Set home to the user's home and update PATH
ENV HOME=/home/user
ENV PATH=$HOME/.local/bin:$PATH

# Set working directory
WORKDIR $HOME/app

# Install system dependencies (must be done as root)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Switch back to user
USER user

# Install python dependencies
COPY --chown=user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=user . $HOME/app

# Expose the port Hugging Face Spaces expects
EXPOSE 7860

# Run uvicorn on port 7860 (required by HF Spaces)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
