# LongCat-Video Avatar — RunPod Deployment Guide

> **Audio-driven portrait/avatar lipsync video generation on RunPod GPUs.**
> Supports both **RunPod Pods** (interactive Gradio UI) and **RunPod Serverless** (API-only).

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Option A — RunPod Pods Deployment (Gradio UI)](#option-a--runpod-pods-deployment-gradio-ui)
4. [Option B — RunPod Serverless Deployment (API)](#option-b--runpod-serverless-deployment-api)
5. [Building the Docker Image](#building-the-docker-image)
6. [Pushing to a Container Registry](#pushing-to-a-container-registry)
7. [Testing Your Deployment](#testing-your-deployment)
8. [Troubleshooting](#troubleshooting)
9. [Cost Estimates & Optimisation](#cost-estimates--optimisation)

---

## Prerequisites

| Requirement | Details |
|---|---|
| **RunPod account** | Sign up at [runpod.io](https://runpod.io) and add billing credits |
| **Docker** | Docker Desktop or Docker Engine installed locally (with NVIDIA Container Toolkit if testing with GPU) |
| **Docker Hub account** (or other registry) | Needed to push the image so RunPod can pull it |
| **Model weights** | ~67 GB in `repo/weights/` — download via the Gradio app's "Download Models" button or HuggingFace CLI |
| **Disk space** | ~100 GB free for building the Docker image |
| **GPU (local testing)** | NVIDIA A100 80 GB recommended; 40 GB may work at 480p |

---

## Project Structure

```
longcat_video_app/
├── app.py                 # Gradio web interface
├── handler.py             # RunPod serverless handler
├── Dockerfile             # Multi-stage Docker build
├── docker-compose.yml     # Local testing with Docker Compose
├── requirements.txt       # Python dependencies
├── .dockerignore          # Docker build exclusions
├── build.sh               # Build helper script
├── push.sh                # Push helper script
├── test_local.sh          # Local test helper script
├── DEPLOYMENT_GUIDE.md    # This file
├── outputs/               # Generated videos (created at runtime)
├── audio_temp/            # Temporary audio files (created at runtime)
└── repo/                  # LongCat-Video repository
    ├── longcat_video/     # Python package
    └── weights/           # Model weights (~67 GB)
        ├── LongCat-Video/
        └── LongCat-Video-Avatar/
```

---

## Option A — RunPod Pods Deployment (Gradio UI)

This option gives you a persistent GPU instance with the Gradio web interface.

### Step 1: Build and Push the Docker Image

```bash
# Build the image (from the longcat_video_app directory)
./build.sh

# Set your Docker Hub username and push
export DOCKER_USERNAME="your-dockerhub-username"
./push.sh
```

### Step 2: Create a RunPod Pod

1. Go to **[RunPod Console → Pods](https://www.runpod.io/console/pods)**
2. Click **"+ Deploy"**
3. Select GPU: **A100 80GB** (or A100 PCIe 80GB)
4. Under **"Container Image"**, enter your image:
   ```
   docker.io/your-dockerhub-username/longcat-video:latest
   ```
5. Set **Container Disk** to at least **20 GB** (for outputs)
6. Set **Volume Disk** to **0 GB** (weights are in the image)
7. Under **"Expose HTTP Ports"**, add: **7860**
8. Click **"Deploy On-Demand"** (or Spot if you want lower cost)

### Step 3: Access the Gradio UI

1. Wait for the pod status to show **"Running"** (cold start takes 2-5 minutes)
2. Click the **"Connect"** button on your pod
3. Click **"HTTP Service [Port 7860]"** — this opens the Gradio UI
4. Alternatively, note the pod's proxy URL: `https://<pod-id>-7860.proxy.runpod.net`

### Step 4: Use the Application

1. In the Gradio UI, go to the **"Setup & Status"** tab
2. Click **"Load Pipeline to GPU"** (first load takes ~2 minutes)
3. Switch to the **"Generate Video"** tab
4. Upload your portrait image and audio file
5. Configure resolution, mode, and parameters
6. Click **"Generate Lipsync Video"**

---

## Option B — RunPod Serverless Deployment (API)

This option creates an auto-scaling API endpoint — you only pay when processing requests.

### Step 1: Build and Push the Docker Image

Same as Option A above. The image contains both `app.py` and `handler.py`.

### Step 2: Create a Serverless Endpoint

1. Go to **[RunPod Console → Serverless](https://www.runpod.io/console/serverless)**
2. Click **"+ New Endpoint"**
3. Configure:
   - **Endpoint Name**: `longcat-video-avatar`
   - **Container Image**: `docker.io/your-dockerhub-username/longcat-video:latest`
   - **Container Start Command**: `python3 handler.py`
   - **GPU**: A100 80GB
   - **Max Workers**: 1 (increase if needed)
   - **Idle Timeout**: 300 seconds (keeps the model loaded between requests)
   - **Execution Timeout**: 600 seconds (video generation can take a while)
   - **Container Disk**: 20 GB
4. Click **"Create"**

### Step 3: Get Your API Key and Endpoint ID

1. Copy the **Endpoint ID** from the serverless dashboard
2. Get your **API Key** from [RunPod Settings → API Keys](https://www.runpod.io/console/user/settings)

### Step 4: Send a Request

```bash
RUNPOD_API_KEY="your-api-key"
ENDPOINT_ID="your-endpoint-id"

# Encode your image and audio to base64
IMAGE_B64=$(base64 -w0 portrait.png)
AUDIO_B64=$(base64 -w0 speech.wav)

# Submit the job
curl -s -X POST \
  "https://api.runpod.ai/v2/${ENDPOINT_ID}/run" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"input\": {
      \"image\": \"${IMAGE_B64}\",
      \"audio\": \"${AUDIO_B64}\",
      \"resolution\": \"480p\",
      \"aspect_ratio\": \"16:9\",
      \"mode\": \"ai2v\",
      \"num_inference_steps\": 30,
      \"guidance_scale\": 5.0,
      \"audio_guidance_scale\": 3.0,
      \"seed\": 42,
      \"continuation_segments\": 2
    }
  }"
```

The response will contain a `job_id`. Poll for results:

```bash
# Check job status
curl -s \
  "https://api.runpod.ai/v2/${ENDPOINT_ID}/status/${JOB_ID}" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  | python3 -m json.tool
```

When complete, the response includes `video_base64`. Decode it:

```bash
# Extract and decode the video
echo "${VIDEO_BASE64}" | base64 -d > output_video.mp4
```

### Alternative: Use URL Inputs

Instead of base64, you can pass URLs for the image and audio:

```json
{
  "input": {
    "image": "https://images.pexels.com/photos/7428875/pexels-photo-7428875.jpeg?cs=srgb&dl=pexels-august-de-richelieu-7428875.jpg&fm=jpg",
    "audio": "https://example.com/speech.wav",
    "resolution": "480p"
  }
}
```

---

## Building the Docker Image

### Quick Build

```bash
cd /path/to/longcat_video_app
chmod +x build.sh push.sh test_local.sh
./build.sh
```

### Manual Build

```bash
DOCKER_BUILDKIT=1 docker build -t longcat-video:latest .
```

### Custom Image Name/Tag

```bash
IMAGE_NAME=my-longcat IMAGE_TAG=v1.0 ./build.sh
```

> **⚠️ Build size warning:** The image will be **~80–90 GB** because the model weights (~67 GB) are baked in. This ensures fast cold starts on RunPod but requires significant upload bandwidth.

### Alternative: Download Weights at Runtime

If you'd rather not bake weights into the image (smaller image, slower cold start):

1. Add `repo/weights/` to `.dockerignore`
2. The Gradio app's "Download Models" button will download weights on first run
3. Use a RunPod **Network Volume** to persist weights between restarts

---

## Pushing to a Container Registry

### Docker Hub

```bash
export DOCKER_USERNAME="your-username"
./push.sh
```

### Alternative Registries

**GitHub Container Registry (ghcr.io):**
```bash
export REGISTRY="ghcr.io"
export DOCKER_USERNAME="your-github-username"
./push.sh
```

**RunPod Container Registry (if available):**
```bash
export REGISTRY="registry.runpod.io"
export DOCKER_USERNAME="your-runpod-username"
./push.sh
```

> **💡 Tip:** For large images, consider using a registry geographically close to RunPod's data centres (US) to speed up pulls.

---

## Testing Your Deployment

### Local Test with Docker

```bash
# Test Gradio UI mode
./test_local.sh gradio
# → Open http://localhost:7860

# Test serverless handler mode
./test_local.sh serverless
```

### Local Test with Docker Compose

```bash
# Gradio mode
docker compose up gradio

# Serverless mode
docker compose --profile serverless up serverless
```

### Test the Serverless Handler Locally

With the serverless container running:

```bash
IMAGE_B64=$(base64 -w0 test_portrait.png)
AUDIO_B64=$(base64 -w0 test_audio.wav)

curl -s -X POST http://localhost:8000/runsync \
  -H "Content-Type: application/json" \
  -d "{
    \"input\": {
      \"image\": \"${IMAGE_B64}\",
      \"audio\": \"${AUDIO_B64}\",
      \"resolution\": \"480p\",
      \"aspect_ratio\": \"16:9\"
    }
  }" | python3 -c "
import sys, json, base64
resp = json.load(sys.stdin)
if 'output' in resp and 'video_base64' in resp['output']:
    with open('test_output.mp4', 'wb') as f:
        f.write(base64.b64decode(resp['output']['video_base64']))
    print('✅ Video saved to test_output.mp4')
else:
    print(resp)
"
```

### Python Client for RunPod Serverless

```python
import runpod
import base64

runpod.api_key = "your-runpod-api-key"
endpoint = runpod.Endpoint("your-endpoint-id")

# Read and encode files
with open("portrait.png", "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode()
with open("speech.wav", "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

# Submit job
run = endpoint.run({
    "image": image_b64,
    "audio": audio_b64,
    "resolution": "480p",
    "aspect_ratio": "16:9",
    "mode": "ai2v",
    "num_inference_steps": 30,
    "seed": 42,
})

# Wait for result (blocks until done)
result = run.output()

# Save video
with open("output.mp4", "wb") as f:
    f.write(base64.b64decode(result["video_base64"]))

print(f"Video saved! Duration: {result['duration_sec']}s, Resolution: {result['resolution']}")
```

---

## Troubleshooting

### Common Issues

| Problem | Solution |
|---|---|
| **OOM (Out of Memory)** | Use A100 80GB. Reduce resolution to 480p. Reduce `continuation_segments`. |
| **Slow cold start** | The 67 GB of weights take time to load. Use Pods with idle timeout to keep the model loaded. |
| **"CUDA out of memory"** | Ensure you selected A100 80GB. Close any other processes using GPU memory. |
| **Container fails to start** | Check RunPod logs. Ensure the image was built and pushed successfully. |
| **Gradio UI not accessible** | Verify port 7860 is exposed. Check that `GRADIO_SERVER_NAME=0.0.0.0` is set. |
| **Serverless timeout** | Increase execution timeout (default 600s). Reduce video length/resolution. |
| **Model download fails** | If not baking weights, ensure internet access is available. Check HuggingFace Hub status. |
| **Audio issues** | Ensure audio is WAV or MP3 format. The vocal separator expects clean audio input. |
| **Black/corrupted video** | Try different seed values. Ensure the input image is a clear portrait photo. |

### Checking Logs

**RunPod Pods:**
- Click "Logs" on your pod in the RunPod dashboard
- Or SSH into the pod: `ssh root@<pod-ip> -p <ssh-port>`

**RunPod Serverless:**
- Check the "Logs" tab on your endpoint page
- Each job has its own log output

### GPU Memory Requirements

| Resolution | Min VRAM | Recommended |
|---|---|---|
| 480p (832×480) | ~40 GB | A100 80GB |
| 720p (1280×720) | ~60 GB | A100 80GB |
| 1080p (1920×1080) | ~75 GB | A100 80GB |

---

## Cost Estimates & Optimisation

### RunPod GPU Pricing (approximate, as of 2026)

| GPU | On-Demand | Spot | VRAM |
|---|---|---|---|
| A100 80GB SXM | ~$1.64/hr | ~$0.89/hr | 80 GB |
| A100 80GB PCIe | ~$1.44/hr | ~$0.79/hr | 80 GB |
| H100 80GB | ~$3.29/hr | ~$2.09/hr | 80 GB |

> Prices vary — check [runpod.io/pricing](https://www.runpod.io/pricing) for current rates.

### Cost Per Video (approximate)

| Resolution | Generation Time | Cost (On-Demand A100) |
|---|---|---|
| 480p, 3 segments | ~3-5 min | ~$0.08-0.14 |
| 720p, 3 segments | ~8-12 min | ~$0.19-0.29 |
| 1080p, 3 segments | ~15-25 min | ~$0.37-0.61 |

### Optimisation Tips

1. **Use Spot instances** — Save 40-50% on RunPod Pods (may be interrupted).
2. **Pods vs Serverless** — Use Pods if you generate many videos per session (avoid cold starts). Use Serverless if usage is sporadic.
3. **Idle timeout (Serverless)** — Set to 300s to keep the model loaded between requests. Lower if you want to save money during gaps.
4. **480p for drafts** — Generate quick drafts at 480p, then re-render final versions at higher resolution.
5. **Reduce continuation segments** — Fewer segments = shorter video = less cost. Each segment adds ~1-3 min of generation time.
6. **Network Volumes** — If not baking weights, use a RunPod Network Volume to persist model weights across pod restarts and avoid re-downloading 67 GB.
7. **Build image near RunPod** — Build and push from a US-based cloud VM for faster image pulls.
8. **Template** — Save your pod configuration as a RunPod Template for quick redeployment.

### Monthly Cost Examples

| Usage Pattern | Setup | Est. Monthly Cost |
|---|---|---|
| Light (10 videos/month) | Serverless, A100 spot | ~$5-15 |
| Medium (50 videos/month) | Serverless, A100 on-demand | ~$25-75 |
| Heavy (daily, 8hr/day) | Pod, A100 spot | ~$200-250 |
| Production (24/7) | Pod, A100 on-demand | ~$1,050-1,200 |

---

## Quick Reference

```bash
# Build the Docker image
./build.sh

# Push to Docker Hub
DOCKER_USERNAME=myuser ./push.sh

# Test locally (Gradio)
./test_local.sh gradio

# Test locally (Serverless)
./test_local.sh serverless
```

**RunPod Pods URL pattern:** `https://<pod-id>-7860.proxy.runpod.net`
**RunPod Serverless API:** `https://api.runpod.ai/v2/<endpoint-id>/run`

---

*Built for LongCat-Video Avatar — Audio-driven lipsync generation.*
