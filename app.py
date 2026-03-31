#!/usr/bin/env python3
"""
LongCat-Video Avatar — Gradio Web Interface
Audio-driven portrait/avatar lipsync video generation.
"""

import os
import sys
import json
import time
import math
import random
import shutil
import tempfile
import traceback
import subprocess
from pathlib import Path

import numpy as np
import gradio as gr

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repo")
WEIGHTS_DIR = os.path.join(REPO_DIR, "weights")
BASE_MODEL_DIR = os.path.join(WEIGHTS_DIR, "LongCat-Video")
AVATAR_MODEL_DIR = os.path.join(WEIGHTS_DIR, "LongCat-Video-Avatar")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
AUDIO_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

# Add repo to path so longcat_video package is importable
sys.path.insert(0, REPO_DIR)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_pipeline = None
_vocal_separator = None
_device = None

DEFAULT_NEGATIVE_PROMPT = (
    "Close-up, Bright tones, overexposed, static, blurred details, subtitles, "
    "style, works, paintings, images, static, overall gray, worst quality, "
    "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
    "poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, "
    "fused fingers, still picture, messy background, three legs, "
    "many people in the background, walking backwards"
)

DEFAULT_PROMPT = (
    "A person stands in a well-lit environment, speaking naturally with expressive "
    "facial movements and subtle body gestures. The scene is captured in high quality "
    "with clear details and natural lighting."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def generate_uid():
    return f"{int(time.time())%1000000}_{random.randint(100000,999999)}"


def check_gpu():
    """Return (available: bool, info: str)."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_mem / 1024**3
            return True, f"✅ GPU: {name} ({vram:.1f} GB VRAM)"
        return False, "⚠️ No GPU detected — inference requires CUDA GPU"
    except Exception as e:
        return False, f"⚠️ GPU check failed: {e}"


def check_models():
    """Check if model weights are downloaded."""
    needed = {
        "Base tokenizer": os.path.join(BASE_MODEL_DIR, "tokenizer"),
        "Base text_encoder": os.path.join(BASE_MODEL_DIR, "text_encoder"),
        "Base VAE": os.path.join(BASE_MODEL_DIR, "vae"),
        "Base scheduler": os.path.join(BASE_MODEL_DIR, "scheduler"),
        "Avatar single DiT": os.path.join(AVATAR_MODEL_DIR, "avatar_single"),
        "Wav2Vec2": os.path.join(AVATAR_MODEL_DIR, "chinese-wav2vec2-base"),
        "Vocal separator": os.path.join(AVATAR_MODEL_DIR, "vocal_separator"),
    }
    status = {}
    for name, path in needed.items():
        status[name] = os.path.isdir(path) and len(os.listdir(path)) > 0
    return status


def download_models_if_needed(progress=gr.Progress(track_tqdm=True)):
    """Download missing model weights from HuggingFace."""
    status = check_models()
    missing = [k for k, v in status.items() if not v]
    if not missing:
        return "✅ All model weights are already downloaded."

    log_lines = []
    os.makedirs(WEIGHTS_DIR, exist_ok=True)

    # Check which repos need downloading
    need_base = any("Base" in m for m in missing)
    need_avatar = any(m for m in missing if "Base" not in m)

    if need_base:
        log_lines.append("⬇️ Downloading LongCat-Video base model components...")
        try:
            subprocess.run(
                [
                    "huggingface-cli", "download",
                    "meituan-longcat/LongCat-Video",
                    "--local-dir", BASE_MODEL_DIR,
                    "--include", "tokenizer/*", "text_encoder/*", "vae/*", "scheduler/*",
                ],
                check=True, capture_output=True, text=True, timeout=7200,
            )
            log_lines.append("✅ Base model components downloaded.")
        except Exception as e:
            log_lines.append(f"❌ Base download error: {e}")

    if need_avatar:
        log_lines.append("⬇️ Downloading LongCat-Video-Avatar model...")
        try:
            subprocess.run(
                [
                    "huggingface-cli", "download",
                    "meituan-longcat/LongCat-Video-Avatar",
                    "--local-dir", AVATAR_MODEL_DIR,
                    "--include", "avatar_single/*", "chinese-wav2vec2-base/*", "vocal_separator/*",
                ],
                check=True, capture_output=True, text=True, timeout=7200,
            )
            log_lines.append("✅ Avatar model downloaded.")
        except Exception as e:
            log_lines.append(f"❌ Avatar download error: {e}")

    # Re-check
    final_status = check_models()
    still_missing = [k for k, v in final_status.items() if not v]
    if still_missing:
        log_lines.append(f"⚠️ Still missing: {', '.join(still_missing)}")
    else:
        log_lines.append("✅ All model weights ready!")

    return "\n".join(log_lines)


def load_pipeline():
    """Load the avatar pipeline into GPU memory."""
    global _pipeline, _vocal_separator, _device
    if _pipeline is not None:
        return "✅ Pipeline already loaded."

    import torch
    if not torch.cuda.is_available():
        return "❌ Cannot load pipeline — no CUDA GPU available."

    # Verify models exist
    status = check_models()
    missing = [k for k, v in status.items() if not v]
    if missing:
        return f"❌ Missing model weights: {', '.join(missing)}. Please download first."

    try:
        from transformers import AutoTokenizer, UMT5EncoderModel, Wav2Vec2FeatureExtractor
        from longcat_video.pipeline_longcat_video_avatar import LongCatVideoAvatarPipeline
        from longcat_video.modules.scheduling_flow_match_euler_discrete import FlowMatchEulerDiscreteScheduler
        from longcat_video.modules.autoencoder_kl_wan import AutoencoderKLWan
        from longcat_video.modules.avatar.longcat_video_dit_avatar import LongCatVideoAvatarTransformer3DModel
        from longcat_video.context_parallel import context_parallel_util
        from longcat_video.audio_process.wav2vec2 import Wav2Vec2ModelWrapper
        from audio_separator.separator import Separator

        _device = 0  # GPU 0
        dtype = torch.bfloat16

        cp_split_hw = context_parallel_util.get_optimal_split(1)

        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL_DIR, subfolder="tokenizer", torch_dtype=dtype
        )
        text_encoder = UMT5EncoderModel.from_pretrained(
            BASE_MODEL_DIR, subfolder="text_encoder", torch_dtype=dtype
        )
        vae = AutoencoderKLWan.from_pretrained(
            BASE_MODEL_DIR, subfolder="vae", torch_dtype=dtype
        )
        scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
            BASE_MODEL_DIR, subfolder="scheduler", torch_dtype=dtype
        )
        dit = LongCatVideoAvatarTransformer3DModel.from_pretrained(
            AVATAR_MODEL_DIR, subfolder="avatar_single",
            cp_split_hw=cp_split_hw, torch_dtype=dtype
        )

        wav2vec_path = os.path.join(AVATAR_MODEL_DIR, "chinese-wav2vec2-base")
        audio_encoder = Wav2Vec2ModelWrapper(wav2vec_path).to(_device)
        audio_encoder.feature_extractor._freeze_parameters()
        wav2vec_fe = Wav2Vec2FeatureExtractor.from_pretrained(wav2vec_path, local_files_only=True)

        pipe = LongCatVideoAvatarPipeline(
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            vae=vae,
            scheduler=scheduler,
            dit=dit,
            audio_encoder=audio_encoder,
            wav2vec_feature_extractor=wav2vec_fe,
        )
        pipe.to(_device)
        _pipeline = pipe

        # Vocal separator
        vocal_sep_path = os.path.join(AVATAR_MODEL_DIR, "vocal_separator", "Kim_Vocal_2.onnx")
        sep_model_dir = os.path.dirname(vocal_sep_path)
        sep_model_name = os.path.basename(vocal_sep_path)
        audio_temp = Path(AUDIO_TEMP_DIR)
        os.makedirs(audio_temp / "vocals", exist_ok=True)
        separator = Separator(
            output_dir=str(audio_temp / "vocals"),
            output_single_stem="vocals",
            model_file_dir=sep_model_dir,
        )
        separator.load_model(sep_model_name)
        _vocal_separator = separator

        return "✅ Pipeline loaded successfully on GPU!"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Pipeline load failed: {e}"


def extract_vocal(source_path):
    """Extract vocals from audio using the loaded separator."""
    global _vocal_separator
    if _vocal_separator is None:
        return source_path  # fallback: use original
    try:
        audio_temp = Path(AUDIO_TEMP_DIR)
        outputs = _vocal_separator.separate(source_path)
        if not outputs:
            return source_path
        default_vocal = audio_temp / "vocals" / outputs[0]
        target = f"/tmp/vocal_{generate_uid()}.wav"
        shutil.move(str(default_vocal.resolve()), target)
        return target
    except Exception:
        traceback.print_exc()
        return source_path


def generate_video(
    image_path,
    audio_path,
    prompt,
    negative_prompt,
    resolution,
    mode,
    num_segments,
    num_inference_steps,
    text_guidance_scale,
    audio_guidance_scale,
    seed,
    ref_img_index,
    mask_frame_range,
    progress=gr.Progress(track_tqdm=True),
):
    """Main generation function."""
    global _pipeline, _device

    if _pipeline is None:
        raise gr.Error("Pipeline not loaded. Please click 'Load Model' first.")
    if image_path is None and mode == "ai2v":
        raise gr.Error("Please upload a source image.")
    if audio_path is None:
        raise gr.Error("Please upload an audio file.")

    import torch
    import librosa
    import PIL.Image
    from diffusers.utils import load_image
    from longcat_video.audio_process.torch_utils import save_video_ffmpeg

    pipe = _pipeline
    device = _device

    # Parameters
    save_fps = 16
    num_frames = 93
    num_cond_frames = 13
    audio_stride = 2
    num_segments = max(1, int(num_segments))

    if resolution == "480p (832×480)":
        res_key = "480p"
        height, width = 480, 832
    else:  # 720p
        res_key = "720p"
        height, width = 768, 1280

    generator = torch.Generator(device=device)
    generator.manual_seed(int(seed))

    # Extract vocals
    progress(0.05, desc="Extracting vocals from audio...")
    vocal_path = extract_vocal(audio_path)

    # Load and pad audio
    progress(0.1, desc="Processing audio embeddings...")
    speech_array, sr = librosa.load(vocal_path, sr=16000)
    generate_duration = num_frames / save_fps + (num_segments - 1) * (num_frames - num_cond_frames) / save_fps
    source_duration = len(speech_array) / sr
    added_samples = math.ceil((generate_duration - source_duration) * sr)
    if added_samples > 0:
        speech_array = np.append(speech_array, [0.0] * added_samples)

    full_audio_emb = pipe.get_audio_embedding(
        speech_array, fps=save_fps * audio_stride, device=device, sample_rate=sr
    )
    if torch.isnan(full_audio_emb).any():
        raise gr.Error("Audio embedding contains NaN values — please try a different audio file.")

    # Clean up vocal temp
    if vocal_path != audio_path and os.path.exists(vocal_path):
        os.remove(vocal_path)

    # Prepare audio embedding for first clip
    indices = torch.arange(2 * 2 + 1) - 2
    audio_start_idx = 0
    audio_end_idx = audio_start_idx + audio_stride * num_frames
    center_indices = torch.arange(audio_start_idx, audio_end_idx, audio_stride).unsqueeze(1) + indices.unsqueeze(0)
    center_indices = torch.clamp(center_indices, min=0, max=full_audio_emb.shape[0] - 1)
    audio_emb = full_audio_emb[center_indices][None, ...].to(device)

    # Generate first segment
    progress(0.15, desc=f"Generating segment 1/{num_segments}...")
    uid = generate_uid()
    out_base = os.path.join(OUTPUT_DIR, f"avatar_{uid}")

    if mode == "ai2v":
        image = load_image(image_path)
        output_tuple = pipe.generate_ai2v(
            image=image,
            prompt=prompt,
            negative_prompt=negative_prompt,
            resolution=res_key,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            text_guidance_scale=text_guidance_scale,
            audio_guidance_scale=audio_guidance_scale,
            output_type="both",
            generator=generator,
            audio_emb=audio_emb,
        )
    else:  # at2v
        output_tuple = pipe.generate_at2v(
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=height,
            width=width,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            text_guidance_scale=text_guidance_scale,
            audio_guidance_scale=audio_guidance_scale,
            generator=generator,
            output_type="both",
            audio_emb=audio_emb,
        )

    output, latent = output_tuple
    output = output[0]
    video = [(output[i] * 255).astype(np.uint8) for i in range(output.shape[0])]
    video = [PIL.Image.fromarray(img) for img in video]
    del output
    torch.cuda.empty_cache()

    ref_latent = latent[:, :, :1].clone()
    all_frames = list(video)
    current_video = video

    # Video continuation segments
    for seg_idx in range(1, num_segments):
        pct = 0.15 + 0.8 * seg_idx / num_segments
        progress(pct, desc=f"Generating segment {seg_idx + 1}/{num_segments}...")

        audio_start_idx += audio_stride * (num_frames - num_cond_frames)
        audio_end_idx = audio_start_idx + audio_stride * num_frames
        center_indices = torch.arange(audio_start_idx, audio_end_idx, audio_stride).unsqueeze(1) + indices.unsqueeze(0)
        center_indices = torch.clamp(center_indices, min=0, max=full_audio_emb.shape[0] - 1)
        audio_emb = full_audio_emb[center_indices][None, ...].to(device)

        output_tuple = pipe.generate_avc(
            video=current_video,
            video_latent=latent,
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=current_video[0].size[1],
            width=current_video[0].size[0],
            num_frames=num_frames,
            num_cond_frames=num_cond_frames,
            num_inference_steps=num_inference_steps,
            text_guidance_scale=text_guidance_scale,
            audio_guidance_scale=audio_guidance_scale,
            generator=generator,
            output_type="both",
            use_kv_cache=True,
            offload_kv_cache=False,
            enhance_hf=True,
            audio_emb=audio_emb,
            ref_latent=ref_latent,
            ref_img_index=ref_img_index,
            mask_frame_range=mask_frame_range,
        )
        output, latent = output_tuple
        output = output[0]
        new_video = [(output[i] * 255).astype(np.uint8) for i in range(output.shape[0])]
        new_video = [PIL.Image.fromarray(img) for img in new_video]
        del output
        torch.cuda.empty_cache()

        all_frames.extend(new_video[num_cond_frames:])
        current_video = new_video

    # Save final video with audio
    progress(0.95, desc="Encoding final video with audio...")
    output_tensor = torch.from_numpy(np.array(all_frames))
    save_video_ffmpeg(output_tensor, out_base, audio_path, fps=save_fps, quality=5)

    final_path = out_base + ".mp4"
    if os.path.exists(final_path):
        progress(1.0, desc="Done!")
        return final_path
    else:
        raise gr.Error("Video generation completed but output file not found.")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------
def get_system_status():
    gpu_ok, gpu_info = check_gpu()
    model_status = check_models()
    model_lines = []
    for name, ready in model_status.items():
        icon = "✅" if ready else "❌"
        model_lines.append(f"  {icon} {name}")
    pipeline_status = "✅ Loaded" if _pipeline is not None else "⏳ Not loaded"

    return (
        f"**GPU:** {gpu_info}\n\n"
        f"**Pipeline:** {pipeline_status}\n\n"
        f"**Model Weights:**\n" + "\n".join(model_lines)
    )


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
.status-box { padding: 12px; border-radius: 8px; background: #1a1a2e; border: 1px solid #333; }
.header-text { text-align: center; margin-bottom: 8px; }
footer { display: none !important; }
"""

def build_ui():
    with gr.Blocks(
        title="🐱 LongCat-Video Avatar — Lipsync Generator",
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="purple"),
    ) as demo:
        # Header
        gr.Markdown(
            """
            # 🐱 LongCat-Video Avatar — Lipsync Generator
            **Generate expressive audio-driven portrait animations from a single image and audio clip.**
            Upload a portrait/avatar image and an audio file to create a talking-head video with natural lip sync.
            """,
            elem_classes="header-text",
        )

        # ---- Setup Tab ----
        with gr.Tab("⚙️ Setup & Status"):
            gr.Markdown("### System Status")
            status_display = gr.Markdown(value=get_system_status)

            with gr.Row():
                btn_refresh = gr.Button("🔄 Refresh Status", variant="secondary")
                btn_download = gr.Button("⬇️ Download Models", variant="primary")
                btn_load = gr.Button("🚀 Load Pipeline to GPU", variant="primary")

            download_log = gr.Textbox(label="Download / Load Log", lines=5, interactive=False)

            btn_refresh.click(fn=get_system_status, outputs=status_display)
            btn_download.click(fn=download_models_if_needed, outputs=download_log).then(
                fn=get_system_status, outputs=status_display
            )
            btn_load.click(fn=load_pipeline, outputs=download_log).then(
                fn=get_system_status, outputs=status_display
            )

        # ---- Generate Tab ----
        with gr.Tab("🎬 Generate Video"):
            with gr.Row(equal_height=False):
                # Left: Inputs
                with gr.Column(scale=1):
                    gr.Markdown("### 📥 Inputs")

                    source_image = gr.Image(
                        label="Portrait / Avatar Image",
                        type="filepath",
                        sources=["upload", "clipboard"],
                        height=280,
                    )
                    audio_file = gr.Audio(
                        label="Audio File (speech/singing)",
                        type="filepath",
                        sources=["upload", "microphone"],
                    )
                    prompt = gr.Textbox(
                        label="Prompt (describe the scene & character)",
                        value=DEFAULT_PROMPT,
                        lines=3,
                        placeholder="Describe the character and scene...",
                    )

                    with gr.Accordion("⚙️ Advanced Settings", open=False):
                        negative_prompt = gr.Textbox(
                            label="Negative Prompt",
                            value=DEFAULT_NEGATIVE_PROMPT,
                            lines=2,
                        )
                        resolution = gr.Radio(
                            label="Resolution",
                            choices=["480p (832×480)", "720p (1280×768)"],
                            value="480p (832×480)",
                            info="720p produces higher quality but requires more VRAM and time",
                        )
                        mode = gr.Radio(
                            label="Generation Mode",
                            choices=["ai2v", "at2v"],
                            value="ai2v",
                            info="ai2v = Audio+Image→Video (recommended) | at2v = Audio+Text→Video",
                        )
                        num_segments = gr.Slider(
                            label="Number of Segments (more = longer video)",
                            minimum=1, maximum=10, step=1, value=1,
                            info="Each segment ≈ 5 sec. Video continuation extends length.",
                        )
                        num_inference_steps = gr.Slider(
                            label="Inference Steps",
                            minimum=10, maximum=80, step=1, value=50,
                            info="More steps = higher quality, slower generation",
                        )
                        text_guidance_scale = gr.Slider(
                            label="Text Guidance Scale",
                            minimum=1.0, maximum=10.0, step=0.5, value=4.0,
                        )
                        audio_guidance_scale = gr.Slider(
                            label="Audio Guidance Scale",
                            minimum=1.0, maximum=10.0, step=0.5, value=4.0,
                            info="Higher = stronger lip sync (3–5 recommended)",
                        )
                        seed = gr.Number(label="Random Seed", value=42, precision=0)
                        ref_img_index = gr.Slider(
                            label="Reference Image Index",
                            minimum=-10, maximum=30, step=1, value=10,
                            info="0–24 for consistency; other ranges reduce repeated actions",
                        )
                        mask_frame_range = gr.Slider(
                            label="Mask Frame Range",
                            minimum=1, maximum=10, step=1, value=3,
                            info="Larger values reduce repeated actions but may add artifacts",
                        )

                    generate_btn = gr.Button(
                        "🎬 Generate Lipsync Video",
                        variant="primary",
                        size="lg",
                    )

                # Right: Output
                with gr.Column(scale=1):
                    gr.Markdown("### 🎥 Output")
                    output_video = gr.Video(label="Generated Video", height=400)
                    download_btn = gr.DownloadButton(
                        label="📥 Download Video",
                        visible=False,
                    )

            # Wire generation
            def on_generate(*args):
                video_path = generate_video(*args)
                return gr.Video(value=video_path), gr.DownloadButton(value=video_path, visible=True)

            generate_btn.click(
                fn=on_generate,
                inputs=[
                    source_image, audio_file, prompt, negative_prompt,
                    resolution, mode, num_segments, num_inference_steps,
                    text_guidance_scale, audio_guidance_scale, seed,
                    ref_img_index, mask_frame_range,
                ],
                outputs=[output_video, download_btn],
            )

        # ---- Tips Tab ----
        with gr.Tab("💡 Tips & Info"):
            gr.Markdown(
                """
                ### 🎯 Tips for Best Results

                **Image Selection:**
                - Use a clear, well-lit portrait photo with the face prominently visible
                - Frontal or slightly angled face views work best
                - Avoid heavy occlusions (sunglasses, masks, etc.)
                - Higher resolution source images produce better results

                **Audio Tips:**
                - Clean speech audio works best — the vocal separator will try to isolate vocals
                - Audio length determines video length (with silence padding if needed)
                - Supported formats: WAV, MP3, FLAC, OGG, M4A

                **Parameter Tuning:**
                - **Audio Guidance Scale (3–5):** Higher values improve lip sync accuracy
                - **Text Guidance Scale (3–5):** Controls how closely the video follows the text prompt
                - **Inference Steps (50):** Default is good; lower for speed, higher for quality
                - **Number of Segments:** Each segment ≈ 5 seconds at 16fps (93 frames)
                  - 1 segment ≈ 5.8 sec, 2 segments ≈ 10.8 sec, 5 segments ≈ 25.8 sec
                - **Reference Image Index:** 0–24 ensures consistency, -10 or 30 reduces repetitive motions
                - **Mask Frame Range:** Increase to reduce repeated actions, but don't go too high

                **Resolution:**
                - **480p (832×480):** Faster generation, less VRAM required
                - **720p (1280×768):** Higher quality, requires more VRAM and time

                **Generation Modes:**
                - **ai2v (Audio+Image→Video):** Uses your uploaded image as the character appearance — **recommended**
                - **at2v (Audio+Text→Video):** Generates the character from the text prompt only

                ### 📐 About Resolutions
                The model natively supports 480p and 720p output. The actual pixel dimensions
                are determined by the input image's aspect ratio, matched to the nearest
                supported bucket. For portrait orientation, expect ~480×832 or ~768×1280.

                ### ⏱ Performance
                - Single segment at 480p: ~2–5 min on A100 80GB
                - Single segment at 720p: ~5–10 min on A100 80GB
                - Video continuation adds proportional time per segment
                """
            )

    return demo


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    demo = build_ui()
    demo.queue(max_size=2)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )
