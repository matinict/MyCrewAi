import shutil
import os
import multiprocessing
from typing import Type, Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.max_open_warning'] = 0


# ---------------------------------------------------------------------------
# Input Schema
# ---------------------------------------------------------------------------

class IntroClipToolInput(BaseModel):
    """Input schema for IntroClipTool."""
    topic: str = Field(..., description="Topic name (e.g. 'LLM Popularity')")
    start_year: int = Field(..., description="First year in the dataset")
    end_year: int = Field(..., description="Last year in the dataset")
    output_dir: str = Field(..., description="Directory to save the intro clip(s)")

    # Format control
    video_formats: list = Field(
        default=["Shorts", "HD"],
        description="Formats to generate intro for: 'HD', 'Shorts', '2K', '4K', 'Shorts4K'"
    )

    # Intro settings
    intro_enabled: bool = Field(default=True, description="Generate intro clip(s)")
    intro_duration: int = Field(default=10, description="Duration of intro in seconds for Shorts/portrait formats")
    intro_duration_hd: int = Field(default=15, description="Duration of intro in seconds for HD/landscape formats. 0 = use intro_duration for all formats.")

    # Branding
    channel: str = Field(default="PlayOwnAi", description="Channel name shown on intro screen")

    # Watermark (optional overlay)
    watermark_enabled: bool = Field(default=False, description="Add semi-transparent watermark")
    watermark_text: str = Field(default="@PlayOwnAi", description="Watermark text")
    watermark_opacity: int = Field(default=60, ge=0, le=255, description="Watermark opacity (0-255)")

    # Background color
    bg_color: tuple = Field(default=(20, 20, 40), description="RGB background color")


# ---------------------------------------------------------------------------
# Resolution map (matches bar_race_video_tool.py conventions)
# ---------------------------------------------------------------------------

RESOLUTIONS = {
    "HD":       (1920, 1080),
    "2K":       (2560, 1440),
    "4K":       (3840, 2160),
    "8K":       (7680, 4320),
    "Shorts":   (1080, 1920),
    "ShortsHD": (1080, 1920),
    "Shorts4K": (2160, 3840),
}

FONT_SCALE = {
    "HD":       (160, 65),    # (title_size, subtitle_size)
    "2K":       (213, 87),
    "4K":       (320, 130),
    "8K":       (640, 260),
    "Shorts":   (114, 48),    # portrait: ~0.71x of HD
    "ShortsHD": (114, 48),
    "Shorts4K": (227, 96),
}

OPTIMAL_THREADS = min(multiprocessing.cpu_count(), 6)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class IntroClipTool(BaseTool):
    """
    Generates intro screen video clip(s) for bar race videos.
    Creates a branded intro card (channel name + topic + year range)
    for each requested video format (HD, Shorts, 2K, 4K, etc.).
    Optionally overlays a semi-transparent watermark.
    Triggered by intro_enabled=true in data.json.
    """
    name: str = "Intro Clip Tool"
    description: str = (
        "Creates branded intro screen MP4 clip(s) for bar race videos. "
        "Supports HD, Shorts, 2K, 4K formats. "
        "Triggered by intro_enabled=true."
    )
    args_schema: Type[BaseModel] = IntroClipToolInput

    def _run(
        self,
        topic: str,
        start_year: int,
        end_year: int,
        output_dir: str,
        video_formats: list = None,
        intro_enabled: bool = True,
        intro_duration: int = 10,
        intro_duration_hd: int = 15,
        channel: str = "PlayOwnAi",
        watermark_enabled: bool = False,
        watermark_text: str = "@PlayOwnAi",
        watermark_opacity: int = 60,
        bg_color: tuple = (20, 20, 40),
    ) -> str:

        # --- SKIP ---
        if not intro_enabled:
            return "🔇 Intro clip skipped (intro_enabled=false)"

        if video_formats is None:
            video_formats = ["Shorts", "HD"]

        # --- DEPENDENCY CHECK ---
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        except ImportError:
            return "❌ FATAL: Pillow not installed. Run: pip install Pillow"

        if not shutil.which('ffmpeg'):
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        os.makedirs(output_dir, exist_ok=True)

        results = []
        errors = []

        for fmt in video_formats:
            fmt = fmt.strip()
            if fmt not in RESOLUTIONS:
                errors.append(f"⚠️ Unknown format '{fmt}', skipping.")
                continue

            try:
                output_path = os.path.join(output_dir, f"intro_{fmt}.mp4")
                print(f"[IntroClipTool] Generating {fmt} intro → {output_path}")

                # Per-format duration: landscape formats use intro_duration_hd,
                # portrait formats use intro_duration
                is_portrait_fmt = RESOLUTIONS[fmt][1] > RESOLUTIONS[fmt][0]
                fmt_duration = (
                    intro_duration if is_portrait_fmt
                    else (intro_duration_hd if intro_duration_hd > 0 else intro_duration)
                )
                print(f"[IntroClipTool] {fmt} duration: {fmt_duration}s ({'portrait' if is_portrait_fmt else 'landscape'})")
                self._create_intro_clip(
                    fmt=fmt,
                    duration=fmt_duration,
                    output_path=output_path,
                    topic=topic,
                    start_year=start_year,
                    end_year=end_year,
                    channel=channel,
                    bg_color=tuple(bg_color),
                    watermark_enabled=watermark_enabled,
                    watermark_text=watermark_text,
                    watermark_opacity=watermark_opacity,
                )

                if os.path.exists(output_path):
                    size_kb = os.path.getsize(output_path) // 1024
                    results.append(f"intro_{fmt}.mp4 ({size_kb} KB)")
                    print(f"[IntroClipTool] ✅ {fmt} intro created ({size_kb} KB)")
                else:
                    errors.append(f"❌ {fmt}: file not created")

            except Exception as e:
                errors.append(f"❌ {fmt}: {e}")
                import traceback
                print(f"[IntroClipTool] ERROR for {fmt}: {traceback.format_exc()}")

        if not results:
            return "❌ Intro clip generation failed.\n" + "\n".join(errors)

        summary = (
            "🎬 Intro clips created:\n"
            + "\n".join([f"   • {r}" for r in results])
        )
        if errors:
            summary += "\n\n⚠️ Some issues:\n" + "\n".join(errors)
        return summary

    # -----------------------------------------------------------------------
    # Core: create a single intro clip for one format
    # -----------------------------------------------------------------------

    def _create_intro_clip(
        self,
        fmt: str,
        duration: int,
        output_path: str,
        topic: str,
        start_year: int,
        end_year: int,
        channel: str,
        bg_color: tuple,
        watermark_enabled: bool,
        watermark_text: str,
        watermark_opacity: int,
    ):
        import subprocess
        from PIL import Image, ImageDraw, ImageFont

        width, height = RESOLUTIONS[fmt]
        title_size, subtitle_size = FONT_SCALE[fmt]
        is_portrait = height > width
        fps = 30

        # --- BACKGROUND ---
        img = Image.new('RGB', (width, height), color=tuple(bg_color))
        draw = ImageDraw.Draw(img)

        # --- FONTS ---
        title_font, subtitle_font = self._load_fonts(title_size, subtitle_size)

        # --- CHANNEL NAME (top third) ---
        cx = width // 2
        channel_y = height // 3
        draw.text((cx, channel_y), channel, fill='white', font=title_font, anchor='mm')

        # --- TOPIC LINES (center) ---
        topic_words = topic.split()
        max_words_per_line = 2 if is_portrait else 4
        subtitle_lines = []
        current_line = []
        for word in topic_words:
            current_line.append(word)
            if len(current_line) >= max_words_per_line or len(' '.join(current_line)) > 20:
                subtitle_lines.append(' '.join(current_line))
                current_line = []
        if current_line:
            subtitle_lines.append(' '.join(current_line))
        subtitle_lines.append(f"{start_year} - {end_year}")

        line_spacing = subtitle_size + int(subtitle_size * 0.4)
        total_block_h = len(subtitle_lines) * line_spacing
        y_offset = height // 2 - total_block_h // 2 + height // 8

        for line in subtitle_lines:
            draw.text((cx, y_offset), line, fill='lightblue', font=subtitle_font, anchor='mm')
            y_offset += line_spacing

        # --- WATERMARK (optional) ---
        if watermark_enabled:
            img = self._add_watermark(img, watermark_text, watermark_opacity, width, height, subtitle_size)

        # --- SAVE FRAME PNG ---
        temp_img_path = output_path.replace('.mp4', '_frame.png')
        img.save(temp_img_path)

        # --- CONVERT PNG → MP4 via ffmpeg (no moviepy needed) ---
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', temp_img_path,
            '-t', str(duration),
            '-c:v', 'libx264',
            '-preset', 'faster',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-r', str(fps),
            '-threads', str(OPTIMAL_THREADS),
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:300]}")

        # --- CLEANUP ---
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _load_fonts(self, title_size: int, subtitle_size: int):
        from PIL import ImageFont

        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            'C:\\Windows\\Fonts\\arialbd.ttf',
        ]
        title_font = subtitle_font = None
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    title_font = ImageFont.truetype(fp, title_size)
                    subtitle_font = ImageFont.truetype(fp, subtitle_size)
                    break
                except Exception:
                    continue

        if title_font is None:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()

        return title_font, subtitle_font

    def _add_watermark(
        self,
        base_img,
        watermark_text: str,
        opacity: int,
        width: int,
        height: int,
        ref_size: int,
    ):
        from PIL import Image, ImageDraw, ImageFont

        wm_size = max(ref_size, int(width * 0.06))
        _, wm_font = self._load_fonts(wm_size, wm_size)

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        bbox = draw.textbbox((0, 0), watermark_text, font=wm_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (width - tw) // 2
        ty = (height - th) // 2
        draw.text((tx, ty), watermark_text, fill=(255, 255, 255, opacity), font=wm_font)

        base_rgba = base_img.convert('RGBA')
        combined = Image.alpha_composite(base_rgba, overlay)
        return combined.convert('RGB')
