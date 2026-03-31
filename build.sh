#!/usr/bin/env bash
# =============================================================================
# build.sh — Build the LongCat-Video Docker image
# =============================================================================
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-longcat-video}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "══════════════════════════════════════════════════════════════"
echo "  Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "══════════════════════════════════════════════════════════════"

# Verify weights exist
if [ ! -d "repo/weights/LongCat-Video" ] || [ ! -d "repo/weights/LongCat-Video-Avatar" ]; then
    echo "❌  Model weights not found in repo/weights/"
    echo "    Please download them first (see DEPLOYMENT_GUIDE.md)"
    exit 1
fi

WEIGHTS_SIZE=$(du -sh repo/weights/ | cut -f1)
echo "📦  Weights directory size: ${WEIGHTS_SIZE}"
echo ""

# Build with BuildKit for better caching
export DOCKER_BUILDKIT=1

docker build \
    --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
    --progress=plain \
    --file Dockerfile \
    .

echo ""
echo "✅  Image built successfully: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "    Image size: $(docker image inspect ${IMAGE_NAME}:${IMAGE_TAG} --format='{{.Size}}' | numfmt --to=iec 2>/dev/null || docker images ${IMAGE_NAME}:${IMAGE_TAG} --format '{{.Size}}')"
echo ""
echo "Next steps:"
echo "  • Test locally:  ./test_local.sh"
echo "  • Push to hub:   ./push.sh"
