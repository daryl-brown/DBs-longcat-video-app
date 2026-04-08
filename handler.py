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
      "mode":        "ai2v" | "at2v"  (default "ai2v"),
      "num_inference_steps": 50,
      "text_guidance_scale": 4.0,
      "audio_guidance_scale": 4.0,
      "seed":        42,
      "num_segments": 1
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
import math
import base64
import tempfile
import traceback
import time
import requests
import numpy as np
from pathlib import Path

import runpod

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APP_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(APP_DIR, "repo")

# Use network volume if mounted (RunPod always mounts at /runpod-volume)
_VOLUME_DIR = "/runpod-volume"
WEIGHTS_DIR    = _VOLUME_DIR if os.path.isdir(_VOLUME_DIR) else os.path.join(REPO_DIR, "weights")
BASE_MODEL_DIR  = os.path.join(WEIGHTS_DIR, "LongCat-Video")
AVATAR_MODEL_DIR = os.path.join(WEIGHTS_DIR, "LongCat-Video-Avatar")
OUTPUT_DIR     = os.path.join(APP_DIR, "outputs")
AUDIO_TEMP_DIR = os.path.join(APP_DIR, "audio_temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

sys.path.insert(0, REPO_DIR)

# ---------------------------------------------------------------------------
# Globals — loaded once, reused across requests
# ---------------------------------------------------------------------------
_pipeline        = None
_vocal_separator = None
_local_rank      = 0

SAVE_FPS     = 16
AUDIO_STRIDE = 2
NUM_FRAMES   = 93
NUM_COND_FRAMES = 13

NEG_PROMPT = (
    "Close-up, Bright tones, overexposed, static, blurred details, subtitles, "
    "style, works, paintings, images, static, overall gray, worst quality, low quality, "
    "JPEG compression residue, ugly, incomplete, extra fingers, poorly drawn hands, "
    "poorly drawn faces, deformed, disfigured, misshapen limbs, fused fingers, "
    "still picture, messy background, three legs, many people in the background, walking backwards"
)


# ---------------------------------------------------------------------------
# Weight download
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Pipeline load
# ---------------------------------------------------------------------------
def _load_pipeline():
    """Load model pipeline into GPU — called once at cold start."""
    global _pipeline, _vocal_separator, _local_rank

    if _pipeline is not None:
        return

    _ensure_weights()

    import torch
    import torch.distributed as dist
    from transformers import AutoTokenizer, UMT5EncoderModel, Wav2Vec2FeatureExtractor
    from longcat_video.modules.scheduling_flow_match_euler_discrete import FlowMatchEulerDiscreteScheduler
    from longcat_video.modules.autoencoder_kl_wan import AutoencoderKLWan
    from longcat_video.modules.avatar.longcat_video_dit_avatar import LongCatVideoAvatarTransformer3DModel
    from longcat_video.pipeline_longcat_video_avatar import LongCatVideoAvatarPipeline
    from longcat_video.context_parallel import context_parallel_util
    from longcat_video.audio_process.wav2vec2 import Wav2Vec2ModelWrapper
    from audio_separator.separator import Separator

    _local_rank = 0 if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16

    # Single-process distributed init (required by context_parallel internals)
    if not dist.is_initialized():
        os.environ.setdefault("RANK", "0")
        os.environ.setdefault("WORLD_SIZE", "1")
        os.environ.setdefault("MASTER_ADDR", "localhost")
        os.environ.setdefault("MASTER_PORT", "29500")
        dist.init_process_group(backend="nccl", init_method="env://")

    context_parallel_util.init_context_parallel(
        context_parallel_size=1, global_rank=0, world_size=1
    )
    cp_size    = context_parallel_util.get_cp_size()
    cp_split_hw = context_parallel_util.get_optimal_split(cp_size)

    print("[handler] Loading tokenizer …")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR, subfolder="tokenizer")

    print("[handler] Loading text encoder …")
    text_encoder = UMT5EncoderModel.from_pretrained(
        BASE_MODEL_DIR, subfolder="text_encoder", torch_dtype=dtype
    )

    print("[handler] Loading VAE …")
    vae = AutoencoderKLWan.from_pretrained(
        BASE_MODEL_DIR, subfolder="vae", torch_dtype=dtype
    )

    print("[handler] Loading scheduler …")
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
        BASE_MODEL_DIR, subfolder="scheduler"
    )

    print("[handler] Loading transformer (dit) …")
    dit = LongCatVideoAvatarTransformer3DModel.from_pretrained(
        AVATAR_MODEL_DIR, subfolder="avatar_single",
        cp_split_hw=cp_split_hw, torch_dtype=dtype
    )

    print("[handler] Loading Wav2Vec2 …")
    wav2vec_path = os.path.join(AVATAR_MODEL_DIR, "chinese-wav2vec2-base")
    audio_encoder = Wav2Vec2ModelWrapper(wav2vec_path).to(_local_rank)
    audio_encoder.feature_extractor._freeze_parameters()
    wav2vec_feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(
        wav2vec_path, local_files_only=True
    )

    print("[handler] Building pipeline …")
    _pipeline = LongCatVideoAvatarPipeline(
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        vae=vae,
        scheduler=scheduler,
        dit=dit,
        audio_encoder=audio_encoder,
        wav2vec_feature_extractor=wav2vec_feature_extractor,
    )
    _pipeline.to(_local_rank)

    print("[handler] Loading vocal separator …")
    vocal_separator_model = os.path.join(AVATAR_MODEL_DIR, "vocal_separator", "Kim_Vocal_2.onnx")
    vocals_dir = Path(AUDIO_TEMP_DIR) / "vocals"
    os.makedirs(vocals_dir, exist_ok=True)
    _vocal_separator = Separator(
        output_dir=vocals_dir,
        output_single_stem="vocals",
        model_file_dir=os.path.dirname(vocal_separator_model),
    )
    _vocal_separator.load_model(os.path.basename(vocal_separator_model))

    print("[handler] Pipeline ready ✔")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
    """Separate vocal track and return path to vocal file."""
    import librosa, soundfile as sf
    outputs = _vocal_separator.separate(audio_path)
    if not outputs:
        return audio_path  # fallback: use raw audio
    vocals_dir = Path(AUDIO_TEMP_DIR) / "vocals"
    vocal_file = vocals_dir / outputs[0]
    target = os.path.join(AUDIO_TEMP_DIR, f"vocal_{int(time.time())}.wav")
    os.rename(str(vocal_file), target)
    return target


def _build_audio_emb(full_audio_emb, segment_idx, device):
    """Build windowed audio embedding for a given segment."""
    import torch
    indices = torch.arange(2 * 2 + 1) - 2  # [-2, -1, 0, 1, 2]
    audio_start_idx = segment_idx * AUDIO_STRIDE * (NUM_FRAMES - NUM_COND_FRAMES)
    audio_end_idx   = audio_start_idx + AUDIO_STRIDE * NUM_FRAMES
    center_indices  = (
        torch.arange(audio_start_idx, audio_end_idx, AUDIO_STRIDE).unsqueeze(1)
        + indices.unsqueeze(0)
    )
    center_indices = torch.clamp(center_indices, min=0, max=full_audio_emb.shape[0] - 1)
    return full_audio_emb[center_indices][None, ...].to(device)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handler(event):
    """RunPod serverless handler."""
    try:
        _load_pipeline()

        data = event.get("input", {})

        # Warmup — pipeline loaded, nothing to generate
        if data.get("warmup"):
            return {"status": "warm", "message": "Worker is ready"}

        import torch
        import librosa
        import PIL.Image
        from longcat_video.audio_process.torch_utils import save_video_ffmpeg

        # --- Decode inputs --------------------------------------------------
        image_path = _decode_input(data, "image", ".png")
        audio_path = _decode_input(data, "audio", ".wav")

        # --- Parameters -----------------------------------------------------
        resolution    = data.get("resolution", "480p")
        mode          = data.get("mode", "ai2v")
        steps         = int(data.get("num_inference_steps", 50))
        text_guidance = float(data.get("text_guidance_scale", 4.0))
        audio_guidance = float(data.get("audio_guidance_scale", 4.0))
        seed          = int(data.get("seed", 42))
        num_segments  = max(1, int(data.get("num_segments", 1)))
        prompt        = data.get("prompt", "")
        neg_prompt    = data.get("neg_prompt", NEG_PROMPT)

        aspect = data.get("aspect_ratio", "16:9")
        if resolution == "720p":
            h, w = (768, 1280) if aspect == "16:9" else (1280, 768)
        else:
            h, w = (480, 832) if aspect == "16:9" else (832, 480)

        generator = torch.Generator(device=_local_rank).manual_seed(seed)

        # --- Vocal separation -----------------------------------------------
        vocal_path  = _extract_vocal(audio_path)
        speech_array, sr = librosa.load(vocal_path, sr=16000)

        # Pad audio to cover full generation duration
        generate_duration = (
            NUM_FRAMES / SAVE_FPS
            + (num_segments - 1) * (NUM_FRAMES - NUM_COND_FRAMES) / SAVE_FPS
        )
        source_duration = len(speech_array) / sr
        pad_samples = math.ceil((generate_duration - source_duration) * sr)
        if pad_samples > 0:
            speech_array = np.append(speech_array, [0.0] * pad_samples)

        # --- Audio embedding ------------------------------------------------
        full_audio_emb = _pipeline.get_audio_embedding(
            speech_array, fps=SAVE_FPS * AUDIO_STRIDE,
            device=_local_rank, sample_rate=sr
        )
        audio_emb = _build_audio_emb(full_audio_emb, segment_idx=0, device=_local_rank)

        # --- First segment --------------------------------------------------
        image = PIL.Image.open(image_path).convert("RGB")

        if mode == "at2v":
            output, latent = _pipeline.generate_at2v(
                prompt=prompt, negative_prompt=neg_prompt,
                height=h, width=w, num_frames=NUM_FRAMES,
                num_inference_steps=steps,
                text_guidance_scale=text_guidance,
                audio_guidance_scale=audio_guidance,
                generator=generator, output_type="both",
                audio_emb=audio_emb,
            )
        else:
            output, latent = _pipeline.generate_ai2v(
                image=image,
                prompt=prompt, negative_prompt=neg_prompt,
                resolution=resolution, num_frames=NUM_FRAMES,
                num_inference_steps=steps,
                text_guidance_scale=text_guidance,
                audio_guidance_scale=audio_guidance,
                generator=generator, output_type="both",
                audio_emb=audio_emb,
            )

        output = output[0]
        video  = [(output[i] * 255).astype(np.uint8) for i in range(output.shape[0])]
        video  = [PIL.Image.fromarray(img) for img in video]
        ref_latent = latent[:, :, :1].clone()
        all_frames = list(video)

        # --- Continuation segments ------------------------------------------
        for seg_i in range(1, num_segments):
            audio_emb = _build_audio_emb(full_audio_emb, segment_idx=seg_i, device=_local_rank)

            output, latent = _pipeline.generate_avc(
                video=video, video_latent=latent,
                prompt=prompt, negative_prompt=neg_prompt,
                height=h, width=w,
                num_frames=NUM_FRAMES, num_cond_frames=NUM_COND_FRAMES,
                num_inference_steps=steps,
                text_guidance_scale=text_guidance,
                audio_guidance_scale=audio_guidance,
                generator=generator, output_type="both",
                use_kv_cache=True, offload_kv_cache=False, enhance_hf=True,
                audio_emb=audio_emb,
                ref_latent=ref_latent, ref_img_index=10, mask_frame_range=3,
            )
            output = output[0]
            video  = [(output[i] * 255).astype(np.uint8) for i in range(output.shape[0])]
            video  = [PIL.Image.fromarray(img) for img in video]
            all_frames.extend(video[NUM_COND_FRAMES:])

        # --- Save & encode --------------------------------------------------
        ts       = int(time.time())
        out_stem = os.path.join(OUTPUT_DIR, f"result_{ts}")
        out_path = out_stem + ".mp4"

        output_tensor = torch.from_numpy(np.array(all_frames))
        save_video_ffmpeg(output_tensor, out_stem, vocal_path, fps=SAVE_FPS, quality=5)

        with open(out_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")

        for p in [image_path, audio_path, vocal_path]:
            try:
                os.remove(p)
            except OSError:
                pass

        return {
            "video_base64": video_b64,
            "duration_sec": round(len(all_frames) / SAVE_FPS, 2),
            "resolution":   f"{w}x{h}",
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
