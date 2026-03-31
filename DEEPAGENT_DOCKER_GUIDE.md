# 🐳 Building & Pushing the LongCat-Video Docker Image from DeepAgent

This guide explains how to build and push the LongCat-Video Docker image to
Docker Hub so you can deploy it on RunPod (or any GPU cloud).

---

## Table of Contents

1. [Environment Overview](#environment-overview)
2. [Docker Status in DeepAgent](#docker-status-in-deepagent)
3. [Option A — Build Right Here in DeepAgent](#option-a--build-right-here-in-deepagent)
4. [Option B — Build on Your Own Machine (Recommended)](#option-b--build-on-your-own-machine)
5. [Step-by-Step: Authenticate with Docker Hub](#step-by-step-authenticate-with-docker-hub)
6. [Step-by-Step: Build the Image](#step-by-step-build-the-image)
7. [Step-by-Step: Push to Docker Hub](#step-by-step-push-to-docker-hub)
8. [Monitoring Build Progress](#monitoring-build-progress)
9. [Time & Disk Estimates](#time--disk-estimates)
10. [What Happens After the VM Shuts Down](#what-happens-after-the-vm-shuts-down)
11. [Troubleshooting](#troubleshooting)

---

## Environment Overview

| Item                | Details                                       |
|---------------------|-----------------------------------------------|
| **Docker CLI**      | ✅ Installed (Docker 29.3.0)                  |
| **Docker Daemon**   | ⚠️ Not running — see below                   |
| **Disk Space**      | ~305 GB free of 372 GB                        |
| **Model Weights**   | ✅ 67 GB already downloaded in `repo/weights/`|
| **All Files Ready** | ✅ Dockerfile, build.sh, push.sh, etc.        |

### Current Docker Status

The DeepAgent VM has the **Docker CLI** installed, but the **Docker daemon**
(`dockerd`) is not running and cannot be started directly in this containerized
environment. This means:

- ✅ You can **edit, review, and prepare** all Docker-related files here
- ✅ You can **download the entire project** (including weights) from here
- ⚠️ You **cannot run `docker build` or `docker push`** directly in this VM

> **Why?** The DeepAgent VM runs inside a container itself, and Docker-in-Docker
> requires a privileged daemon that isn't enabled in this environment.

### What You CAN Do Here

1. **Prepare everything** — all files are ready to go
2. **Start the Docker daemon** if it becomes available (the script will check)
3. **Copy files to your machine** and build there
4. **Use the all-in-one script** (`deploy_from_deepagent.sh`) which handles
   both scenarios automatically

---

## Option A — Build Right Here in DeepAgent

If Docker daemon becomes available (e.g., future DeepAgent updates), you can
build and push entirely from this environment:

```bash
cd /home/ubuntu/longcat_video_app

# Quick check — does Docker work?
docker info

# If that succeeds, use the all-in-one script:
./deploy_from_deepagent.sh
```

The `deploy_from_deepagent.sh` script will:
1. Check if Docker daemon is running
2. Prompt for your Docker Hub username
3. Log you in to Docker Hub
4. Build the image (~67 GB with weights baked in)
5. Push to Docker Hub
6. Give you the exact image name for RunPod

---

## Option B — Build on Your Own Machine (Recommended)

Since the Docker daemon is not currently available in DeepAgent, the
recommended approach is to build on a machine with Docker installed.

### Prerequisites on Your Machine

- **Docker Desktop** (macOS/Windows) or **Docker Engine** (Linux)
- **~150 GB free disk space** (67 GB weights + build layers + final image)
- **8+ GB RAM** for the build process
- **Stable internet** for pushing the ~70 GB image

### Transfer Files to Your Machine

#### Method 1: Clone/Download from This Environment

All files are at `/home/ubuntu/longcat_video_app/`. You can:
- Use the **Code Editor UI** to download files
- Copy the entire project including weights

#### Method 2: Recreate on Your Machine

If you already have the model weights downloaded:

```bash
# On your machine:
mkdir longcat_video_app && cd longcat_video_app

# Copy all deployment files (Dockerfile, app.py, handler.py, etc.)
# Make sure repo/weights/ contains the model weights

# Then build:
./build.sh

# Then push:
export DOCKER_USERNAME=your-username
./push.sh
```

---

## Step-by-Step: Authenticate with Docker Hub

### 1. Create a Docker Hub Account (if needed)

1. Go to [hub.docker.com](https://hub.docker.com)
2. Sign up for a free account
3. Remember your **username** — you'll need it

### 2. Log In via Command Line

```bash
# Interactive login (prompts for username and password)
docker login

# Or specify the username upfront
docker login -u YOUR_USERNAME

# You'll be prompted for your password or access token
```

### 3. Using Access Tokens (Recommended)

Instead of your password, use a **Personal Access Token**:

1. Go to [hub.docker.com/settings/security](https://hub.docker.com/settings/security)
2. Click **"New Access Token"**
3. Give it a name like "longcat-video-build"
4. Copy the token
5. Use it as your password when running `docker login`

```bash
# Login with access token
docker login -u YOUR_USERNAME
# When prompted for password, paste your access token
```

---

## Step-by-Step: Build the Image

```bash
cd /home/ubuntu/longcat_video_app   # or wherever your project is

# Option 1: Use the build script
./build.sh

# Option 2: Manual build command
DOCKER_BUILDKIT=1 docker build \
    --tag longcat-video:latest \
    --progress=plain \
    --file Dockerfile \
    .
```

### What Happens During the Build

| Step | What It Does | Time Estimate |
|------|-------------|---------------|
| 1 | Pull NVIDIA CUDA 12.4 base image | 2-5 min |
| 2 | Install system packages (Python, ffmpeg, etc.) | 3-5 min |
| 3 | Create Python venv & install PyTorch | 5-10 min |
| 4 | Install flash-attention (compiles from source) | 10-20 min |
| 5 | Install remaining Python deps | 3-5 min |
| 6 | Copy application code | < 1 min |
| 7 | Copy model weights (67 GB) | 5-15 min |
| 8 | Finalize runtime image | 2-3 min |
| **Total** | | **30-60 min** |

---

## Step-by-Step: Push to Docker Hub

```bash
# Set your Docker Hub username
export DOCKER_USERNAME=your-username

# Option 1: Use the push script
./push.sh

# Option 2: Manual push
docker tag longcat-video:latest docker.io/${DOCKER_USERNAME}/longcat-video:latest
docker push docker.io/${DOCKER_USERNAME}/longcat-video:latest
```

### Push Time Estimates

The image is ~70+ GB, so push time depends on upload speed:

| Upload Speed | Estimated Push Time |
|-------------|--------------------|
| 10 Mbps     | ~16 hours          |
| 50 Mbps     | ~3 hours           |
| 100 Mbps    | ~1.5 hours         |
| 500 Mbps    | ~20 minutes        |
| 1 Gbps      | ~10 minutes        |

> 💡 **Tip**: If you have slow upload, consider using a cloud VM (AWS, GCP)
> with fast internet to build and push. Many cloud VMs have 1+ Gbps upload.

---

## Monitoring Build Progress

### During Build

The `--progress=plain` flag shows detailed output:

```bash
# Watch the build in real-time
DOCKER_BUILDKIT=1 docker build --progress=plain -t longcat-video:latest .

# In another terminal, monitor disk usage
watch -n 5 'df -h / && echo "" && docker system df'
```

### During Push

```bash
# Docker shows layer-by-layer upload progress
# Example output:
# 3a4e5f6: Pushing [==>                    ]  2.1GB/67.2GB
# 7b8c9d0: Pushed
# a1b2c3d: Pushing [======>                ]  5.4GB/14.8GB
```

### Check Image Size After Build

```bash
docker images longcat-video
# REPOSITORY     TAG      IMAGE ID       SIZE
# longcat-video  latest   abc123def456   72.5GB
```

---

## Time & Disk Estimates

### Disk Space Requirements

| Component | Size |
|-----------|------|
| Model weights (source) | ~67 GB |
| Docker build cache | ~15-20 GB |
| Final Docker image | ~70-75 GB |
| **Total needed** | **~150-160 GB** |

### Time Estimates

| Phase | Time |
|-------|------|
| Build (first time) | 30-60 minutes |
| Build (cached, code change only) | 5-10 minutes |
| Push (depends on internet) | 10 min - 16 hours |
| **Total (100 Mbps upload)** | **~2 hours** |

---

## What Happens After the VM Shuts Down

> ⚠️ **Important**: The DeepAgent VM is **temporary**.

- **Source files** (`Dockerfile`, `app.py`, etc.): Persist in the VM filesystem
  during the session but are lost when the VM shuts down
- **Docker images**: Would be lost when the VM shuts down
- **Pushed images on Docker Hub**: ✅ **Persist forever** on Docker Hub
- **Model weights**: Would need to be re-downloaded in a new session

### What This Means for You

1. **If you build AND push before the VM shuts down** → Your image is safe on
   Docker Hub and ready for RunPod
2. **If you only build but don't push** → The image is lost. You'll need to
   rebuild in the next session
3. **Best practice**: Always push to Docker Hub as soon as the build completes

### Recommended Workflow

```
1. Build image         ← ~30-60 min
2. Push to Docker Hub  ← depends on internet
3. Deploy on RunPod    ← use the Docker Hub image URL
```

Once pushed, you never need this VM again — RunPod pulls directly from
Docker Hub.

---

## Troubleshooting

### "Cannot connect to Docker daemon"

```
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Solution**: The Docker daemon isn't running. In DeepAgent, try:
```bash
sudo dockerd &    # May not work in all environments
```
If this fails, you'll need to build on your own machine or a cloud VM.

### "No space left on device"

```bash
# Clean up Docker cache
docker system prune -a

# Check disk usage
df -h /
```

### Build Fails at flash-attention

flash-attn compilation needs lots of RAM and time:
```bash
# The Dockerfile uses a pre-built wheel — if it fails, try:
pip install flash-attn --no-build-isolation
```

### Push is Too Slow

Consider:
1. Using a cloud VM with faster upload
2. Splitting the image into smaller layers
3. Using a registry closer to your location

### "Denied: requested access to the resource is denied"

```bash
# Make sure you're logged in
docker login

# Make sure the image tag matches your username
docker tag longcat-video:latest YOUR_USERNAME/longcat-video:latest
docker push YOUR_USERNAME/longcat-video:latest
```

---

## Quick Reference

```bash
# === Full workflow ===
cd /home/ubuntu/longcat_video_app

# 1. Login
docker login -u YOUR_USERNAME

# 2. Build
./build.sh

# 3. Push
export DOCKER_USERNAME=YOUR_USERNAME
./push.sh

# === Or use the all-in-one script ===
./deploy_from_deepagent.sh
```

The image name for RunPod will be:
```
docker.io/YOUR_USERNAME/longcat-video:latest
```
