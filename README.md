# 🎬 LongCat-Video Avatar — Lipsync Video Generator

**Generate realistic talking-head / lipsync videos from a single image and audio file.**

This project wraps the [LongCat-Video-Avatar](https://github.com/meituan-longcat/LongCat-Video) model into a production-ready Docker image deployable on **RunPod Serverless** — so you only pay when generating videos.

---

### What It Does

Given:
- 📷 A portrait / avatar image
- 🎤 An audio file (speech, singing, etc.)

It produces:
- 🎥 A lipsync video where the person in the image speaks/sings along with the audio

Supports **480p** and **720p** output, landscape (16:9) or portrait (9:16) aspect ratios, and multi-segment video continuation for longer clips.

---

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | A100 40GB | **A100 80GB** |
| VRAM | 40 GB | 80 GB |
| System RAM | 32 GB | 64 GB |
| Disk (Docker image) | 80 GB | 100 GB |

> ⚠️ This model requires significant GPU memory. An **NVIDIA A100 80GB** is recommended for reliable 480p/720p generation.

---

### Quick Start (RunPod Serverless)

1. **Push this repo to GitHub** (see [GITHUB_PUSH_COMMANDS.txt](GITHUB_PUSH_COMMANDS.txt))
2. **Build the Docker image** (via Docker Hub or RunPod — see [RUNPOD_SERVERLESS_SETUP.md](RUNPOD_SERVERLESS_SETUP.md))
3. **Create a RunPod Serverless endpoint** pointing to your Docker image
4. **Send API requests** to generate videos

For detailed step-by-step instructions, see **[RUNPOD_SERVERLESS_SETUP.md](RUNPOD_SERVERLESS_SETUP.md)**.

---

### Project Structure

```
longcat_video_app/
├── handler.py              # RunPod Serverless API handler
├── app.py                  # Gradio web UI (alternative)
├── Dockerfile              # Multi-stage build (downloads weights from HuggingFace)
├── requirements.txt        # Python dependencies
├── docker-compose.yml      # Local testing
├── repo/                   # LongCat-Video source code (no weights)
│   ├── longcat_video/      # Core model code
│   └── weights/            # ← Git-ignored; downloaded during Docker build
├── RUNPOD_SERVERLESS_SETUP.md
├── GITHUB_PUSH_COMMANDS.txt
└── README.md               # This file
```

---

### API Usage

#### Request Format

```json
{
  "input": {
    "image": "<base64-encoded image OR https:// URL>",
    "audio": "<base64-encoded audio OR https:// URL>",
    "resolution": "480p",
    "aspect_ratio": "16:9",
    "mode": "ai2v",
    "num_inference_steps": 30,
    "guidance_scale": 5.0,
    "audio_guidance_scale": 3.0,
    "seed": 42,
    "continuation_segments": 2
  }
}
```

#### Response Format

```json
{
  "output": {
    "video_base64": "<base64-encoded MP4 video>",
    "duration_sec": 6.4,
    "resolution": "832x480"
  }
}
```

#### Python Example

```python
import runpod
import base64

runpod.api_key = "YOUR_RUNPOD_API_KEY"
endpoint = runpod.Endpoint("YOUR_ENDPOINT_ID")

# Using URLs (easiest)
result = endpoint.run_sync({
    "input": {
        "image": "https://images.pexels.com/photos/20000981/pexels-photo-20000981/free-photo-of-portrait-of-an-african-man.jpeg",
        "audio": "https://example.com/speech.wav",
        "resolution": "480p",
        "continuation_segments": 2
    }
}, timeout=600)

# Save the video
with open("output.mp4", "wb") as f:
    f.write(base64.b64decode(result["output"]["video_base64"]))
```

#### cURL Example

```bash
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer YOUR_RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image": "https://images.pexels.com/photos/30320071/pexels-photo-30320071/free-photo-of-black-and-white-portrait-of-a-smiling-woman.jpeg",
      "audio": "https://example.com/speech.wav",
      "resolution": "480p"
    }
  }'
```

---

### Input Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `image` | string | *required* | Base64 image or URL |
| `audio` | string | *required* | Base64 audio or URL |
| `resolution` | string | `"480p"` | `"480p"`, `"720p"`, or `"1080p"` |
| `aspect_ratio` | string | `"16:9"` | `"16:9"` or `"9:16"` |
| `mode` | string | `"ai2v"` | `"ai2v"` (audio+image) or `"at2v"` (audio+text) |
| `num_inference_steps` | int | `30` | Denoising steps (higher = better quality, slower) |
| `guidance_scale` | float | `5.0` | Text guidance strength |
| `audio_guidance_scale` | float | `3.0` | Audio guidance strength |
| `seed` | int | `42` | Random seed for reproducibility |
| `continuation_segments` | int | `2` | Number of video continuation segments |
| `prompt` | string | `""` | Optional text prompt |
| `neg_prompt` | string | `""` | Optional negative prompt |

---

### Deployment Options

| Method | Best For |
|--------|----------|
| **RunPod Serverless** | Production — pay only per request |
| **RunPod Pod** | Development — persistent GPU instance |
| **Local Docker** | Testing with `docker-compose` |

---

### Credits

- **LongCat-Video** by [Meituan LongCat Team](https://github.com/meituan-longcat/LongCat-Video)
- Model weights hosted on [HuggingFace](https://huggingface.co/meituan-longcat)
- Serverless deployment powered by [RunPod](https://runpod.io)

### License

This deployment wrapper follows the license terms of the original LongCat-Video project. See [repo/LICENSE](repo/LICENSE) for the model license.
