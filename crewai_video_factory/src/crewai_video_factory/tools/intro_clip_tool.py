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
    start_year: Optional[int] = Field(default=None, description="First year. Omit or null for debate/timeless topics.")
    end_year: Optional[int] = Field(default=None, description="Last year. Omit or null for debate/timeless topics.")
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

    # Language suffix for output filenames
    lang_suffix: str = Field(default="En", description="Language suffix appended to output filenames. e.g. 'En', 'Bn', 'Fr'")

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
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        output_dir: str = "output",
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
        lang_suffix: str = "En",
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
                _lang = lang_suffix if lang_suffix else "En"
                silent_video = os.path.join(output_dir, f"intro_{fmt}_{_lang}.mp4")
                audio_file = os.path.join(output_dir, f"intro_{fmt}_{_lang}_audio.mp3")
                final_merged = os.path.join(output_dir, f"intro_{fmt}_{_lang}_with_audio.mp4")

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
                    f"Welcome to {channel}. ",
                    f"Exploring {topic}. ",
                ]

                # Add slug to narration if provided
                _slug = intro_slug.strip() if intro_slug else ""
                if not _slug:
                    _ctx = intro_context.strip().lower() if intro_context else "bar_race"
                    _ctx_labels = {
                        "bar_race":     "Watch the race — see how the leaders change over time. ",
                        "debate":       "One of the biggest debates in tech right now. ",  # ✅ ADDED
                        "definition":   "Let's explore what this really means. ",
                    }
                    _slug = _ctx_labels.get(_ctx, intro_context.replace("_", "  ").title())

                if _slug:
                    narration_parts.append(f"{_slug} ")  # ✅ ADD SLUG TO AUDIO

                narration = "  ".join(narration_parts)

                # Save narration as cc_en.txt alongside video
                cc_path = os.path.join(output_dir, f"intro_{fmt}_{_lang}_cc.txt")
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(narration)
                print(f"[IntroClipTool] 📝 Narration saved: {cc_path} ({len(narration)} chars)")

                # ── AUDIO FIRST (for auto-duration mode) ───────────────────
                audio_path = os.path.join(output_dir, f"intro_{fmt}_{_lang}_audio.mp3")
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
                    output_path = os.path.join(output_dir, f"intro_{fmt}_{_lang}.mp4")
                    print(f"[IntroClipTool] 🎬 Rendering {fmt} video ({audio_duration:.1f}s)...")
                    self._create_intro_clip(
                        fmt=fmt,
                        duration=audio_duration,  # ✅ Use audio duration
                        output_path=output_path,
                        topic=topic,
                        start_year=start_year,
                        end_year=end_year,
                        channel=channel,
                        slug=_slug,
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
                merged_path = os.path.join(output_dir, f"intro_{fmt}_{_lang}_with_audio.mp4")
                if audio_path and os.path.exists(audio_path):
                    import subprocess as _sp
                    merge_cmd = [
                        'ffmpeg', '-y',
                        '-i', output_path,
                        '-i', audio_path,
                        '-c:v', 'copy',
                        '-c:a', 'aac', '-ar', '44100', '-ac', '1',
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
        duration: float,
        output_path: str,
        topic: str,
        start_year,
        end_year,
        channel: str,
        watermark_enabled: bool,
        watermark_text: str,
        watermark_opacity: int,
        slug: str = "",
        bg_color: tuple = (20, 20, 40),
        video_fps: int = 30,
    ):
        import subprocess, math, random, tempfile
        from PIL import Image, ImageDraw, ImageFont, ImageFilter

        width, height = RESOLUTIONS[fmt]
        title_size, subtitle_size = FONT_SCALE[fmt]
        is_portrait = height > width
        fps         = video_fps
        total_frames = max(1, int(duration * fps))

        # ── Text elements ──────────────────────────────────────────────────
        topic_clean  = _clean_text(topic)
        channel_clean = _clean_text(channel)

        # Wrap topic into lines
        max_words = 2 if is_portrait else 4
        words, current, lines = topic_clean.split(), [], []
        for w in words:
            current.append(w)
            if len(current) >= max_words or len(' '.join(current)) > 20:
                lines.append(' '.join(current)); current = []
        if current: lines.append(' '.join(current))

        # Year line (only if valid)
        year_line = None
        try:
            sy, ey = int(start_year or 0), int(end_year or 0)
            if sy > 0 and ey > 0:
                year_line = f"{sy} - {ey}"
        except Exception:
            pass

        # Slug line — wrap into short lines so it fits within frame width
        slug_lines = []
        if slug and slug.strip():
            _slug_raw = _clean_text(slug.strip())
            _slug_words = _slug_raw.split()
            _max_slug_words = 4 if is_portrait else 6   # tighter wrap for long slugs
            _cur = []
            for _w in _slug_words:
                _cur.append(_w)
                if len(_cur) >= _max_slug_words or len(' '.join(_cur)) > 22:
                    slug_lines.append(' '.join(_cur)); _cur = []
            if _cur:
                slug_lines.append(' '.join(_cur))
        slug_clean = slug_lines[0] if slug_lines else ""   # keep for colour-check

        all_sub_lines = lines + ([year_line] if year_line else []) + slug_lines

        title_font, subtitle_font = self._load_fonts(title_size, subtitle_size)
        slug_size = max(18, int(subtitle_size * 0.72))
        _, slug_font = self._load_fonts(title_size, slug_size)

        # ── Particle seeds (random but deterministic) ──────────────────────
        random.seed(42)
        n_particles = max(30, width // 30)
        particles = [
            {
                'x':  random.randint(0, width),
                'y':  random.randint(0, height),
                'vy': random.uniform(0.3, 1.2) * (height / 1080),
                'r':  random.randint(2, 5),
                'alpha': random.randint(60, 180),
            }
            for _ in range(n_particles)
        ]

        # ── Animation timing (fraction of total_frames) ────────────────────
        #   0.00 – 0.25  channel fades+scales in
        #   0.25 – 0.75  topic lines slide up one by one
        #   0.75 – 1.00  year line pulses in (hold)
        ch_start, ch_end   = 0.00, 0.25
        sub_start, sub_end = 0.25, 0.75
        yr_start           = 0.75

        sub_per = (sub_end - sub_start) / max(len(all_sub_lines), 1)

        # ── Gradient palette ───────────────────────────────────────────────
        # Deep space → electric purple → neon cyan animated slow drift
        def gradient_bg(frame_idx):
            shift = (frame_idx / max(total_frames, 1)) * math.pi * 2
            img = Image.new('RGB', (width, height))
            px = img.load()
            for y in range(height):
                t = y / height
                # base: deep navy to dark purple
                r0 = int(8  + 20  * t)
                g0 = int(6  + 10  * t)
                b0 = int(30 + 60  * t)
                # animated shimmer wave
                wave = 0.5 + 0.5 * math.sin(shift + t * math.pi * 3)
                # inject cyan/purple glow band
                r1 = int(min(255, r0 + 80  * wave * (1 - t)))
                g1 = int(min(255, g0 + 40  * wave * t))
                b1 = int(min(255, b0 + 120 * wave))
                for x in range(width):
                    px[x, y] = (r1, g1, b1)
            return img

        # ── Glow helper: draw text with a soft halo ────────────────────────
        def draw_text_glow(draw, pos, text, font, color, glow_color, anchor='mm', glow_r=3):
            cx2, cy2 = pos
            for dx in range(-glow_r, glow_r+1, glow_r):
                for dy in range(-glow_r, glow_r+1, glow_r):
                    if dx == 0 and dy == 0: continue
                    draw.text((cx2+dx, cy2+dy), text, fill=glow_color, font=font, anchor=anchor)
            draw.text(pos, text, fill=color, font=font, anchor=anchor)

        # ── Per-element alpha easing (smooth in/out) ───────────────────────
        def ease_in_out(t):
            return t * t * (3 - 2 * t)

        def alpha_for(t_global, t_in, t_out, hold_end=1.0):
            """Returns 0-255 alpha. Fades in at t_in, holds to hold_end, fades at t_out."""
            if t_global < t_in:   return 0
            if t_global < t_out:  return int(255 * ease_in_out((t_global - t_in) / max(t_out - t_in, 0.001)))
            if t_global < hold_end: return 255
            return int(255 * (1 - ease_in_out((t_global - hold_end) / max(1.0 - hold_end, 0.001))))

        # ── Layout positions ───────────────────────────────────────────────
        cx = width // 2
        # Channel name: upper third
        ch_y = int(height * 0.30)
        # Topic block: centered lower half
        line_h      = subtitle_size + int(subtitle_size * 0.5)
        slug_line_h = slug_size + int(slug_size * 0.5)
        # block height: topic/year lines use line_h, slug lines use slug_line_h
        n_slug = len(slug_lines)
        n_other = len(all_sub_lines) - n_slug
        block_h = n_other * line_h + n_slug * slug_line_h
        block_y = int(height * 0.52) - block_h // 2

        # ── Render frames into temp dir ────────────────────────────────────
        tmpdir = tempfile.mkdtemp(prefix='intro_frames_')
        try:
            for fi in range(total_frames):
                t = fi / max(total_frames - 1, 1)   # 0.0 → 1.0

                # Background (animated gradient)
                img  = gradient_bg(fi)
                base = img.convert('RGBA')
                overlay = Image.new('RGBA', (width, height), (0,0,0,0))
                draw = ImageDraw.Draw(overlay)

                # ── Particles ─────────────────────────────────────────────
                for p in particles:
                    px_x = int(p['x'])
                    px_y = int((p['y'] + fi * p['vy']) % height)
                    r = p['r']
                    a = p['alpha']
                    draw.ellipse(
                        [px_x - r, px_y - r, px_x + r, px_y + r],
                        fill=(180, 220, 255, a)
                    )

                # ── Channel name ───────────────────────────────────────────
                ch_t_local = (t - ch_start) / max(ch_end - ch_start, 0.001)
                ch_t_local = max(0.0, min(1.0, ch_t_local))
                ch_alpha   = int(255 * ease_in_out(ch_t_local))
                # scale: starts at 60%, grows to 100%
                ch_scale   = 0.6 + 0.4 * ease_in_out(ch_t_local)
                # slight upward drift during entrance
                ch_drift   = int((1 - ease_in_out(ch_t_local)) * subtitle_size)

                if ch_alpha > 0:
                    scaled_size = max(12, int(title_size * ch_scale))
                    ch_font, _ = self._load_fonts(scaled_size, subtitle_size)
                    color_ch = (255, 255, 255, ch_alpha)
                    glow_ch  = (120, 160, 255, ch_alpha // 3)
                    draw_text_glow(draw, (cx, ch_y + ch_drift), channel_clean,
                                   ch_font, color_ch, glow_ch, anchor='mm', glow_r=max(2, title_size//20))

                # ── Topic / subtitle lines ─────────────────────────────────
                for li, line in enumerate(all_sub_lines):
                    l_in  = sub_start + li * sub_per
                    l_out = l_in + sub_per * 0.6
                    l_t   = (t - l_in) / max(l_out - l_in, 0.001)
                    l_t   = max(0.0, min(1.0, l_t))
                    l_alpha = int(255 * ease_in_out(l_t)) if t >= l_in else 0

                    # slide up from below
                    slide = int((1 - ease_in_out(l_t)) * subtitle_size * 1.5)

                    if l_alpha > 0:
                        # Accumulate y position respecting mixed line heights
                        _y = block_y
                        for _i, _ln in enumerate(all_sub_lines[:li]):
                            _y += slug_line_h if _ln in slug_lines else line_h
                        y_pos = _y + slide
                        is_year = (year_line and line == year_line)
                        is_slug = (line in slug_lines)
                        if is_year:
                            # Year: gold pulsing
                            pulse = 0.8 + 0.2 * math.sin(t * math.pi * 6)
                            yr_a  = int(l_alpha * pulse)
                            color_l = (255, 220, 80, yr_a)
                            glow_l  = (200, 140, 0, yr_a // 4)
                            _render_font = subtitle_font
                        elif is_slug:
                            # Slug: warm amber, smaller font
                            color_l = (255, 200, 120, l_alpha)
                            glow_l  = (180, 80, 0, l_alpha // 5)
                            _render_font = slug_font
                        else:
                            color_l = (140, 210, 255, l_alpha)
                            glow_l  = (0, 80, 200, l_alpha // 4)
                            _render_font = subtitle_font
                        draw_text_glow(draw, (cx, y_pos), line,
                                       _render_font, color_l, glow_l,
                                       anchor='mm', glow_r=max(2, subtitle_size//12))

                # Composite overlay onto background
                img = Image.alpha_composite(base, overlay).convert('RGB')

                # ── Watermark ─────────────────────────────────────────────
                if watermark_enabled:
                    img = self._add_watermark(img, watermark_text, watermark_opacity,
                                              width, height, subtitle_size)

                frame_path = os.path.join(tmpdir, f'frame_{fi:06d}.png')
                img.save(frame_path, 'PNG')

            # ── Encode frames → MP4 via ffmpeg ─────────────────────────────
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(tmpdir, 'frame_%06d.png'),
                '-c:v', 'libx264',
                '-preset', 'faster',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                '-threads', str(OPTIMAL_THREADS),
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg encode failed: {result.stderr.decode()[:300]}")

        finally:
            import shutil as _sh
            _sh.rmtree(tmpdir, ignore_errors=True)


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
