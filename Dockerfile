# =============================================================================
# Dockerfile — LongCat-Video Avatar  (RunPod Serverless / A100 optimised)
# =============================================================================
# Two-stage build:
#   Stage 1  "builder"  — install Python deps + download model weights
#   Stage 2  "runtime"  — lean image with only what we need
#
# Model weights are downloaded from HuggingFace during build.
# They are NOT expected to be in the Git repository.
# =============================================================================

# --------------- Stage 1: builder -------------------------------------------
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3-pip python3.10-dev \
        git wget curl build-essential ninja-build \
        ffmpeg libsndfile1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create venv
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch first (CUDA 12.4)
RUN pip install --no-cache-dir \
    torch==2.6.0+cu124 \
    torchaudio==2.6.0+cu124 \
    torchvision==0.21.0+cu124 \
    --index-url https://download.pytorch.org/whl/cu124

# Install flash-attn via pre-built wheel (avoids long compilation; matched to cu124 + torch2.6 + py3.10)
RUN pip install --no-cache-dir \
    "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu124torch2.6cxx11abiTRUE-cp310-cp310-linux_x86_64.whl"

# Install remaining deps
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt 2>/dev/null || \
    pip install --no-cache-dir -r /tmp/requirements.txt --ignore-installed torch torchaudio torchvision

# Install huggingface-cli for model downloads
RUN pip install --no-cache-dir huggingface_hub

# --------------- Download model weights from HuggingFace --------------------
RUN mkdir -p /weights/LongCat-Video /weights/LongCat-Video-Avatar

# Download base model components (tokenizer, text_encoder, vae, scheduler)
RUN huggingface-cli download meituan-longcat/LongCat-Video \
    --local-dir /weights/LongCat-Video \
    --include "tokenizer/*" "text_encoder/*" "vae/*" "scheduler/*"

# Download avatar model components
RUN huggingface-cli download meituan-longcat/LongCat-Video-Avatar \
    --local-dir /weights/LongCat-Video-Avatar \
    --include "avatar_single/*" "chinese-wav2vec2-base/*" "vocal_separator/*"

# --------------- Stage 2: runtime -------------------------------------------
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv \
        ffmpeg libsndfile1 libgl1 libglib2.0-0 \
        curl wget \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Application directory
WORKDIR /app

# Copy application code (repo source code, NOT weights)
COPY app.py handler.py ./
COPY repo/ ./repo/

# Copy downloaded weights into the expected location
COPY --from=builder /weights/LongCat-Video     ./repo/weights/LongCat-Video/
COPY --from=builder /weights/LongCat-Video-Avatar ./repo/weights/LongCat-Video-Avatar/

# Pre-create output dirs
RUN mkdir -p /app/outputs /app/audio_temp

# Expose Gradio port
EXPOSE 7860

# Health check for RunPod
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

# Default: run serverless handler (for RunPod Serverless)
CMD ["python3", "handler.py"]
