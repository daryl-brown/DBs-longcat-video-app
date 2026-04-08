# =============================================================================
# Dockerfile — LongCat-Video Avatar  (RunPod Serverless / A100 optimised)
# =============================================================================
# Two-stage build:
#   Stage 1  "builder"  — install Python deps
#   Stage 2  "runtime"  — lean image with only what we need
#
# Model weights are NOT baked into the image.
# They are downloaded from HuggingFace on first cold start by handler.py.
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

# Clone LongCat-Video source code (provides the longcat_video Python package)
RUN git clone --depth 1 https://github.com/meituan-longcat/LongCat-Video /opt/longcat-repo

# Install flash-attn — try pre-built wheel first, fall back to source compile
# Pre-built wheels from: https://github.com/mjun0812/flash-attention-prebuild-wheels
RUN pip install --no-cache-dir ninja packaging psutil && \
    pip install --no-cache-dir \
        https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.16/flash_attn-2.7.4+cu124torch2.6-cp310-cp310-linux_x86_64.whl \
    2>/dev/null || \
    pip install --no-cache-dir flash-attn==2.7.4.post1 --no-build-isolation

# Install remaining deps
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt 2>/dev/null || \
    pip install --no-cache-dir -r /tmp/requirements.txt --ignore-installed torch torchaudio torchvision

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

# Pre-create output and weights dirs (v2)
RUN mkdir -p /app/outputs /app/audio_temp /app/repo/weights/LongCat-Video /app/repo/weights/LongCat-Video-Avatar

# Copy application code
COPY app.py handler.py ./

# Copy longcat_video source package from builder
COPY --from=builder /opt/longcat-repo /app/repo

# Expose Gradio port
EXPOSE 7860

# Health check for RunPod
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

# Default: run serverless handler (for RunPod Serverless)
CMD ["python3", "handler.py"]
