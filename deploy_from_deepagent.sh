#!/usr/bin/env bash
# =============================================================================
# deploy_from_deepagent.sh — All-in-one: Build & Push LongCat-Video from DeepAgent
# =============================================================================
# This script handles everything:
#   1. Checks Docker daemon availability
#   2. Prompts for Docker Hub credentials
#   3. Builds the image
#   4. Pushes to Docker Hub
#   5. Gives you the RunPod-ready image URL
# =============================================================================
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-longcat-video}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY="${REGISTRY:-docker.io}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
}

print_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
}

print_ok() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# =============================================================================
# Step 0: Pre-flight checks
# =============================================================================
print_header "LongCat-Video — Build & Push to Docker Hub"

echo -e "\n${BLUE}📋 Pre-flight Checks${NC}"
echo "─────────────────────────────────────────"

# Check we're in the right directory
cd "${SCRIPT_DIR}"
print_ok "Working directory: $(pwd)"

# Check Docker CLI
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version 2>&1)
    print_ok "Docker CLI: ${DOCKER_VERSION}"
else
    print_error "Docker CLI not found. Please install Docker first."
    exit 1
fi

# Check Docker daemon
print_step "Checking Docker daemon..."
if docker info &> /dev/null; then
    print_ok "Docker daemon is running"
else
    print_warn "Docker daemon is NOT running."
    echo ""
    echo "    The Docker daemon cannot be started in this environment."
    echo "    You have two options:"
    echo ""
    echo "    1. Run this script on a machine with Docker installed"
    echo "    2. Copy files from /home/ubuntu/longcat_video_app/ to your machine"
    echo ""
    echo "    Attempting to start daemon anyway..."
    
    # Try starting it (may work in some environments)
    if sudo dockerd &> /dev/null & then
        sleep 3
        if docker info &> /dev/null; then
            print_ok "Docker daemon started successfully!"
        else
            print_error "Could not start Docker daemon."
            echo ""
            echo "    To build on your own machine:"
            echo "    ┌─────────────────────────────────────────────────┐"
            echo "    │  cd /path/to/longcat_video_app                  │"
            echo "    │  docker login -u YOUR_USERNAME                   │"
            echo "    │  ./build.sh                                      │"
            echo "    │  export DOCKER_USERNAME=YOUR_USERNAME             │"
            echo "    │  ./push.sh                                       │"
            echo "    └─────────────────────────────────────────────────┘"
            exit 1
        fi
    fi
fi

# Check model weights
if [ ! -d "repo/weights/LongCat-Video" ] || [ ! -d "repo/weights/LongCat-Video-Avatar" ]; then
    print_error "Model weights not found in repo/weights/"
    echo "    Please download them first. See DEPLOYMENT_GUIDE.md."
    exit 1
fi
WEIGHTS_SIZE=$(du -sh repo/weights/ | cut -f1)
print_ok "Model weights found: ${WEIGHTS_SIZE}"

# Check disk space
AVAILABLE_GB=$(df -BG / | tail -1 | awk '{print $4}' | tr -d 'G')
print_ok "Available disk space: ${AVAILABLE_GB} GB"
if [ "${AVAILABLE_GB}" -lt 100 ]; then
    print_warn "Less than 100 GB free. Build may fail. Recommend 150+ GB."
fi

# Check Dockerfile
if [ ! -f "Dockerfile" ]; then
    print_error "Dockerfile not found in $(pwd)"
    exit 1
fi
print_ok "Dockerfile found"

echo ""
echo "─────────────────────────────────────────"
print_ok "All pre-flight checks passed!"

# =============================================================================
# Step 1: Get Docker Hub credentials
# =============================================================================
print_header "Step 1: Docker Hub Authentication"

# Check if already logged in
if docker info 2>/dev/null | grep -q "Username"; then
    EXISTING_USER=$(docker info 2>/dev/null | grep "Username" | awk '{print $2}')
    echo -e "Currently logged in as: ${GREEN}${EXISTING_USER}${NC}"
    read -p "Use this account? [Y/n]: " USE_EXISTING
    if [[ "${USE_EXISTING:-Y}" =~ ^[Yy]$ ]]; then
        DOCKER_USERNAME="${EXISTING_USER}"
    else
        read -p "Enter Docker Hub username: " DOCKER_USERNAME
    fi
else
    # Prompt for username
    if [ "${DOCKER_USERNAME:-your-dockerhub-username}" = "your-dockerhub-username" ]; then
        echo ""
        echo "  You need a Docker Hub account to push the image."
        echo "  Sign up free at: https://hub.docker.com"
        echo ""
        read -p "  Enter your Docker Hub username: " DOCKER_USERNAME
    fi
fi

if [ -z "${DOCKER_USERNAME}" ]; then
    print_error "No username provided. Exiting."
    exit 1
fi

FULL_IMAGE="${REGISTRY}/${DOCKER_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo -e "  Image will be pushed as: ${GREEN}${FULL_IMAGE}${NC}"
echo ""

# Login
print_step "Logging in to Docker Hub..."
echo "  (Use an Access Token instead of password for better security)"
echo "  Generate one at: https://hub.docker.com/settings/security"
echo ""

if ! docker login -u "${DOCKER_USERNAME}" "${REGISTRY}"; then
    print_error "Docker login failed. Please check your credentials."
    exit 1
fi
print_ok "Logged in to Docker Hub as ${DOCKER_USERNAME}"

# =============================================================================
# Step 2: Build the Docker image
# =============================================================================
print_header "Step 2: Building Docker Image"

echo ""
echo "  Image name:  ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  Weights:     ${WEIGHTS_SIZE}"
echo "  Disk free:   ${AVAILABLE_GB} GB"
echo ""
echo "  ⏱️  Estimated build time: 30-60 minutes"
echo "  📦 Estimated image size: ~70-75 GB"
echo ""

read -p "  Start build? [Y/n]: " CONFIRM_BUILD
if [[ ! "${CONFIRM_BUILD:-Y}" =~ ^[Yy]$ ]]; then
    echo "Build cancelled."
    exit 0
fi

BUILD_START=$(date +%s)
print_step "Building image (this will take a while)..."
echo ""

export DOCKER_BUILDKIT=1
if docker build \
    --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
    --progress=plain \
    --file Dockerfile \
    . ; then
    BUILD_END=$(date +%s)
    BUILD_DURATION=$(( (BUILD_END - BUILD_START) / 60 ))
    print_ok "Image built successfully in ~${BUILD_DURATION} minutes!"
    
    IMAGE_SIZE=$(docker images "${IMAGE_NAME}:${IMAGE_TAG}" --format '{{.Size}}' 2>/dev/null || echo "unknown")
    echo "  Image size: ${IMAGE_SIZE}"
else
    print_error "Build failed! Check the output above for errors."
    exit 1
fi

# =============================================================================
# Step 3: Push to Docker Hub
# =============================================================================
print_header "Step 3: Pushing to Docker Hub"

echo ""
echo -e "  Destination: ${GREEN}${FULL_IMAGE}${NC}"
echo ""
echo "  ⏱️  Push time depends on your upload speed:"
echo "     100 Mbps → ~1.5 hours"
echo "     500 Mbps → ~20 minutes"
echo "       1 Gbps → ~10 minutes"
echo ""

read -p "  Start push? [Y/n]: " CONFIRM_PUSH
if [[ ! "${CONFIRM_PUSH:-Y}" =~ ^[Yy]$ ]]; then
    echo "Push skipped. You can push later with:"
    echo "  docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${FULL_IMAGE}"
    echo "  docker push ${FULL_IMAGE}"
    exit 0
fi

PUSH_START=$(date +%s)
print_step "Tagging image..."
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}"
print_ok "Tagged: ${FULL_IMAGE}"

print_step "Pushing to Docker Hub (this may take a while)..."
echo ""
if docker push "${FULL_IMAGE}"; then
    PUSH_END=$(date +%s)
    PUSH_DURATION=$(( (PUSH_END - PUSH_START) / 60 ))
    echo ""
    print_ok "Push completed in ~${PUSH_DURATION} minutes!"
else
    print_error "Push failed! Check the output above for errors."
    echo "You can retry with:"
    echo "  docker push ${FULL_IMAGE}"
    exit 1
fi

# =============================================================================
# Done!
# =============================================================================
print_header "🎉 Deployment Complete!"

TOTAL_END=$(date +%s)
TOTAL_DURATION=$(( (TOTAL_END - BUILD_START) / 60 ))

echo ""
echo -e "  ${GREEN}Total time: ~${TOTAL_DURATION} minutes${NC}"
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo -e "  │  Docker Hub image: ${GREEN}${FULL_IMAGE}${NC}"
echo "  └─────────────────────────────────────────────────────────┘"
echo ""
echo "  Next steps for RunPod deployment:"
echo ""
echo "  1. Go to https://www.runpod.io/console/pods"
echo "  2. Click 'Deploy' → Choose an A100 80GB GPU"
echo "  3. Set Container Image to:"
echo -e "     ${CYAN}${FULL_IMAGE}${NC}"
echo "  4. Set Container Disk to: 20 GB"
echo "  5. Set Volume Disk to: 0 GB (weights are in the image)"
echo "  6. Expose HTTP Port: 7860"
echo "  7. Deploy!"
echo ""
echo "  The Gradio UI will be available at the RunPod-provided URL."
echo ""
echo "  For Serverless deployment, see DEPLOYMENT_GUIDE.md"
echo ""
