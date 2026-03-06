import shutil
import os
import multiprocessing
from typing import Type, Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.max_open_warning'] = 0

# ── Input Schema ───────────────────────────────────────────────────────────
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

    # Intro settings — 0 or null = auto-calculate from audio
    intro_enabled: bool = Field(default=True, description="Generate intro clip(s)")
    intro_duration: int = Field(default=0, description="Duration of intro in seconds for Shorts/portrait formats. 0 = auto from audio")
    intro_duration_hd: int = Field(default=0, description="Duration of intro in seconds for HD/landscape formats. 0 = auto from audio")

    # Branding
    channel: str = Field(default="PlayOwnAi", description="Channel name shown on intro screen")

    # Watermark (optional overlay)
    watermark_enabled: bool = Field(default=False, description="Add semi-transparent watermark")
    watermark_text: str = Field(default="@PlayOwnAi", description="Watermark text")
    watermark_opacity: int = Field(default=60, ge=0, le=255, description="Watermark opacity (0-255)")

    # Audio
    audio_speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed for Shorts/portrait via ffmpeg atempo.")
    audio_speed_hd: float = Field(default=0.0, ge=0.0, le=2.0, description="Speech speed for HD/landscape. 0.0 = use audio_speed.")

    # FPS
    video_fps: int = Field(default=30, description="Output video frame rate. Must match all other tools. Default: 30.")

    # Context label — drives narration wording (bar_race | debate | definition | custom)
    intro_context: str = Field(default="bar_race", description="Context label: bar_race | debate | definition | custom string")
    intro_slug: str    = Field(default="", description="Optional custom line 2 text — overrides context label when set")

    # Background color
    bg_color: tuple = Field(default=(20, 20, 40), description="RGB background color")

# ── Resolution map (matches bar_race_video_tool.py conventions) ───────────
RESOLUTIONS = {
    "HD":       (1920, 1080),
    "2K":       (2560, 1440),
    "4K":       (3840, 2160),
    "8K":       (7680, 4320),
    "Shorts":   (1080, 1920),
    "ShortsHD": (1080, 1920),
    "Shorts4K": (2160, 3840),
}

def _clean_text(text: str) -> str:
    """Strip unicode math italic/bold to plain ASCII so fonts can render them."""
    import unicodedata
    replacements = {
        '–': '-', '—': '--', '…': '...',
        '‘': "'", '’': "'", '"': '"', '"': '"',
    }
    for uni, asc in replacements.items():
        text = text.replace(uni, asc)
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('ascii')

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

# ── Tool ───────────────────────────────────────────────────────────────────
class IntroClipTool(BaseTool):
    """
    Generates intro screen video clip(s) for bar race videos.
    Creates a branded intro card (channel name + topic + year range)
    for each requested video format (HD, Shorts, 2K, 4K, etc.).
    Optionally overlays a semi-transparent watermark.
    Triggered by intro_enabled=true in data.json.

    AUTO-DURATION MODE:
    Set intro_duration=0 or intro_duration_hd=0 to auto-calculate from audio length.
    """
    name: str = "Intro Clip Tool"
    description: str = (
        "Creates branded intro screen MP4 clip(s) for bar race videos.  "
        "Supports HD, Shorts, 2K, 4K formats.  "
        "Set intro_duration=0 for auto-duration from audio.  "
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
        intro_duration: int = 0,
        intro_duration_hd: int = 0,
        channel: str = "PlayOwnAi",
        watermark_enabled: bool = False,
        watermark_text: str = "@PlayOwnAi",
        watermark_opacity: int = 60,
        bg_color: tuple = (20, 20, 40),
        intro_context: str = "bar_race",
        intro_slug: str = "",
        audio_speed: float = 1.0,
        audio_speed_hd: float = 0.0,
        video_fps: int = 30,
    ) -> str:

        # --- SKIP ---
        if not intro_enabled:
            return "🔇 Intro clip skipped (intro_enabled=false)"

        if video_formats is None:
            video_formats = ["Shorts", "HD"]

        # --- DEPENDENCY CHECK ---
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "❌ FATAL: Pillow not installed. Run: pip install Pillow"

        if not shutil.which('ffmpeg'):
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        try:
            from gtts import gTTS
        except ImportError:
            return "❌ FATAL: gTTS not installed. Run: pip install gTTS"

        os.makedirs(output_dir, exist_ok=True)

        results = []
        errors = []

        for fmt in video_formats:
            fmt = fmt.strip()
            if fmt not in RESOLUTIONS:
                errors.append(f"⚠️ Unknown format '{fmt}', skipping.")
                continue

            try:
                # ✅ SMART SKIP — check what already exists
                silent_video = os.path.join(output_dir, f"intro_{fmt}.mp4")
                audio_file = os.path.join(output_dir, f"intro_{fmt}_audio.mp3")
                final_merged = os.path.join(output_dir, f"intro_{fmt}_with_audio.mp4")

                # Skip everything if final merged exists
                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped (final exists: {os.path.basename(final_merged)})")
                    continue

                # Per-format duration — 0 = auto from audio
                is_portrait_fmt = RESOLUTIONS[fmt][1] > RESOLUTIONS[fmt][0]
                fmt_duration = (
                    intro_duration if is_portrait_fmt
                    else (intro_duration_hd if intro_duration_hd > 0 else intro_duration)
                )

                # Check if auto-duration mode (0 or null)
                auto_duration = (fmt_duration == 0 or fmt_duration is None)

                print(f"[IntroClipTool] {fmt} duration: {'AUTO (from audio)' if auto_duration else f'{fmt_duration}s'} ({'portrait' if is_portrait_fmt else 'landscape'})")

                # Build narration text
                is_portrait_fmt2 = RESOLUTIONS[fmt][1] > RESOLUTIONS[fmt][0]
                spd = audio_speed if is_portrait_fmt2 else (audio_speed_hd if audio_speed_hd > 0.0 else audio_speed)

                # intro_slug overrides context label when provided
                _slug = intro_slug.strip() if intro_slug else ""
                if not _slug:
                    _ctx = intro_context.strip().lower() if intro_context else "bar_race"
                    _ctx_labels = {
                        "bar_race":    "Watch the race — see how the leaders change over time.",
                        "debate":      "One of the biggest debates right now.",
                        "definition":  "Let's explore what this really means.",
                    }
                    _slug = _ctx_labels.get(_ctx, intro_context.replace("_", " ").title())

                narration_parts = [
                    f"Welcome to {channel}.",
                    f"Exploring {topic}. {_slug}",
                ]
                narration = "   ".join(narration_parts)

                # Save narration as cc_en.txt alongside video
                cc_path = os.path.join(output_dir, f"intro_{fmt}_cc_en.txt")
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(narration)
                print(f"[IntroClipTool] 📝 Narration saved: {cc_path} ({len(narration)} chars)")

                # ── AUDIO FIRST (for auto-duration mode) ───────────────────
                audio_path = os.path.join(output_dir, f"intro_{fmt}_audio.mp3")
                audio_duration = fmt_duration

                if auto_duration or not os.path.exists(silent_video):
                    # Generate audio first to measure duration
                    print(f"[IntroClipTool] 🎙 Generating {fmt} intro audio (speed={spd}) → {audio_path}")
                    try:
                        self._generate_audio(narration, audio_path, spd)
                        if os.path.exists(audio_path):
                            audio_duration = self._get_duration(audio_path)
                            print(f"[IntroClipTool] 🔊 Audio duration: {audio_duration:.1f}s")
                        else:
                            errors.append(f"⚠️ {fmt} audio failed to generate")
                            audio_duration = fmt_duration if fmt_duration > 0 else 10
                    except Exception as ae:
                        errors.append(f"⚠️ {fmt} audio failed: {ae}")
                        audio_duration = fmt_duration if fmt_duration > 0 else 10
                else:
                    # Audio exists from previous run
                    if os.path.exists(audio_path):
                        audio_duration = self._get_duration(audio_path)
                        print(f"[IntroClipTool] 🔊 Using existing audio: {audio_duration:.1f}s")

                # ── VIDEO RENDER ───────────────────────────────────────────
                if os.path.exists(silent_video):
                    print(f"[IntroClipTool] ⏭️ {fmt}: Silent video exists — skipping render")
                    output_path = silent_video
                else:
                    # Render silent video with calculated duration
                    output_path = os.path.join(output_dir, f"intro_{fmt}.mp4")
                    print(f"[IntroClipTool] 🎬 Rendering {fmt} video ({audio_duration:.1f}s)...")
                    self._create_intro_clip(
                        fmt=fmt,
                        duration=audio_duration,  # ✅ Use audio duration
                        output_path=output_path,
                        topic=topic,
                        start_year=start_year,
                        end_year=end_year,
                        channel=channel,
                        bg_color=bg_color,
                        watermark_enabled=watermark_enabled,
                        watermark_text=watermark_text,
                        watermark_opacity=watermark_opacity,
                        video_fps=video_fps,
                    )

                if not os.path.exists(output_path):
                    errors.append(f"❌ {fmt}: video file not created")
                    continue

                size_kb = os.path.getsize(output_path) // 1024
                print(f"[IntroClipTool] ✅ {fmt} video created ({size_kb} KB)")

                # ── MERGE: bake audio into video → intro_{fmt}_with_audio.mp4 ──
                merged_path = os.path.join(output_dir, f"intro_{fmt}_with_audio.mp4")
                if audio_path and os.path.exists(audio_path):
                    import subprocess as _sp
                    merge_cmd = [
                        'ffmpeg', '-y',
                        '-i', output_path,
                        '-i', audio_path,
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-shortest',
                        merged_path,
                    ]
                    merge_result = _sp.run(merge_cmd, capture_output=True, check=False)
                    if merge_result.returncode == 0 and os.path.exists(merged_path):
                        merged_kb = os.path.getsize(merged_path) // 1024
                        results.append(f"intro_{fmt}.mp4 ({size_kb} KB) + audio → intro_{fmt}_with_audio.mp4 ({merged_kb} KB, {audio_duration:.1f}s)")
                        print(f"[IntroClipTool] ✅ {fmt} merged: intro_{fmt}_with_audio.mp4 ({merged_kb} KB, {audio_duration:.1f}s)")
                    else:
                        results.append(f"intro_{fmt}.mp4 ({size_kb} KB) [audio merge failed]")
                        errors.append(f"⚠️ {fmt} merge failed: {merge_result.stderr.decode()[:150]}")
                else:
                    results.append(f"intro_{fmt}.mp4 ({size_kb} KB) [no audio]")

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

    # ── Core: create a single intro clip for one format ───────────────────
    def _create_intro_clip(
        self,
        fmt: str,
        duration: float,  # ✅ Now float for auto-duration
        output_path: str,
        topic: str,
        start_year: int,
        end_year: int,
        channel: str,
        bg_color: tuple,
        watermark_enabled: bool,
        watermark_text: str,
        watermark_opacity: int,
        video_fps: int = 30,
    ):
        import subprocess
        from PIL import Image, ImageDraw, ImageFont

        width, height = RESOLUTIONS[fmt]
        title_size, subtitle_size = FONT_SCALE[fmt]
        is_portrait = height > width
        fps = video_fps

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
        topic = _clean_text(topic)
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

        # --- CONVERT PNG → MP4 via ffmpeg ---
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', temp_img_path,
            '-t', str(duration),  # ✅ Float duration supported
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

    # ── Helpers ────────────────────────────────────────────────────────────
    def _generate_audio(self, text: str, output_path: str, speed: float):
        """Generate MP3 from text via gTTS + ffmpeg atempo speed control."""
        from gtts import gTTS
        import subprocess
        import threading
        import time

        label = os.path.basename(output_path)
        print(f"[IntroClipTool] ⏱ {label} — generating audio ({len(text)} chars)")

        _stop = threading.Event()
        def _ticker(lbl, start):
            while not _stop.is_set():
                time.sleep(5)
                if not _stop.is_set():
                    print(f"[IntroClipTool] ⏳ {lbl} ... {int(time.time()-start)}s")
        t_start = time.time()
        ticker = threading.Thread(target=_ticker, args=(label, t_start), daemon=True)
        ticker.start()

        result = None
        try:
            temp_path = output_path.replace('.mp3', '_temp.mp3')
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(temp_path)
            atempo = max(0.5, min(2.0, speed))
            result = subprocess.run([
                'ffmpeg', '-y', '-i', temp_path,
                '-filter:a', f'atempo={atempo}',
                output_path
            ], capture_output=True, check=False)
        finally:
            _stop.set()
            ticker.join(timeout=1)

        if os.path.exists(temp_path):
            os.remove(temp_path)

        elapsed = time.time() - t_start
        if result and result.returncode != 0 and not os.path.exists(output_path):
            raise RuntimeError(f"ffmpeg atempo failed: {result.stderr.decode()[:200]}")

        size_kb = os.path.getsize(output_path) // 1024 if os.path.exists(output_path) else 0
        print(f"[IntroClipTool] ✅ {label} audio done in {elapsed:.1f}s ({size_kb}KB)")

    def _get_duration(self, media_path: str) -> float:
        """Get media duration in seconds via ffprobe."""
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", media_path],
            capture_output=True, text=True
        )
        try:
            return float(r.stdout.strip())
        except Exception:
            return 0.0

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
