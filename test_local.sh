#!/usr/bin/env bash
# =============================================================================
# test_local.sh — Run the container locally for quick smoke-testing
# =============================================================================
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-longcat-video}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MODE="${1:-gradio}"   # "gradio" (default) or "serverless"

echo "══════════════════════════════════════════════════════════════"
echo "  Local test — mode: ${MODE}"
echo "══════════════════════════════════════════════════════════════"

if [ "${MODE}" = "serverless" ]; then
    echo "Starting serverless handler on port 8000 …"
    docker run --rm -it \
        --gpus all \
        -p 8000:8000 \
        -v "$(pwd)/outputs:/app/outputs" \
        "${IMAGE_NAME}:${IMAGE_TAG}" \
        python3 handler.py
else
    echo "Starting Gradio UI on port 7860 …"
    echo "Open http://localhost:7860 in your browser."
    docker run --rm -it \
        --gpus all \
        -p 7860:7860 \
        -v "$(pwd)/outputs:/app/outputs" \
        -e GRADIO_SERVER_NAME=0.0.0.0 \
        "${IMAGE_NAME}:${IMAGE_TAG}" \
        python3 app.py
fi
