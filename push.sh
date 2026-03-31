#!/usr/bin/env bash
# =============================================================================
# push.sh — Tag and push the Docker image to Docker Hub (or any registry)
# =============================================================================
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-longcat-video}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# ---- Registry config --------------------------------------------------------
# Set these env vars or edit the defaults below:
DOCKER_USERNAME="${DOCKER_USERNAME:-your-dockerhub-username}"
REGISTRY="${REGISTRY:-docker.io}"
FULL_IMAGE="${REGISTRY}/${DOCKER_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "══════════════════════════════════════════════════════════════"
echo "  Pushing image → ${FULL_IMAGE}"
echo "══════════════════════════════════════════════════════════════"

# Check login
if ! docker info 2>/dev/null | grep -q "Username"; then
    echo "🔑  Not logged in — running docker login …"
    docker login "${REGISTRY}"
fi

# Tag
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}"

# Push
docker push "${FULL_IMAGE}"

echo ""
echo "✅  Push complete: ${FULL_IMAGE}"
echo ""
echo "Use this image name in RunPod:"
echo "  ${FULL_IMAGE}"
