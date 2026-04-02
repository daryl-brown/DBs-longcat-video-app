#!/usr/bin/env python3
"""
RunPod Serverless Handler — LongCat-Video Avatar

Accepts:
  {
    "input": {
      "image":       <base64-encoded image OR URL>,
      "audio":       <base64-encoded audio OR URL>,
      "prompt":      "optional text prompt",
      "neg_prompt":  "optional negative prompt",
      "resolution":  "480p" | "720p"  (default "480p"),
      "aspect_ratio": "16:9" | "9:16" (default "16:9"),
      "mode":        "ai2v" | "at2v"  (default "ai2v"),
      "num_inference_steps": 30,
      "guidance_scale": 5.0,
      "audio_guidance_scale": 3.0,
      "seed":        42,
      "continuation_segments": 2
    }
  }

Returns:
  {
    "video_base64": "<base64 mp4>",
    "duration_sec": 6.4,
    "resolution":   "832x480"
  }
"""

import os
import sys
import base64
import tempfile
import traceback
import time
import io
import requests

import runpod

# ---------------------------------------------------------------------------
# Paths — same layout as the Gradio app
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(APP_DIR, "repo")
WEIGHTS_DIR = os.path.join(REPO_DIR, "weights")
BASE_MODEL_DIR = os.path.join(WEIGHTS_DIR, "LongCat-Video")
AVATAR_MODEL_DIR = os.path.join(WEIGHTS_DIR, "LongCat-Video-Avatar")
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")
AUDIO_TEMP_DIR = os.path.join(APP_DIR, "audio_temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

sys.path.insert(0, REPO_DIR)

# ---------------------------------------------------------------------------
# Global pipeline (loaded once, reused across requests)
# ---------------------------------------------------------------------------
_pipeline = None
_vocal_separator = None
_device = None


def _ensure_weights():
    """Download model weights from HuggingFace if not already present."""
    from huggingface_hub import snapshot_download

    if not os.path.isdir(os.path.join(BASE_MODEL_DIR, "tokenizer")):
        print("[handler] Downloading LongCat-Video base model weights …")
        snapshot_download(
            "meituan-longcat/LongCat-Video",
            local_dir=BASE_MODEL_DIR,
            allow_patterns=["tokenizer/*", "text_encoder/*", "vae/*", "scheduler/*"],
        )

    if not os.path.isdir(os.path.join(AVATAR_MODEL_DIR, "avatar_single")):
        print("[handler] Downloading LongCat-Video-Avatar model weights …")
        snapshot_download(
            "meituan-longcat/LongCat-Video-Avatar",
            local_dir=AVATAR_MODEL_DIR,
            allow_patterns=["avatar_single/*", "chinese-wav2vec2-base/*", "vocal_separator/*"],
        )


def _load_pipeline():
    """Load model pipeline into GPU — called once at cold start."""
    global _pipeline, _vocal_separator, _device
    if _pipeline is not None:
        return

    _ensure_weights()

    import torch
    from transformers import AutoTokenizer, Wav2Vec2FeatureExtractor
    from diffusers import load_image  # noqa: F401
    from longcat_video.modules.scheduler_flow_match_euler import FlowMatchEulerDiscreteScheduler
    from longcat_video.modules.autoencoder_kl_wan import AutoencoderKLWan
    from longcat_video.modules.model_avatar import LongCatVideoAvatarTransformer3DModel
    from longcat_video.pipeline_longcat_video_avatar import LongCatVideoAvatarPipeline
    from longcat_video.context_parallel.context_parallel_util import setup_cp
    from longcat_video.audio_process.wav2vec2 import Wav2Vec2ModelWrapper
    from audio_separator.separator import Separator

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16

    print("[handler] Loading tokenizer …")
    tokenizer = AutoTokenizer.from_pretrained(os.path.join(BASE_MODEL_DIR, "tokenizer"))

    print("[handler] Loading text encoder …")
    from transformers import UMT5EncoderModel
    text_encoder = UMT5EncoderModel.from_pretrained(
        os.path.join(BASE_MODEL_DIR, "text_encoder"), torch_dtype=dtype
    )

    print("[handler] Loading VAE …")
    vae = AutoencoderKLWan.from_pretrained(
        os.path.join(BASE_MODEL_DIR, "vae"), torch_dtype=torch.float32
    )

    print("[handler] Loading scheduler …")
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
        os.path.join(BASE_MODEL_DIR, "scheduler")
    )

    print("[handler] Loading transformer …")
    transformer = LongCatVideoAvatarTransformer3DModel.from_pretrained(
        os.path.join(AVATAR_MODEL_DIR, "avatar_single"), torch_dtype=dtype
    )

    print("[handler] Building pipeline …")
    _pipeline = LongCatVideoAvatarPipeline(
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        vae=vae,
        transformer=transformer,
        scheduler=scheduler,
    )
    _pipeline = _pipeline.to(_device, dtype=dtype)

    print("[handler] Loading Wav2Vec2 …")
    wav2vec_path = os.path.join(AVATAR_MODEL_DIR, "chinese-wav2vec2-base")
    audio_processor = Wav2Vec2FeatureExtractor.from_pretrained(wav2vec_path)
    audio_encoder = Wav2Vec2ModelWrapper.from_pretrained(wav2vec_path)
    _pipeline.audio_encoder = audio_encoder.to(_device, dtype=dtype)
    _pipeline.audio_processor = audio_processor

    setup_cp(cp_size=1)

    print("[handler] Loading vocal separator …")
    _vocal_separator = Separator(
        output_dir=AUDIO_TEMP_DIR,
        model_file_dir=os.path.join(AVATAR_MODEL_DIR, "vocal_separator"),
    )
    _vocal_separator.load_model("UVR-MDX-NET-Inst_HQ_3.onnx")

    print("[handler] Pipeline ready ✔")


def _decode_input(data, key, suffix):
    """Decode a base64 string or download a URL to a temp file."""
    value = data.get(key)
    if value is None:
        raise ValueError(f"Missing required input: {key}")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=AUDIO_TEMP_DIR)
    if value.startswith(("http://", "https://")):
        r = requests.get(value, timeout=120)
        r.raise_for_status()
        tmp.write(r.content)
    else:
        tmp.write(base64.b64decode(value))
    tmp.close()
    return tmp.name


def _extract_vocal(audio_path):
    """Extract vocal track from audio."""
    results = _vocal_separator.separate(audio_path)
    vocal_path = None
    for r in results:
        full = os.path.join(AUDIO_TEMP_DIR, r)
        if "vocal" in r.lower() or "vocals" in r.lower():
            vocal_path = full
    return vocal_path or audio_path


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
RES_MAP = {
    "480p": {"16:9": (832, 480), "9:16": (480, 832)},
    "720p": {"16:9": (1280, 720), "9:16": (720, 1280)},
    "1080p": {"16:9": (1920, 1080), "9:16": (1080, 1920)},
}


def handler(event):
    """RunPod serverless handler."""
    try:
        _load_pipeline()

        data = event.get("input", {})

        # Warmup request — weights downloaded, pipeline loaded, nothing to generate
        if data.get("warmup"):
            return {"status": "warm", "message": "Worker is ready"}

        # --- Decode inputs ------------------------------------------------
        image_path = _decode_input(data, "image", ".png")
        audio_path = _decode_input(data, "audio", ".wav")

        # --- Parameters ---------------------------------------------------
        resolution = data.get("resolution", "480p")
        aspect = data.get("aspect_ratio", "16:9")
        mode = data.get("mode", "ai2v")
        steps = int(data.get("num_inference_steps", 30))
        guidance = float(data.get("guidance_scale", 5.0))
        audio_guidance = float(data.get("audio_guidance_scale", 3.0))
        seed = int(data.get("seed", 42))
        continuation_segments = int(data.get("continuation_segments", 2))
        prompt = data.get("prompt", "")
        neg_prompt = data.get("neg_prompt", "")

        w, h = RES_MAP.get(resolution, RES_MAP["480p"]).get(aspect, (832, 480))

        # --- Generate video -----------------------------------------------
        import torch
        import librosa
        import numpy as np
        from PIL import Image
        from longcat_video.utils.utils import save_video_ffmpeg

        vocal_path = _extract_vocal(audio_path)
        audio_data, sr = librosa.load(vocal_path, sr=16000)

        image = Image.open(image_path).convert("RGB")

        generator = torch.Generator(device=_device).manual_seed(seed)

        # Get audio embedding
        audio_emb, audio_len_in_s = _pipeline.get_audio_embedding(
            audio_data, sr, duration=None
        )

        # First segment
        num_frames = 81
        output = _pipeline(
            prompt=prompt,
            negative_prompt=neg_prompt,
            image=image,
            audio_emb=audio_emb,
            num_frames=num_frames,
            height=h,
            width=w,
            num_inference_steps=steps,
            guidance_scale=guidance,
            audio_guidance_scale=audio_guidance,
            generator=generator,
            mode=mode,
        )
        video = output.frames[0]

        # Continuation segments
        for seg_i in range(continuation_segments):
            seg_output = _pipeline.generate_avc(
                prompt=prompt,
                negative_prompt=neg_prompt,
                audio_emb=audio_emb,
                num_frames=num_frames,
                height=h,
                width=w,
                num_inference_steps=steps,
                guidance_scale=guidance,
                audio_guidance_scale=audio_guidance,
                generator=generator,
                previous_video=video,
            )
            # Append new frames (skip overlap)
            new_frames = seg_output.frames[0]
            video = video + new_frames[1:]

        # Save video
        ts = int(time.time())
        out_path = os.path.join(OUTPUT_DIR, f"result_{ts}.mp4")
        save_video_ffmpeg(video, out_path, audio_path=vocal_path, fps=16)

        # Encode result
        with open(out_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")

        # Cleanup temp files
        for p in [image_path, audio_path]:
            try:
                os.remove(p)
            except OSError:
                pass

        return {
            "video_base64": video_b64,
            "duration_sec": round(len(video) / 16.0, 2),
            "resolution": f"{w}x{h}",
        }

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e), "traceback": traceback.format_exc()}


# ---------------------------------------------------------------------------
# RunPod entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("[handler] Starting RunPod serverless worker …")
    runpod.serverless.start({"handler": handler})
