"""
Image Generation Tool — LOCAL ONLY, no paid APIs.

Architecture mirrors the Piper TTS approach: small .onnx models stored in
models/  next to this file, loaded at runtime via onnxruntime (already
installed for Piper voices).

Recommended model (download once, ~540 MB):
  LCM-Dreamshaper-v7 ONNX — CPU-friendly, 4-step generation, ~8s per image
  Download script:  python image_gen_tool.py --download

Backends (tried in order):
  1. lcm_onnx    — LCM-Dreamshaper-v7 ONNX  (fast CPU, recommended)
  2. sd_onnx     — any ONNX SD unet you place in models/sd_onnx/
  3. gradient    — pure-Pillow procedural background, always works, zero deps

ALL CONFIG driven by caller — no hardcoded prompts.
Results are cached by (prompt+size) hash — identical calls are instant.

Quick start:
  python image_gen_tool.py --download          # download LCM model (~540 MB)
  python image_gen_tool.py --test              # generate a test image
  python image_gen_tool.py --test --backend gradient   # test without model
"""

import hashlib
import os
import sys
from typing import Optional, Type

# ── crewai / pydantic are only needed inside CrewAI ───────────────────────
# When run as a standalone CLI (--download / --test) these may not be
# available in the current Python environment, so we stub them out.
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
    _CREWAI_AVAILABLE = True
except ImportError:
    _CREWAI_AVAILABLE = False

    class BaseModel:       # minimal stub — only used for type hints
        pass
    class BaseTool:        # minimal stub
        pass
    def Field(*args, **kwargs):
        return kwargs.get("default", None)

# ── Paths ──────────────────────────────────────────────────────────────────
_TOOL_DIR  = os.path.dirname(os.path.abspath(__file__))

# Models live at project root: crewai_video_factory/models/
# tools/ is at: src/crewai_video_factory/tools/
# Project root = 3 levels up from _TOOL_DIR
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TOOL_DIR)))
_MODEL_DIR    = os.path.join(_PROJECT_ROOT, "models")
_CACHE_DIR    = os.path.join(_TOOL_DIR, "image_gen_cache")

# LCM sits alongside alba_medium.onnx, joe_medium.onnx etc.
LCM_MODEL_DIR = os.path.join(_MODEL_DIR, "lcm_dreamshaper_v7_onnx")

# ── Default prompts ────────────────────────────────────────────────────────
DEFAULT_DEBATE_BG_PROMPT = (
    "futuristic digital debate arena, dark navy deep purple, "
    "abstract geometric circuit patterns, soft volumetric light beams, "
    "blurred bokeh background, cinematic, no text, no people, no faces"
)
DEFAULT_SHORTS_BG_PROMPT = (
    "futuristic digital debate arena, dark navy deep purple portrait, "
    "abstract geometric circuit patterns, soft volumetric light, "
    "blurred bokeh background, cinematic vertical, no text, no people"
)


# ══════════════════════════════════════════════════════════════════════════
#  Pydantic schema
# ══════════════════════════════════════════════════════════════════════════

class ImageGenInput(BaseModel):
    prompt:      str           = Field(default=DEFAULT_DEBATE_BG_PROMPT)
    width:       int           = Field(default=1920)
    height:      int           = Field(default=1080)
    output_path: Optional[str] = Field(default=None)
    backend:     str           = Field(
        default="auto",
        description="auto | lcm_onnx | sd_onnx | gradient"
    )


# ══════════════════════════════════════════════════════════════════════════
#  Tool
# ══════════════════════════════════════════════════════════════════════════

class ImageGenTool(BaseTool):
    """
    Generates a background image from a text prompt using LOCAL models only.
    No paid APIs. Uses the same onnxruntime already installed for Piper TTS.

    Recommended model: LCM-Dreamshaper-v7 ONNX (~540 MB, one-time download).
    Falls back to a beautiful procedural gradient with zero extra dependencies.

    Returns: absolute path to the generated/cached PNG.
    """
    name: str = "Image Generation Tool"
    description: str = (
        "Generates a background image from a text prompt (LOCAL, no paid API).  "
        "Uses LCM-Dreamshaper ONNX model if downloaded, else procedural gradient.  "
        "Run: python image_gen_tool.py --download  to get the model.  "
        "Returns absolute path to cached PNG."
    )
    args_schema: Type[BaseModel] = ImageGenInput

    def _run(
        self,
        prompt:      str  = DEFAULT_DEBATE_BG_PROMPT,
        width:       int  = 1920,
        height:      int  = 1080,
        output_path: str  = None,
        backend:     str  = "auto",
    ) -> str:
        os.makedirs(_CACHE_DIR, exist_ok=True)

        if not output_path:
            key         = hashlib.md5(f"{prompt}|{width}|{height}".encode()).hexdigest()[:12]
            output_path = os.path.join(_CACHE_DIR, f"bg_{key}.png")

        # Cache hit
        if os.path.exists(output_path):
            kb = os.path.getsize(output_path) // 1024
            print(f"[ImageGen] ✅ Cache hit: {os.path.basename(output_path)} ({kb} KB)")
            return output_path

        print(f"[ImageGen] 🎨 Generating {width}x{height}  backend={backend}")
        print(f"[ImageGen]    Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        for b in self._resolve_backends(backend):
            try:
                print(f"[ImageGen]   Trying: {b}")
                if b == "lcm_onnx":
                    result = _generate_lcm_onnx(prompt, width, height, output_path)
                elif b == "sd_onnx":
                    result = _generate_sd_onnx(prompt, width, height, output_path)
                elif b == "gradient":
                    result = _generate_gradient(width, height, output_path, prompt)
                else:
                    continue

                if result and os.path.exists(result):
                    kb = os.path.getsize(result) // 1024
                    print(f"[ImageGen] ✅ Saved: {os.path.basename(result)} ({kb} KB)")
                    return result
            except Exception as e:
                print(f"[ImageGen]   ⚠️  {b} failed: {e}")

        # Should never reach here (gradient always works)
        return _generate_gradient(width, height, output_path, prompt)

    @staticmethod
    def _resolve_backends(backend: str) -> list:
        if backend == "auto":
            order = []
            if os.path.isdir(LCM_MODEL_DIR):
                order.append("lcm_onnx")
            if os.path.isdir(os.path.join(_MODEL_DIR, "sd_onnx")):
                order.append("sd_onnx")
            order.append("gradient")
            return order
        return [backend, "gradient"]  # gradient is always the safety net


# ══════════════════════════════════════════════════════════════════════════
#  Backend 1: LCM-Dreamshaper-v7 ONNX  (recommended)
# ══════════════════════════════════════════════════════════════════════════
#
#  Model layout inside  models/lcm_dreamshaper_v7_onnx/:
#    unet/model.onnx           ~95 MB   (denoiser)
#    vae_decoder/model.onnx    ~95 MB   (latent -> pixel)
#    text_encoder/model.onnx  ~246 MB   (CLIP, optional but recommended)
#    tokenizer/                         (vocab files)
#
#  Generation: 4 LCM steps at 512x512, then Lanczos-resize to target.
#  CPU timing: ~8-15 s depending on CPU.

def _generate_lcm_onnx(prompt: str, width: int, height: int,
                        out_path: str, model_dir: str = None) -> str:
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    mdir      = model_dir or LCM_MODEL_DIR
    unet_path = os.path.join(mdir, "unet",         "model.onnx")
    vae_path  = os.path.join(mdir, "vae_decoder",  "model.onnx")
    te_path   = os.path.join(mdir, "text_encoder", "model.onnx")
    tok_dir   = os.path.join(mdir, "tokenizer")

    for label, p in [("unet", unet_path), ("vae_decoder", vae_path)]:
        if not os.path.exists(p):
            raise FileNotFoundError(
                f"LCM model file missing: {p}\n"
                f"  Run:  python {os.path.abspath(__file__)} --download"
            )

    opts = ort.SessionOptions()
    opts.inter_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Required when model uses external data file (e.g. unet/model.onnx_data)
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    providers = ["CPUExecutionProvider"]

    # ── Text encoding ──────────────────────────────────────────────────
    if os.path.exists(te_path) and os.path.isdir(tok_dir):
        print("[ImageGen]   Encoding prompt via CLIP ONNX...")
        text_embeds = _encode_prompt_onnx(prompt, te_path, tok_dir, opts, providers)
    else:
        print("[ImageGen]   Text encoder absent — using keyword embedding fallback")
        text_embeds = _encode_prompt_keyword(prompt)  # (1, 77, 768) float32

    # ── LCM denoising (4 steps) ────────────────────────────────────────
    GEN_W, GEN_H = 512, 512
    lat_w, lat_h = GEN_W // 8, GEN_H // 8

    rng     = np.random.default_rng(42)
    latents = rng.standard_normal((1, 4, lat_h, lat_w)).astype(np.float32)

    # SD1.5 DDIM-style timesteps — 20 steps for good quality on CPU
    timesteps     = np.linspace(999, 0, 20, dtype=np.int64)
    guidance_scale = np.array([8.0], dtype=np.float32)

    print("[ImageGen]   Loading UNet...")
    unet_sess   = ort.InferenceSession(unet_path, opts, providers=providers)
    unet_inputs = {i.name for i in unet_sess.get_inputs()}

    for step_i, t in enumerate(timesteps):
        t_arr = np.array([t], dtype=np.int64)
        feed  = {
            "sample":                latents,
            "timestep":              t_arr,
            "encoder_hidden_states": text_embeds,
        }
        if "guidance_scale" in unet_inputs:
            feed["guidance_scale"] = guidance_scale

        noise_pred = unet_sess.run(None, feed)[0]  # (1, 4, 64, 64)

        # Simplified LCM Euler step
        alpha_t = 1.0 - (t / 1000.0)
        latents = (latents - (1.0 - alpha_t) ** 0.5 * noise_pred) / max(alpha_t ** 0.5, 1e-6)

        print(f"[ImageGen]   Step {step_i + 1}/{len(timesteps)}  t={t}")

    del unet_sess  # free RAM before VAE

    # ── VAE decode ─────────────────────────────────────────────────────
    print("[ImageGen]   Decoding latents via VAE...")
    vae_sess       = ort.InferenceSession(vae_path, opts, providers=providers)
    latents_scaled = latents / 0.18215  # SD VAE scaling factor
    pixels         = vae_sess.run(None, {"latent_sample": latents_scaled})[0]

    # (1, 3, H, W) in [-1, 1] → uint8 RGB
    pixels = (pixels.squeeze(0).transpose(1, 2, 0).clip(-1, 1) + 1) / 2 * 255
    img    = Image.fromarray(pixels.astype("uint8"), "RGB")

    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)

    img.save(out_path, "PNG")
    return out_path


def _encode_prompt_onnx(prompt: str, te_path: str, tok_dir: str,
                         opts, providers) -> "np.ndarray":
    """Tokenize + encode via the CLIP text encoder ONNX."""
    import numpy as np
    import json, re
    import onnxruntime as ort

    vocab_file = os.path.join(tok_dir, "vocab.json")
    merge_file = os.path.join(tok_dir, "merges.txt")
    if not (os.path.exists(vocab_file) and os.path.exists(merge_file)):
        return _encode_prompt_keyword(prompt)

    with open(vocab_file) as f:
        vocab = json.load(f)

    SOT, EOT, PAD, MAX_LEN = 49406, 49407, 49407, 77

    tokens = [SOT]
    for word in re.findall(r"[a-zA-Z0-9']+|[^\w\s]", prompt.lower()):
        tok = vocab.get(word + "</w>") or vocab.get(word)
        if tok is not None:
            tokens.append(tok)
    tokens.append(EOT)
    tokens = tokens[:MAX_LEN]
    tokens += [PAD] * (MAX_LEN - len(tokens))

    te_sess    = ort.InferenceSession(te_path, opts, providers=providers)
    input_ids  = np.array([tokens], dtype=np.int32)
    embeds     = te_sess.run(None, {"input_ids": input_ids})[0]  # (1, 77, 768)
    return embeds.astype(np.float32)


def _encode_prompt_keyword(prompt: str) -> "np.ndarray":
    """
    Zero-dependency keyword-weighted embedding (1, 77, 768).
    Sufficient for background generation where spatial layout matters less
    than having valid non-zero conditioning.
    """
    import numpy as np

    rng  = np.random.default_rng(seed=0)
    base = rng.standard_normal((768,)).astype(np.float32)
    base /= np.linalg.norm(base) + 1e-8

    concept_seeds = {
        "dark": 1, "blue": 2, "purple": 3, "futuristic": 4,
        "geometric": 5, "abstract": 6, "circuit": 7, "light": 8,
        "blur": 9, "cinematic": 10, "arena": 11, "digital": 12,
        "neon": 13, "space": 14, "gradient": 15, "background": 16,
    }
    for kw, seed in concept_seeds.items():
        if kw in prompt.lower():
            kw_rng = np.random.default_rng(seed=seed * 1000)
            delta  = kw_rng.standard_normal((768,)).astype(np.float32)
            delta /= np.linalg.norm(delta) + 1e-8
            base  += delta * 0.3

    base /= np.linalg.norm(base) + 1e-8
    return np.tile(base, (1, 77, 1)).astype(np.float32)


# ══════════════════════════════════════════════════════════════════════════
#  Backend 2: Generic SD ONNX  (bring-your-own model)
# ══════════════════════════════════════════════════════════════════════════

def _generate_sd_onnx(prompt: str, width: int, height: int, out_path: str) -> str:
    """Delegate to LCM logic using the sd_onnx directory."""
    sd_dir = os.path.join(_MODEL_DIR, "sd_onnx")
    return _generate_lcm_onnx(prompt, width, height, out_path, model_dir=sd_dir)


# ══════════════════════════════════════════════════════════════════════════
#  Backend 3: Procedural gradient  (Pillow only, always works)
# ══════════════════════════════════════════════════════════════════════════

def _generate_gradient(width: int, height: int, out_path: str,
                        prompt: str = "") -> str:
    """
    Generates a rich dark background purely with Pillow.
    Colour palette is derived from keywords in the prompt so
    different topics get subtly different visuals.
    """
    from PIL import Image, ImageDraw, ImageFilter
    import random

    print(f"[ImageGen]   Rendering procedural gradient {width}x{height}")

    p = prompt.lower()
    if   any(w in p for w in ["red", "fire", "warm", "orange"]):
        top, bot, accent = (30, 5, 15),  (70, 15, 5),  (180, 40, 20)
    elif any(w in p for w in ["green", "nature", "forest", "emerald"]):
        top, bot, accent = (5, 25, 15),  (10, 55, 30), (20, 160, 80)
    elif any(w in p for w in ["gold", "yellow", "luxury"]):
        top, bot, accent = (30, 20, 5),  (60, 40, 5),  (180, 130, 20)
    else:
        # Default: dark navy -> deep purple
        top, bot, accent = (8, 10, 35), (28, 8, 60), (40, 20, 140)

    # Layer 1: vertical gradient
    img  = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        t = t * t * (3 - 2 * t)  # smooth-step
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Layer 2: diagonal grid lines
    line_col = tuple(min(255, c + 18) for c in top)
    step     = max(width // 18, 48)
    for i in range(-height, width + height, step):
        draw.line([(i, 0), (i + height, height)], fill=line_col, width=1)

    # Layer 3: soft glowing orbs (additive blend)
    try:
        import numpy as np
        orb_layer = Image.new("RGB", (width, height), (0, 0, 0))
        od        = ImageDraw.Draw(orb_layer)
        rng       = random.Random(42)
        for _ in range(6):
            cx  = rng.randint(width  // 4, 3 * width  // 4)
            cy  = rng.randint(height // 4, 3 * height // 4)
            rad = rng.randint(min(width, height) // 6, min(width, height) // 3)
            for r in range(rad, 0, -max(1, rad // 40)):
                a   = (1.0 - r / rad) ** 2.5
                col = tuple(int(accent[i] * a * 0.6) for i in range(3))
                if sum(col) < 2:
                    break
                od.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col)
        orb_layer = orb_layer.filter(ImageFilter.GaussianBlur(radius=max(width // 80, 8)))
        img_arr   = np.array(img,       dtype="int32")
        orb_arr   = np.array(orb_layer, dtype="int32")
        img       = Image.fromarray((img_arr + orb_arr).clip(0, 255).astype("uint8"))
    except Exception:
        pass  # skip orbs if numpy not available

    # Layer 4: vignette
    vig  = Image.new("RGB", (width, height), (0, 0, 0))
    vd   = ImageDraw.Draw(vig)
    cx, cy = width // 2, height // 2
    for i in range(60):
        t   = i / 60
        a   = t ** 2.2 * 0.65
        rw  = int(width  * (1 - t * 0.5))
        rh  = int(height * (1 - t * 0.5))
        col = tuple(int(c * (1 - a)) for c in (8, 10, 35))
        vd.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], outline=col)
    img = Image.blend(img, vig, 0.3)

    img.save(out_path, "PNG")
    return out_path


# ══════════════════════════════════════════════════════════════════════════
#  Convenience function  (direct import from debate_video_tool.py)
# ══════════════════════════════════════════════════════════════════════════

def generate_background(
    prompt:      str  = DEFAULT_DEBATE_BG_PROMPT,
    width:       int  = 1920,
    height:      int  = 1080,
    output_path: str  = None,
    backend:     str  = "auto",
) -> str:
    """Drop-in helper — no CrewAI wrapper needed."""
    tool = ImageGenTool()
    return tool._run(
        prompt=prompt, width=width, height=height,
        output_path=output_path, backend=backend,
    )


# ══════════════════════════════════════════════════════════════════════════
#  Model download helper
# ══════════════════════════════════════════════════════════════════════════

def download_lcm_model():
    """
    Download LCM-Dreamshaper-v7 ONNX from Hugging Face (~1 GB total).
    Saves to:  models/lcm_dreamshaper_v7_onnx/

    This is the ONLY download needed. After this, generation works fully
    offline — exactly like Piper TTS .onnx voices.

    Model:   https://huggingface.co/deinferno/LCM_Dreamshaper_v7-onnx
    License: CreativeML Open RAIL-M (free, including commercial use)
    """
    import urllib.request

    BASE = "https://huggingface.co/modularai/stable-diffusion-1.5-onnx/resolve/main"
    FILES = [
        ("unet/model.onnx",                  "unet/model.onnx"),
        ("unet/model.onnx_data",             "unet/model.onnx_data"),   # SD1.5 external weights
        ("vae_decoder/model.onnx",           "vae_decoder/model.onnx"),
        ("text_encoder/model.onnx",          "text_encoder/model.onnx"),
        ("tokenizer/vocab.json",             "tokenizer/vocab.json"),
        ("tokenizer/merges.txt",             "tokenizer/merges.txt"),
        ("tokenizer/tokenizer_config.json",  "tokenizer/tokenizer_config.json"),
    ]

    print(f"\n  Downloading LCM-Dreamshaper-v7 ONNX")
    print(f"  Destination: {LCM_MODEL_DIR}")
    print(f"  Size: ~1 GB  (one-time download)\n")
    os.makedirs(LCM_MODEL_DIR, exist_ok=True)

    failed = []
    for remote_rel, local_rel in FILES:
        dst = os.path.join(LCM_MODEL_DIR, local_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            print(f"  Already exists: {local_rel}  ({os.path.getsize(dst)//1024} KB)")
            continue
        print(f"  Downloading {local_rel} ...", end="", flush=True)
        tmp = dst + ".tmp"
        try:
            req = urllib.request.Request(
                f"{BASE}/{remote_rel}",
                headers={"User-Agent": "python/image_gen_tool"}
            )
            hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
            if hf_token:
                req.add_header("Authorization", f"Bearer {hf_token}")
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(tmp, 'wb') as fout:
                    fout.write(resp.read())
            os.rename(tmp, dst)
            print(f"  {os.path.getsize(dst)//1024} KB")
        except Exception as e:
            errmsg = str(e)
            if "401" in errmsg:
                print(f"  FAILED (401 Unauthorized)")
                print()
                print("  ⚠️  This repo requires a HuggingFace account.")
                print("  Fix options:")
                print("    1. Set env var:  export HF_TOKEN=hf_xxxx  then re-run --download")
                print("       Get token at: https://huggingface.co/settings/tokens")
                print("    2. Or just use the gradient backend (already works, no download needed)")
                print("       The gradient gives a nice dark background for free.")
                print()
            else:
                print(f"  FAILED: {e}")
            failed.append(local_rel)
            if os.path.exists(tmp):
                os.remove(tmp)
            break  # stop trying if auth fails

    if failed:
        print(f"\n  Some files failed: {failed}")
        print("  Re-run --download to retry.")
    else:
        print(f"\n  All model files ready in {LCM_MODEL_DIR}")
        print("  Test with: python image_gen_tool.py --test")


# ══════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="ImageGenTool CLI")
    ap.add_argument("--download", action="store_true",
                    help="Download LCM-Dreamshaper-v7 ONNX model (~540 MB)")
    ap.add_argument("--test",     action="store_true",
                    help="Generate a test background image")
    ap.add_argument("--prompt",   default=DEFAULT_DEBATE_BG_PROMPT)
    ap.add_argument("--backend",  default="auto",
                    choices=["auto", "lcm_onnx", "sd_onnx", "gradient"])
    ap.add_argument("--width",    type=int, default=1920)
    ap.add_argument("--height",   type=int, default=1080)
    args = ap.parse_args()

    if args.download:
        download_lcm_model()

    if args.test:
        out = generate_background(
            prompt=args.prompt,
            width=args.width,
            height=args.height,
            backend=args.backend,
        )
        print(f"\n  Test image saved: {out}")
