# 🚀 RunPod Serverless Setup Guide

Step-by-step instructions to deploy LongCat-Video Avatar as a RunPod Serverless endpoint.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Push Code to GitHub](#2-push-code-to-github)
3. [Build the Docker Image](#3-build-the-docker-image)
   - [Option A: Docker Hub (build locally or on a server)](#option-a-docker-hub)
   - [Option B: RunPod Build System (GitHub link)](#option-b-runpod-build-system)
4. [Create a RunPod Serverless Endpoint](#4-create-a-runpod-serverless-endpoint)
5. [Configure the Endpoint](#5-configure-the-endpoint)
6. [Test Your Endpoint](#6-test-your-endpoint)
7. [API Reference](#7-api-reference)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

- [ ] A **GitHub** account (free) — [github.com](https://github.com)
- [ ] A **RunPod** account — [runpod.io](https://runpod.io)
- [ ] A **Docker Hub** account (free) — [hub.docker.com](https://hub.docker.com) *(only for Option A)*
- [ ] RunPod credits loaded (A100 80GB costs ~$1.64/hr on-demand)

---

## 2. Push Code to GitHub

See **[GITHUB_PUSH_COMMANDS.txt](GITHUB_PUSH_COMMANDS.txt)** for exact commands.

Quick summary:

```bash
# 1. Create a new repo on GitHub (github.com → New Repository)
#    Name it: longcat-video-serverless (or whatever you prefer)
#    Make it PRIVATE (model weights aren't in the repo, but still good practice)

# 2. From your project directory:
cd /path/to/longcat_video_app
git remote add origin https://github.com/YOUR_USERNAME/longcat-video-serverless.git
git branch -M main
git push -u origin main
```

> 💡 The `.gitignore` ensures model weights (67GB) are NOT pushed to GitHub. They're downloaded during Docker build.

---

## 3. Build the Docker Image

The Docker image is large (~70+ GB) because it includes model weights. Choose one option:

### Option A: Docker Hub

**Best if you have a machine with Docker + good internet.**

#### Step 1: Clone the repo on your build machine

```bash
git clone https://github.com/YOUR_USERNAME/longcat-video-serverless.git
cd longcat-video-serverless
```

#### Step 2: Build the image

The Dockerfile automatically downloads model weights from HuggingFace during build.

```bash
# Build (this will take 30-60 minutes — it downloads ~67GB of model weights)
DOCKER_BUILDKIT=1 docker build -t longcat-video:latest .
```

> ⏱ **Estimated time:** 30-60 min (depending on internet speed)
> 💾 **Disk needed:** ~150 GB free space

#### Step 3: Tag and push to Docker Hub

```bash
# Login to Docker Hub
docker login

# Tag the image
docker tag longcat-video:latest YOUR_DOCKERHUB_USERNAME/longcat-video:latest

# Push (this will take a while — the image is ~70+ GB)
docker push YOUR_DOCKERHUB_USERNAME/longcat-video:latest
```

> ⏱ **Push time:** 1-3 hours depending on upload speed

#### Step 4: Note your image name

Your image name for RunPod will be:
```
YOUR_DOCKERHUB_USERNAME/longcat-video:latest
```

---

### Option B: RunPod Build System

**Best if you don't want to build locally. RunPod can build from a GitHub repo or Dockerfile.**

#### Step 1: Go to RunPod Console

1. Log in at [runpod.io/console](https://www.runpod.io/console)
2. Navigate to **Serverless** → **Endpoints**

#### Step 2: Create a new Template

1. Go to **Serverless** → **Custom Templates**
2. Click **"New Template"**
3. Choose **"Build from GitHub"**
4. Connect your GitHub account
5. Select your `longcat-video-serverless` repository
6. Set **Dockerfile path**: `Dockerfile`
7. Click **Build**

> ⏱ RunPod builds may take 45-90 minutes (they also download model weights during build)

---

## 4. Create a RunPod Serverless Endpoint

1. Go to [runpod.io/console/serverless](https://www.runpod.io/console/serverless)
2. Click **"+ New Endpoint"**
3. Configure:

| Setting | Value |
|---------|-------|
| **Endpoint Name** | `longcat-video-lipsync` |
| **Docker Image** | `YOUR_DOCKERHUB_USERNAME/longcat-video:latest` |
| **GPU Type** | `A100 80GB` |
| **Container Disk** | `100 GB` |
| **Volume Disk** | `0 GB` (not needed — weights are in the image) |
| **Min Workers** | `0` (scale to zero — pay only when used) |
| **Max Workers** | `1` (or more if you need parallel processing) |

4. Under **Advanced**:

| Setting | Value |
|---------|-------|
| **Execution Timeout** | `600` seconds (10 min) |
| **Idle Timeout** | `60` seconds |
| **FlashBoot** | `Enabled` (faster cold starts) |

5. Click **"Create Endpoint"**

---

## 5. Configure the Endpoint

#### Recommended Settings

- **GPU: A100 80GB** — Required for this model. Smaller GPUs will OOM.
- **Min Workers: 0** — No cost when idle.
- **Max Workers: 1-3** — Scale based on your usage. Each worker = 1 concurrent video.
- **Execution Timeout: 600s** — Video generation takes 2-8 minutes depending on settings.
- **Idle Timeout: 60s** — Worker stays warm for 60s after last request (faster follow-up calls).
- **FlashBoot: ON** — RunPod caches the container for faster cold starts.

#### Cold Start Time

- **First request (no FlashBoot):** ~3-5 minutes (loading model into GPU)
- **First request (FlashBoot):** ~1-2 minutes
- **Subsequent requests (warm):** ~2-5 minutes (actual generation time)

---

## 6. Test Your Endpoint

Once the endpoint is created, you'll get an **Endpoint ID** (looks like `abc123xyz`).

#### Get your RunPod API Key

1. Go to [runpod.io/console/user/settings](https://www.runpod.io/console/user/settings)
2. Under **API Keys**, create a new key
3. Copy it — you'll need it for requests

#### Quick Test with cURL

```bash
# Replace YOUR_ENDPOINT_ID and YOUR_API_KEY
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image": "https://upload.wikimedia.org/wikipedia/commons/a/a7/Camponotus_flavomarginatus_ant.jpg",
      "audio": "https://www2.cs.uic.edu/~i101/SoundFiles/BabyElephantWalk60.wav",
      "resolution": "480p",
      "continuation_segments": 1
    }
  }'
```

> ⚠️ Use `runsync` for synchronous requests (waits for result, up to timeout).
> Use `run` for async requests (returns a job ID, poll for result).

#### Async Request (Recommended for Production)

```bash
# Submit job
RESPONSE=$(curl -s -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/run" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Sandro_Botticelli_-_Idealized_Portrait_of_a_Lady_%28Portrait_of_Simonetta_Vespucci_as_Nymph%29_-_Google_Art_Project.jpg/960px-Sandro_Botticelli_-_Idealized_Portrait_of_a_Lady_%28Portrait_of_Simonetta_Vespucci_as_Nymph%29_-_Google_Art_Project.jpg",
      "audio": "https://example.com/speech.wav",
      "resolution": "480p"
    }
  }')

# Get the job ID
JOB_ID=$(echo $RESPONSE | jq -r '.id')
echo "Job ID: $JOB_ID"

# Poll for status
curl -s "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/status/$JOB_ID" \
  -H "Authorization: Bearer YOUR_API_KEY" | jq '.status'
```

#### Python Test Script

```python
import runpod
import base64
import time

# Setup
runpod.api_key = "YOUR_API_KEY"
endpoint = runpod.Endpoint("YOUR_ENDPOINT_ID")

# Option 1: Using URLs (easiest)
result = endpoint.run_sync({
    "input": {
        "image": "https://framerusercontent.com/images/JtU1L47El99MQu8ojm88XQefo.png",
        "audio": "https://example.com/speech.wav",
        "resolution": "480p",
        "continuation_segments": 2
    }
}, timeout=600)

# Option 2: Using base64
with open("portrait.jpg", "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode()
with open("speech.wav", "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

result = endpoint.run_sync({
    "input": {
        "image": image_b64,
        "audio": audio_b64,
        "resolution": "480p"
    }
}, timeout=600)

# Save the output video
if "error" not in result:
    video_bytes = base64.b64decode(result["video_base64"])
    with open("output.mp4", "wb") as f:
        f.write(video_bytes)
    print(f"✅ Video saved! Duration: {result['duration_sec']}s, Resolution: {result['resolution']}")
else:
    print(f"❌ Error: {result['error']}")
```

---

## 7. API Reference

#### Request Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `image` | string | ✅ | — | Base64-encoded image or HTTPS URL |
| `audio` | string | ✅ | — | Base64-encoded audio or HTTPS URL |
| `resolution` | string | ❌ | `"480p"` | Output resolution: `"480p"`, `"720p"`, `"1080p"` |
| `aspect_ratio` | string | ❌ | `"16:9"` | `"16:9"` (landscape) or `"9:16"` (portrait) |
| `mode` | string | ❌ | `"ai2v"` | `"ai2v"` (image+audio) or `"at2v"` (text+audio) |
| `num_inference_steps` | int | ❌ | `30` | Denoising steps |
| `guidance_scale` | float | ❌ | `5.0` | Text guidance |
| `audio_guidance_scale` | float | ❌ | `3.0` | Audio guidance |
| `seed` | int | ❌ | `42` | Random seed |
| `continuation_segments` | int | ❌ | `2` | Number of continuation segments |
| `prompt` | string | ❌ | `""` | Text prompt |
| `neg_prompt` | string | ❌ | `""` | Negative prompt |

#### Response Schema (Success)

```json
{
  "video_base64": "<base64 MP4>",
  "duration_sec": 6.4,
  "resolution": "832x480"
}
```

#### Response Schema (Error)

```json
{
  "error": "Error message",
  "traceback": "Full stack trace"
}
```

---

## 8. Troubleshooting

#### ❌ "CUDA out of memory"
- **Cause:** GPU doesn't have enough VRAM
- **Fix:** Use `A100 80GB`. If using 480p, try reducing `continuation_segments` to 1

#### ❌ Cold start takes too long
- **Cause:** Model loading takes 2-5 min on first request
- **Fix:** Enable **FlashBoot** in endpoint settings. Set **Idle Timeout** higher (e.g., 300s) to keep workers warm longer

#### ❌ "Execution timeout"
- **Cause:** Video generation exceeded the timeout limit
- **Fix:** Increase **Execution Timeout** to 900s. Reduce `continuation_segments` or `num_inference_steps`

#### ❌ "Worker failed to start"
- **Cause:** Docker image issue or missing dependencies
- **Fix:** Check logs in RunPod console → Endpoint → Logs tab. Rebuild the Docker image

#### ❌ Empty or corrupted video output
- **Cause:** Usually an audio format issue
- **Fix:** Use `.wav` format audio. Ensure the audio file is valid and not empty

#### ❌ Docker build fails at weight download
- **Cause:** HuggingFace download interrupted or rate-limited
- **Fix:** Retry the build. If persistent, set `HF_TOKEN` build arg for authenticated access

#### 💡 Cost Optimization Tips

- Use **Min Workers: 0** to avoid charges when idle
- Use **480p** resolution (cheaper than 720p — less compute time)
- Use fewer `continuation_segments` for shorter videos
- Use **Spot/Interruptible** GPUs for non-critical workloads (cheaper but may be preempted)

#### 💡 Estimated Costs (A100 80GB)

| Resolution | Segments | ~Generation Time | ~Cost per Video |
|-----------|----------|------------------|-----------------|
| 480p | 1 | ~2 min | ~$0.05 |
| 480p | 2 | ~3-4 min | ~$0.10 |
| 480p | 3 | ~5-6 min | ~$0.15 |
| 720p | 2 | ~6-8 min | ~$0.20 |

*Costs based on RunPod A100 80GB at ~$1.64/hr (March 2026 pricing). Actual costs may vary.*
