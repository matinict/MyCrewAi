# Download from our chat file
"""
Debate Background Video Tool
════════════════════════════════════════════════════════════════════════
Generates an animated background VIDEO for debate videos by:
  1. Calling image_gen_tool.generate_background() → PNG image
     (uses gradient backend — always works, zero extra deps)
  2. Animating the PNG with FFmpeg Ken Burns zoom+pan → .mp4

Triggered by: "debate_background_enabled": true in data.json
Output:        output/{filename}/debate_bg_{fmt}.mp4

debate_video_tool.py reads debate_bg_{fmt}.mp4 automatically
and composites debate text on top when debate_background_enabled=true.

ALL CONFIG FROM data.json — NO HARDCODED VALUES
"""
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# ── Reuse existing image_gen_tool ─────────────────────────────────────────
try:
    from .image_gen_tool import generate_background
    _IMAGE_GEN_AVAILABLE = True
except ImportError:
    try:
        from image_gen_tool import generate_background
        _IMAGE_GEN_AVAILABLE = True
    except ImportError:
        _IMAGE_GEN_AVAILABLE = False
        print("[DebateBg] ⚠️  image_gen_tool not found — will use FFmpeg gradient only")

# ── Resolution map ────────────────────────────────────────────────────────
RESOLUTIONS = {
    "HD":       (1920, 1080),
    "2K":       (2560, 1440),
    "4K":       (3840, 2160),
    "8K":       (7680, 4320),
    "Shorts":   (1080, 1920),
    "ShortsHD": (1080, 1920),
    "Shorts4K": (2160, 3840),
}


# ── Input Schema ──────────────────────────────────────────────────────────
class DebateBgVideoInput(BaseModel):
    topic:                     str   = Field(...,  description="Debate topic")
    filename:                  str   = Field(...,  description="Base filename slug")
    output_dir:                str   = Field(...,  description="Output subdirectory")
    video_formats:             list  = Field(...,  description="Formats: HD, Shorts, etc.")
    debate_background_enabled: bool  = Field(default=False,  description="Generate background video")
    debate_background_prompt:  str   = Field(
        default="futuristic digital debate arena, dark navy deep purple, "
                "abstract geometric circuit patterns, soft volumetric light beams, "
                "blurred bokeh background, cinematic, no text, no people, no faces",
        description="Image generation prompt"
    )
    debate_bg_opacity:         int   = Field(default=150,   description="Opacity 0-255 for composite")
    image_gen_backend:         str   = Field(default="auto", description="auto|gradient|pollinations|lcm_onnx")
    video_fps:                 int   = Field(default=30,     description="Output FPS")
    bg_duration:               float = Field(default=0.0,    description="Duration in seconds. 0=auto")


# ── Tool ──────────────────────────────────────────────────────────────────
class DebateBgVideoTool(BaseTool):
    name: str = "Debate Background Video Tool"
    description: str = (
        "Generates animated background video for debate videos. "
        "Uses image_gen_tool for PNG generation, then FFmpeg Ken Burns animation. "
        "Triggered by debate_background_enabled=true in data.json. "
        "Output: debate_bg_{fmt}.mp4 in output_dir."
    )
    args_schema: Type[BaseModel] = DebateBgVideoInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        video_formats: list,
        debate_background_enabled: bool = False,
        debate_background_prompt: str = "futuristic digital debate arena, dark navy deep purple, cinematic",
        debate_bg_opacity: int = 150,
        image_gen_backend: str = "auto",
        video_fps: int = 30,
        bg_duration: float = 0.0,
    ) -> str:

        if not debate_background_enabled:
            return "⏭️ Debate background skipped (debate_background_enabled=false)"

        # ── Resolve output path ───────────────────────────────────────────
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        results, errors = [], []

        for fmt in video_formats:
            try:
                w, h   = RESOLUTIONS.get(fmt, (1920, 1080))
                out_bg = os.path.join(output_dir, f"debate_bg_{fmt}.mp4")

                # ── Smart skip ────────────────────────────────────────────
                if os.path.exists(out_bg):
                    kb = os.path.getsize(out_bg) // 1024
                    results.append(f"⏭️ {fmt}: exists ({kb} KB)")
                    print(f"[DebateBg] ⏭️ {fmt}: debate_bg_{fmt}.mp4 exists — skipping")
                    continue

                # ── Auto duration from existing debate video ──────────────
                duration = bg_duration
                if duration <= 0:
                    for vid_name in [
                        f"debate_video_{fmt}_with_audio.mp4",
                        f"debate_video_{fmt}.mp4",
                    ]:
                        vid_path = os.path.join(output_dir, vid_name)
                        if os.path.exists(vid_path):
                            duration = self._get_duration(vid_path)
                            print(f"[DebateBg] [{fmt}] Auto duration: {duration:.1f}s from {vid_name}")
                            break
                    if duration <= 0:
                        duration = 120.0
                        print(f"[DebateBg] [{fmt}] No debate video found — default {duration}s")

                print(f"[DebateBg] [{fmt}] {w}x{h}  dur={duration:.1f}s  backend={image_gen_backend}")

                # ── Step 1: Generate background PNG ───────────────────────
                png_path    = os.path.join(output_dir, f"debate_bg_{fmt}.png")
                backend_used = "unknown"

                # Try Pollinations first if requested
                if image_gen_backend == "pollinations":
                    if self._pollinations_image(debate_background_prompt, w, h, png_path):
                        backend_used = "pollinations"
                    else:
                        print(f"[DebateBg]   ⚠️ Pollinations failed — falling back to gradient")

                # Use image_gen_tool (gradient / lcm_onnx / auto)
                if not os.path.exists(png_path):
                    if _IMAGE_GEN_AVAILABLE:
                        img_backend = "auto" if image_gen_backend in ("auto", "lcm_onnx") else "gradient"
                        print(f"[DebateBg]   🎨 image_gen_tool backend={img_backend}")
                        png_result = generate_background(
                            prompt=debate_background_prompt,
                            width=min(w, 1920),
                            height=min(h, 1080),
                            output_path=png_path,
                            backend=img_backend,
                        )
                        if png_result and os.path.exists(png_result):
                            png_path     = png_result
                            backend_used = img_backend
                        else:
                            raise RuntimeError("image_gen_tool returned no file")
                    else:
                        print(f"[DebateBg]   🎨 FFmpeg gradient fallback")
                        self._ffmpeg_gradient_png(w, h, png_path, debate_background_prompt)
                        backend_used = "ffmpeg-gradient"

                if not os.path.exists(png_path):
                    raise RuntimeError(f"PNG generation failed: {png_path}")

                png_kb = os.path.getsize(png_path) // 1024
                print(f"[DebateBg]   ✅ PNG ready: {png_kb} KB  ({backend_used})")

                # ── Step 2: Animate PNG → video ───────────────────────────
                anim_backend = self._png_to_video(png_path, out_bg, w, h, duration, video_fps)
                backend_used = f"{backend_used}+{anim_backend}"

                # ── Cleanup source PNG ────────────────────────────────────
                if os.path.exists(png_path):
                    os.remove(png_path)

                if os.path.exists(out_bg):
                    kb = os.path.getsize(out_bg) // 1024
                    results.append(f"✅ {fmt}: debate_bg_{fmt}.mp4 ({kb} KB) [{backend_used}]")
                    print(f"[DebateBg] ✅ {fmt}: {kb} KB via [{backend_used}]")
                else:
                    errors.append(f"❌ {fmt}: video not created after animation step")

            except Exception as e:
                import traceback
                traceback.print_exc()
                errors.append(f"❌ {fmt}: {e}")

        if not results:
            return "❌ Debate background failed:\n" + "\n".join(errors)

        out = "🎨 Debate backgrounds created:\n" + "\n".join(f"   • {r}" for r in results)
        if errors:
            out += "\n⚠️ Errors:\n" + "\n".join(errors)
        return out


    # ══════════════════════════════════════════════════════════════════════
    # PNG → Animated Video (Ken Burns zoom+pan)
    # ══════════════════════════════════════════════════════════════════════

    def _png_to_video(self, png_path, out_path, w, h, duration, fps) -> str:
        """Animate static PNG with Ken Burns effect via FFmpeg zoompan filter."""
        total_frames = int(duration * fps)
        zoom_delta   = 0.15 / max(total_frames, 1)

        # Try Ken Burns zoom+pan
        try:
            vf = (
                f"scale={w*2}:{h*2}:flags=lanczos,"
                f"zoompan="
                f"z='min(zoom+{zoom_delta:.7f},1.15)':"
                f"x='iw/2-(iw/zoom/2)+sin(on/{fps*10:.1f})*8':"
                f"y='ih/2-(ih/zoom/2)':"
                f"d={total_frames}:"
                f"s={w}x{h}:"
                f"fps={fps},"
                f"unsharp=3:3:0.5"
            )
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", png_path,
                "-vf", vf,
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "22", "-pix_fmt", "yuv420p",
                "-r", str(fps), out_path
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode == 0 and os.path.exists(out_path):
                return "ken-burns"
            print(f"[DebateBg]   ⚠️ Ken Burns failed: {r.stderr.decode()[:150]}")
        except Exception as e:
            print(f"[DebateBg]   ⚠️ Ken Burns error: {e}")

        # Fallback: simple scale + loop (no zoom)
        try:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", png_path,
                "-vf", f"scale={w}:{h}:flags=lanczos,format=yuv420p",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "22", "-r", str(fps), out_path
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode == 0 and os.path.exists(out_path):
                return "simple-loop"
            print(f"[DebateBg]   ⚠️ Simple loop failed: {r.stderr.decode()[:100]}")
        except Exception as e:
            print(f"[DebateBg]   ⚠️ Simple loop error: {e}")

        return "failed"


    # ══════════════════════════════════════════════════════════════════════
    # Pollinations.ai image download
    # ══════════════════════════════════════════════════════════════════════

    def _pollinations_image(self, prompt, w, h, out_path) -> bool:
        """Try to download image from Pollinations.ai API."""
        try:
            print(f"[DebateBg]   🌐 Trying Pollinations.ai...")
            encoded = urllib.parse.quote(f"{prompt}, high quality, cinematic, no text")
            url     = (
                f"https://image.pollinations.ai/prompt/{encoded}"
                f"?width={min(w,1920)}&height={min(h,1080)}"
                f"&nologo=true&model=flux&enhance=true"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()

            if len(data) < 10000:
                print(f"[DebateBg]   ⚠️ Pollinations: too small ({len(data)}B)")
                return False

            with open(out_path, 'wb') as f:
                f.write(data)
            print(f"[DebateBg]   ✅ Pollinations: {len(data)//1024} KB")
            return True

        except Exception as e:
            print(f"[DebateBg]   ⚠️ Pollinations failed: {e}")
            return False


    # ══════════════════════════════════════════════════════════════════════
    # FFmpeg gradient PNG (when image_gen_tool unavailable)
    # ══════════════════════════════════════════════════════════════════════

    def _ffmpeg_gradient_png(self, w, h, out_path, prompt=""):
        """Generate static gradient PNG via FFmpeg lavfi geq filter."""
        r1, g1, b1 = self._prompt_to_color(prompt)
        r2 = min(255, r1 + 20)
        g2 = min(255, g1 + 25)
        b2 = min(255, b1 + 55)
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", (
                f"color=c=0x{r1:02x}{g1:02x}{b1:02x}:s={w}x{h}:r=1,"
                f"geq="
                f"r='{r1}+({r2}-{r1})*Y/{h}':"
                f"g='{g1}+({g2}-{g1})*Y/{h}':"
                f"b='{b1}+({b2}-{b1})*Y/{h}'"
            ),
            "-frames:v", "1", out_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            print(f"[DebateBg]   ⚠️ FFmpeg gradient PNG failed: {result.stderr.decode()[:100]}")


    def _prompt_to_color(self, prompt: str):
        """Extract primary RGB from prompt keywords."""
        p = prompt.lower()
        if "navy"   in p: return (8,  15, 45)
        if "purple" in p: return (20,  8, 45)
        if "teal"   in p: return (5,  35, 45)
        if "red"    in p: return (40,  5, 10)
        if "green"  in p: return (5,  30, 15)
        if "gold"   in p: return (30, 20,  5)
        if "cyber"  in p: return (5,  20, 30)
        return (8, 10, 35)  # default: dark navy


    def _get_duration(self, video_path: str) -> float:
        """Get video duration via ffprobe."""
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", video_path],
                capture_output=True, text=True
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0
