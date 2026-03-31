# =============================================================================
# Dockerfile — LongCat-Video Avatar  (RunPod / A100 optimised)
# =============================================================================
# Two-stage build:
#   Stage 1  "builder"  — install Python deps in a venv
#   Stage 2  "runtime"  — lean image with only what we need
#
# Expected build context: /home/ubuntu/longcat_video_app
# The repo/ directory (including weights/) must be present.
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

# Install flash-attn (needs torch already installed)
RUN pip install --no-cache-dir flash-attn==2.7.4.post1 --no-build-isolation

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

# Copy application code
COPY app.py handler.py ./
COPY repo/ ./repo/

# Pre-create output dirs
RUN mkdir -p /app/outputs /app/audio_temp

# Expose Gradio port
EXPOSE 7860

# Health check for RunPod
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

# Default: run the Gradio app  (override with handler.py for serverless)
CMD ["python3", "app.py"]
