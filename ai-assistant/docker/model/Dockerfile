# GPU-enabled Docker image for model inference
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    git \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Upgrade pip
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch with CUDA support
RUN pip3 install --no-cache-dir \
    torch==2.1.2 \
    torchvision==0.16.2 \
    torchaudio==2.1.2 \
    --index-url https://download.pytorch.org/whl/cu121

# Install model dependencies
RUN pip3 install --no-cache-dir \
    transformers==4.36.2 \
    accelerate==0.26.1 \
    bitsandbytes==0.41.3 \
    sentencepiece==0.1.99 \
    protobuf==3.20.3 \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    pydantic==2.5.3 \
    python-multipart==0.0.6 \
    aiofiles==23.2.1

# Create working directory
WORKDIR /app

# Create model directories
RUN mkdir -p /models /app/logs

# Copy model server code
COPY backend/models/llm /app/models/llm
COPY backend/utils /app/utils
COPY backend/core/config /app/core/config

# Create non-root user
RUN useradd -m -u 1000 modeluser && \
    chown -R modeluser:modeluser /app /models
USER modeluser

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Start model server
CMD ["uvicorn", "models.llm.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
