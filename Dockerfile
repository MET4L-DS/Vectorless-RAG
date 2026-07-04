# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/tmp/huggingface

# Set working directory
WORKDIR /app

# Install system dependencies (including git if needed, and build-essential for any compiled packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the port Hugging Face Spaces expects
EXPOSE 7860

# Run uvicorn on port 7860 (required by HF Spaces)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
