"""
Definition Video Tool
Bottom-to-top streaming paragraph reader:
- New (active) line appears at BOTTOM, bold, large, neon white glow
- Previous lines scroll UP, shrinking smaller as they rise
- Pure black background, all text white
- Pixel-accurate word wrap — never breaks a word
- Bottom 33% clear for YouTube subtitles
Triggered by: "definition_video": true in data.json
Output: definition_video_[format].mp4 in output/{filename}/
"""

import os
import re
import shutil
import subprocess
import time
from typing import Type, List, Tuple
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


class DefinitionVideoInput(BaseModel):
    topic:             str   = Field(...,  description="Topic name")
    filename:          str   = Field(...,  description="Base filename slug")
    output_dir:        str   = Field(...,  description="Output subdirectory")
    video_formats:     list  = Field(...,  description="List of formats: Shorts, HD, etc.")
    definition_video:  bool  = Field(default=False, description="Generate definition video")
    secs_per_line:     float = Field(default=3.5, description="Seconds each line is shown as active")
    channel:           str   = Field(default="PlayOwnAi", description="Channel name")
    watermark_enabled: bool  = Field(default=False, description="Show watermark")
    watermark_text:    str   = Field(default="@PlayOwnAi", description="Watermark text")


class DefinitionVideoTool(BaseTool):
    name: str = "Definition Video Tool"
    description: str = (
        "Creates a bottom-to-top streaming video from the topic definition .txt file. "
        "Active line is large neon white at bottom; older lines shrink as they rise. "
        "Triggered by definition_video=true."
    )
    args_schema: Type[BaseModel] = DefinitionVideoInput

    # ──────────────────────────────────────────────────────────────────
    def _run(
        self,
        topic:             str,
        filename:          str,
        output_dir:        str,
        video_formats:     list,
        definition_video:  bool  = False,
        secs_per_line:     float = 3.5,
        channel:           str   = "PlayOwnAi",
        watermark_enabled: bool  = False,
        watermark_text:    str   = "@PlayOwnAi",
    ) -> str:

        if not definition_video:
            return "⏭️  Definition video skipped (definition_video=false)"

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "❌ Pillow not installed. Run: pip install Pillow --break-system-packages"

        if not shutil.which('ffmpeg'):
            return "❌ ffmpeg not found. Run: sudo apt install ffmpeg"

        # ── Locate definition .txt ──────────────────────────────────────
        filename_clean = ''.join(re.findall(r'\w+', filename)[:3])
        parent_dir = os.path.dirname(os.path.abspath(output_dir))
        txt_candidates = [
            os.path.join(parent_dir, f"{filename_clean}.txt"),
            os.path.join(parent_dir, f"{filename}.txt"),
            os.path.join(output_dir,  f"{filename_clean}.txt"),
        ]
        txt_path = next((p for p in txt_candidates if os.path.exists(p)), None)

        if not txt_path:
            return "❌ Definition .txt not found. Tried:\n" + "\n".join(txt_candidates)

        print(f"[DefVideo] Reading: {txt_path}")
        with open(txt_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        raw_lines = self._parse_lines(raw)
        print(f"[DefVideo] Parsed {len(raw_lines)} raw lines")

        results, errors = [], []

        for fmt in video_formats:
            try:
                out_path    = os.path.join(output_dir, f"definition_video_{fmt}.mp4")
                is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                w, h        = (1080, 1920) if is_portrait else (1920, 1080)
                print(f"\n[DefVideo] [{fmt}] {w}x{h}  secs_per_line={secs_per_line}")
                self._render(raw_lines, out_path, w, h, secs_per_line,
                             channel, watermark_enabled, watermark_text,
                             topic=topic)
                if os.path.exists(out_path):
                    kb = os.path.getsize(out_path) // 1024
                    results.append(f"✅ {fmt}: {out_path} ({kb} KB)")
                else:
                    errors.append(f"❌ {fmt}: output file missing after render")
            except Exception as e:
                import traceback; traceback.print_exc()
                errors.append(f"❌ {fmt}: {e}")

        if not results:
            return "❌ Definition video failed:\n" + "\n".join(errors)

        out = "🎬 Definition videos created:\n" + "\n".join(f"   • {r}" for r in results)
        if errors:
            out += "\n⚠️ Errors:\n" + "\n".join(errors)
        return out

    # ──────────────────────────────────────────────────────────────────
    def _parse_lines(self, raw: str) -> List[str]:
        """
        Returns only body lines (starting from WHAT IS...).
        Skips: ━━━ separators, TOPIC:/Channel:/Subscribe: header lines,
               TIMELINE and WHAT YOU WILL SEE sections.
        Cleans Term N: → N: and doubled N: N: patterns.
        """
        SKIP_STARTS  = ("TIMELINE", "WHAT YOU WILL SEE", "Subscribe to",
                        "Channel:", "TOPIC:")
        result       = []
        skip_section = False

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("━") or line.startswith("─"):
                skip_section = False
                continue

            # Strip leading emoji/icons
            line = re.sub(
                r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff'
                r'\u2600-\u27ff\u2000-\u206f\ufe00-\ufe0f]+\s*',
                '', line
            ).strip()
            if not line:
                continue

            # Skip header/footer lines
            if any(line.upper().startswith(s.upper()) for s in SKIP_STARTS):
                skip_section = True if line.upper().startswith(("TIMELINE","WHAT YOU WILL SEE")) else False
                continue
            if skip_section:
                continue

            # Clean Term N: / doubled N: N:
            line = re.sub(r'KEY\s+TERMS\s+(\d+):\s*\1:\s*', r'KEY TERMS\n\1: ', line)
            line = re.sub(r'KEY\s+TERMS\s+(\d+):',             r'KEY TERMS\n\1:', line)
            line = re.sub(r'\bTerm\s+(\d+):\s*',              r'\1: ', line)
            line = re.sub(r'\b(\d+):\s+\1:\s*',              r'\1: ', line)

            # Split "KEY TERMS\n1:" into two list entries
            for part in line.split('\n'):
                part = part.strip()
                if part:
                    # Section headers (WHAT IS / WHY DOES / KEY TERMS) → Title Case
                    # Body lines → Sentence case (first letter capital only)
                    import re as _re2
                    if _re2.match(r'^(WHAT IS|WHY DOES|KEY TERMS)', part, _re2.I):
                        part = part.title()
                    else:
                        part = part[0].upper() + part[1:]
                    result.append(part)

        return result

    # ──────────────────────────────────────────────────────────────────
    def _pixel_wrap(self, text: str, font, max_px: int) -> List[str]:
        """
        Wrap a single string to fit within max_px using real font metrics.
        Never splits a word — breaks only on spaces.
        """
        from PIL import Image as _Img, ImageDraw
        tmp  = _Img.new("RGB", (1, 1))
        draw = ImageDraw.Draw(tmp)

        def line_w(words):
            if not words:
                return 0
            bb = draw.textbbox((0, 0), ' '.join(words), font=font)
            return bb[2] - bb[0]

        words, current, result = text.split(), [], []
        for word in words:
            test = current + [word]
            if current and line_w(test) > max_px:
                result.append(' '.join(current))
                current = [word]
            else:
                current = test
        if current:
            result.append(' '.join(current))
        return result

    # ──────────────────────────────────────────────────────────────────
    def _neon_white(self, alpha: float, frame: int) -> Tuple[int, int, int]:
        """Pulsing neon-white: cyan-white → pure white, slow shimmer."""
        import math
        t = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        return (
            min(255, int((200 + 55 * t) * alpha)),
            min(255, int((230 + 25 * t) * alpha)),
            min(255, int(255 * alpha)),
        )

    # ──────────────────────────────────────────────────────────────────
    def _draw_neon(self, draw, x, y, text, font, alpha, frame):
        """4-layer neon glow: halo → inner glow → face → bloom."""
        import math
        t     = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        halo  = (int( 50*t*alpha), int(130*t*alpha), int(210*t*alpha))
        inner = (int(150*t*alpha), int(210*t*alpha), int(255*t*alpha))
        face  = self._neon_white(alpha, frame)
        bloom = (int(255*alpha),   int(255*alpha),   int(255*alpha))

        draw.text((x+2, y+2), text, font=font, fill=halo)
        draw.text((x+1, y+1), text, font=font, fill=inner)
        draw.text((x,   y  ), text, font=font, fill=face)
        draw.text((x-1, y-1), text, font=font, fill=bloom)

    # ──────────────────────────────────────────────────────────────────
    def _justify(self, draw, x, y, text, font, max_w, fill):
        """
        Justify only if line fills >65% of max_w — prevents huge gaps on short lines.
        Falls back to left-align for short/single-word lines.
        """
        words = text.split()
        if len(words) <= 1:
            draw.text((x, y), text, font=font, fill=fill)
            return
        # Measure natural line width
        word_widths = []
        for w2 in words:
            bb = draw.textbbox((0, 0), w2, font=font)
            word_widths.append(bb[2] - bb[0])
        # Natural space width
        sp_bb = draw.textbbox((0, 0), ' ', font=font)
        sp_w  = sp_bb[2] - sp_bb[0]
        natural_w = sum(word_widths) + sp_w * (len(words) - 1)
        # Only justify if line is long enough (>65% full) — avoids funny gaps
        if natural_w < max_w * 0.65:
            draw.text((x, y), text, font=font, fill=fill)
            return
        gap = (max_w - sum(word_widths)) / max(len(words) - 1, 1)
        cx = x
        for word, ww in zip(words, word_widths):
            draw.text((int(cx), y), word, font=font, fill=fill)
            cx += ww + gap

    def _render(self, raw_lines, out_path, w, h, secs_per_line,
                channel, wm_enabled, wm_text, topic=""):
        from PIL import Image, ImageDraw, ImageFont

        FPS             = 24
        frames_per_line = int(secs_per_line * FPS)
        fade_frames     = min(6, frames_per_line // 5)

        # ── Font sizes ──────────────────────────────────────────────────
        # Active (bottom) line is the largest.
        # Each step up shrinks by SHRINK_STEP px.
        BASE_ACTIVE = w // 28      # body active font — smaller than header (w//22)
        SHRINK_STEP = w // 130     # each older line shrinks by this many px
        MIN_SIZE    = w // 58      # minimum font size for oldest visible lines
        base_wm     = w // 52

        try:
            f_active = ImageFont.truetype(FONT_BOLD,    BASE_ACTIVE)
            f_wm     = ImageFont.truetype(FONT_BOLD,    base_wm)
        except Exception:
            f_active = f_wm = ImageFont.load_default()

        def get_font(age: int):
            """Return font for a line that is `age` steps above active (age=0=active)."""
            size = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
            try:
                return ImageFont.truetype(
                    FONT_BOLD if age == 0 else FONT_REGULAR, size)
            except Exception:
                return ImageFont.load_default()

        # ── Layout ─────────────────────────────────────────────────────
        pad_x       = int(w * 0.05)
        header_h    = int(h * 0.10)     # fixed header zone height at top
        pad_top     = header_h + int(h * 0.02)   # body starts below header
        wm_zone     = int(h * 0.88)     # watermark/progress zone
        # Active line sits at vertical center of BODY area (below header)
        body_h        = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y      = pad_top + body_h // 2 - active_font_h // 2

        # Max usable text width
        max_px = w - pad_x - int(w * 0.05)

        # ── Static header fonts ─────────────────────────────────────────
        hdr_topic_size = max(w // 22, 28)   # bigger — ~87px on HD, ~49px on Shorts
        try:
            f_hdr_topic = ImageFont.truetype(FONT_BOLD, hdr_topic_size)
        except Exception:
            f_hdr_topic = ImageFont.load_default()

        # Pre-build header text — topic only, centered, no @channel
        hdr_line1 = topic if topic else channel

        # ── Pixel-wrap every raw line using the active font ─────────────
        lines: List[str] = []
        for raw in raw_lines:
            lines.extend(self._pixel_wrap(raw, f_active, max_px))

        total_frames = len(lines) * frames_per_line

        print(f"[DefVideo]   Wrapped lines: {len(lines)}  "
              f"Total frames: {total_frames}  "
              f"Est: {total_frames/FPS:.0f}s ({total_frames/FPS/60:.1f}min)")

        # ── ffmpeg pipe ─────────────────────────────────────────────────
        cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
               '-s', f'{w}x{h}', '-pix_fmt', 'rgb24', '-r', str(FPS), '-i', '-',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
               '-pix_fmt', 'yuv420p', out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        t0 = time.time()

        # ── tqdm progress bar ───────────────────────────────────────────
        try:
            from tqdm import tqdm
            import sys
            pbar = tqdm(
                total=total_frames,
                desc=f"  🎬 [{out_path.split('/')[-1]}]",
                unit="fr",
                bar_format=(
                    "{desc}: {percentage:3.0f}%|{bar:35}| "
                    "{n_fmt}/{total_fmt} fr [{elapsed}<{remaining}, {rate_fmt}]"
                ),
                dynamic_ncols=True,
                leave=True,
                colour="white",
                file=sys.stdout,
                position=0,
            )
        except ImportError:
            pbar = None

        global_frame = 0

        for line_idx, ltext in enumerate(lines):
            for fi in range(frames_per_line):
                alpha = min(1.0, fi / max(fade_frames, 1))

                img  = Image.new("RGB", (w, h), (0, 0, 0))
                draw = ImageDraw.Draw(img)

                # ══ STATIC HEADER — centered topic, no channel tag ══
                hdr_bbox = draw.textbbox((0, 0), hdr_line1, font=f_hdr_topic)
                hdr_w    = hdr_bbox[2] - hdr_bbox[0]
                hdr_x    = (w - hdr_w) // 2          # centered
                hdr_y    = int(h * 0.018)
                draw.text((hdr_x, hdr_y), hdr_line1,
                          font=f_hdr_topic, fill=(255, 255, 255))
                # Thin separator line under header
                sep_y = header_h - 2
                draw.line([(pad_x, sep_y), (w - pad_x, sep_y)],
                          fill=(50, 60, 80), width=1)

                # ══ PAST lines — stack ABOVE active, bottom-to-top ══
                past_indices = list(range(max(0, line_idx - 30), line_idx))
                past_indices.reverse()   # index 0 = most recent past

                y_cursor = active_y   # walk upward from active line
                for age, pi in enumerate(past_indices, start=1):
                    fnt    = get_font(age)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    y_pos  = y_cursor - line_h
                    if y_pos < pad_top:
                        break
                    brightness = max(25, 160 - age * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_pos, lines[pi], fnt, max_px, c)
                    y_cursor = y_pos

                # ══ ACTIVE line — neon white glow, justified ══
                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)

                # ══ UPCOMING lines — stack BELOW active, top-to-bottom ══
                future_start = active_y + active_font_h + int(h * 0.025)
                y_cursor     = future_start
                for ahead, fi2 in enumerate(
                        range(line_idx + 1, min(line_idx + 20, len(lines))),
                        start=1):
                    fnt    = get_font(ahead)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - ahead * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    if y_cursor + line_h > wm_zone:
                        break
                    # upcoming: dim, shrinking — mirror of past lines
                    brightness = max(18, 110 - ahead * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_cursor, lines[fi2], fnt, max_px, c)
                    y_cursor += line_h

                # ══ Progress bar — single 1px line at very bottom ══
                prog   = (line_idx * frames_per_line + fi) / total_frames
                bar_y  = h - 2                          # exactly 1 line from bottom
                filled = int(w * prog)
                draw.line([(0, bar_y), (w - 1, bar_y)], fill=(40, 40, 40), width=1)
                if filled > 0:
                    draw.line([(0, bar_y), (filled, bar_y)], fill=(200, 200, 200), width=1)

                # ══ Watermark — centered, very dim, above progress bar ══
                tag     = wm_text if wm_enabled else f"@{channel}"
                tw_bbox = draw.textbbox((0, 0), tag, font=f_wm)
                tw      = tw_bbox[2] - tw_bbox[0]
                wm_x    = (w - tw) // 2
                wm_y    = wm_zone + int(h * 0.02)
                draw.text((wm_x, wm_y), tag, font=f_wm, fill=(30, 30, 38))

                proc.stdin.write(img.tobytes())
                global_frame += 1
                if pbar is not None:
                    pbar.update(1)

        if pbar is not None:
            pbar.close()

        proc.stdin.close()
        proc.wait()
        elapsed = time.time() - t0
        print(f"[DefVideo]   ✅ Encoded in {elapsed:.0f}s ({elapsed/60:.1f}min)")
