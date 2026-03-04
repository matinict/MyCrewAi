"""
Debate Video Tool
Bottom-to-top streaming debate visualization — identical rendering engine to definition_video_tool.py:
- New (active) line appears at BOTTOM, bold, large, neon white glow
- Previous lines scroll UP, shrinking smaller as they rise
- Pure black background, all text white
- Pixel-accurate word wrap — never breaks a word
- Bottom 33% clear for YouTube subtitles
- gTTS audio + atempo sync (same as definition_video_tool)

Input files: propose.md, oppose.md, decide.md in output/{filename}/
Triggered by: "debate_video_enabled": true in data.json
Output: debate_video_[format].mp4 + _audio.mp3 + _with_audio.mp4 in output/{filename}/
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


def _clean_text(text: str) -> str:
    """
    Convert Mathematical Alphanumeric Symbols (e.g. italic 𝘔𝘪𝘥-𝘭𝘦𝘷𝘦𝘭) and other
    unicode stylised chars to plain ASCII so LiberationSans can render them.
    NFKD normalization decomposes math italic/bold/sans-serif variants to base ASCII.
    """
    import unicodedata
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('ascii')


class DebateVideoInput(BaseModel):
    """Input schema for DebateVideoTool."""
    topic:                str   = Field(..., description="Debate topic/motion")
    filename:             str   = Field(..., description="Base filename slug")
    output_dir:           str   = Field(..., description="Output subdirectory")
    video_formats:        list  = Field(..., description="List of formats: Shorts, HD, 4K, etc.")
    debate_video_enabled: bool  = Field(default=False, description="Generate debate video")
    secs_per_line:        float = Field(default=3.5, description="Seconds each line is shown as active")
    channel:              str   = Field(default="PlayOwnAi", description="Channel name")
    watermark_enabled:    bool  = Field(default=False, description="Show watermark")
    watermark_text:       str   = Field(default="@PlayOwnAi", description="Watermark text")
    video_fps:            int   = Field(default=30, description="Output video frame rate (ignored — uses 24 internally)")
    tts_engine:           str   = Field(default="gtts", description="TTS engine: 'gtts' or 'edge-tts'")


class DebateVideoTool(BaseTool):
    """Creates bottom-to-top streaming debate video — same engine as DefinitionVideoTool."""
    name: str = "Debate Video Tool"
    description: str = (
        "Generates a debate video with bottom-to-top streaming text animation. "
        "Reads propose.md (PRO), oppose.md (CON), decide.md (Moderator) from output_dir. "
        "Same rendering engine as Definition Video Tool. "
        "Triggered by debate_video_enabled=true."
    )
    args_schema: Type[BaseModel] = DebateVideoInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        video_formats: list,
        debate_video_enabled: bool = False,
        secs_per_line: float = 3.5,
        channel: str = "PlayOwnAi",
        watermark_enabled: bool = False,
        watermark_text: str = "@PlayOwnAi",
        video_fps: int = 30,
        tts_engine: str = "gtts",
    ) -> str:

        if not debate_video_enabled:
            return "⏭️ Debate video skipped (debate_video_enabled=false)"

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "❌ Pillow not installed. Run: pip install Pillow --break-system-packages"

        if not shutil.which('ffmpeg'):
            return "❌ ffmpeg not found. Run: sudo apt install ffmpeg"

        # ── Resolve output directory ──────────────────────────────────────
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # ── Load debate content ───────────────────────────────────────────
        propose_file = os.path.join(output_dir, "propose.md")
        oppose_file  = os.path.join(output_dir, "oppose.md")
        decide_file  = os.path.join(output_dir, "decide.md")

        for label, path in [("propose.md", propose_file),
                             ("oppose.md",  oppose_file),
                             ("decide.md",  decide_file)]:
            if not os.path.exists(path):
                return f"❌ {label} not found in {output_dir}"

        with open(propose_file, 'r', encoding='utf-8') as f:
            pro_text = f.read().strip()
        with open(oppose_file, 'r', encoding='utf-8') as f:
            con_text = f.read().strip()
        with open(decide_file, 'r', encoding='utf-8') as f:
            moderator_text = f.read().strip()

        # ── Combine into single narrative ─────────────────────────────────
        raw = "\n\n".join([pro_text, con_text, moderator_text])

        results, errors = [], []

        for fmt in video_formats:
            try:
                # ── Smart skip ────────────────────────────────────────────
                silent_video = os.path.join(output_dir, f"debate_video_{fmt}.mp4")
                audio_file   = os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")
                final_merged = os.path.join(output_dir, f"debate_video_{fmt}_with_audio.mp4")

                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped (final exists: {os.path.basename(final_merged)})")
                    continue

                # ── Parse lines ───────────────────────────────────────────
                raw_lines   = self._parse_lines(raw)
                spoken_text = self._lines_to_spoken(raw_lines, topic, channel)

                print(f"[DebateVideo] [{fmt}] Parsed {len(raw_lines)} lines")

                # ── Save narration text immediately ───────────────────────
                cc_path = os.path.join(output_dir, f"debate_video_{fmt}_cc_en.txt")
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(spoken_text)
                print(f"[DebateVideo] 📝 Narration saved: {cc_path} ({len(spoken_text)} chars)")

                # ── Render silent video ───────────────────────────────────
                if os.path.exists(silent_video):
                    print(f"[DebateVideo] ⏭️ {fmt}: Silent video exists — skipping render")
                    out_path = silent_video
                else:
                    out_path    = silent_video
                    is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                    w, h        = (1080, 1920) if is_portrait else (1920, 1080)
                    print(f"\n[DebateVideo] [{fmt}] {w}x{h}  secs_per_line={secs_per_line}")

                    self._render(raw_lines, out_path, w, h, secs_per_line,
                                 channel, watermark_enabled, watermark_text,
                                 topic=topic)

                    if not os.path.exists(out_path):
                        errors.append(f"❌ {fmt}: video missing after render")
                        continue

                # ── TTS audio ─────────────────────────────────────────────
                audio_path = os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")
                final_path = os.path.join(output_dir, f"debate_video_{fmt}_with_audio.mp4")
                video_dur  = self._get_duration(out_path)
                self._generate_tts(spoken_text, audio_path, video_dur, tts_engine)

                # ── Merge audio + video ───────────────────────────────────
                if os.path.exists(audio_path):
                    self._merge_audio_video(out_path, audio_path, final_path, video_dur)
                    merged_kb = os.path.getsize(final_path) // 1024 if os.path.exists(final_path) else 0
                    kb        = os.path.getsize(out_path) // 1024
                    results.append(
                        f"✅ {fmt}: {os.path.basename(final_path)} ({merged_kb} KB)  "
                        f"Duration: {video_dur:.1f}s"
                    )
                else:
                    kb = os.path.getsize(out_path) // 1024
                    results.append(f"✅ {fmt}: {os.path.basename(silent_video)} ({kb} KB) [no audio]")

            except Exception as e:
                import traceback
                traceback.print_exc()
                errors.append(f"❌ {fmt}: {e}")

        if not results:
            return "❌ Debate video failed:\n" + "\n".join(errors)

        out = "🎬 Debate videos created:\n" + "\n".join(f"   • {r}" for r in results)
        if errors:
            out += "\n⚠️ Errors:\n" + "\n".join(errors)
        return out

    # ── Helpers (identical to definition_video_tool.py) ───────────────────

    def _lines_to_spoken(self, lines: list, topic: str, channel: str) -> str:
        """Convert display lines to natural spoken narration text for TTS."""
        import re as _re
        parts = []
        for line in lines:
            # Clean section headers to natural speech
            line = _re.sub(r'^PROPOSITION:\s*', 'In favour of the motion: ', line, flags=_re.I)
            line = _re.sub(r'^OPPOSITION:\s*',  'Against the motion: ',      line, flags=_re.I)
            line = _re.sub(r'^VERDICT:\s*',     'The verdict: ',              line, flags=_re.I)
            line = _re.sub(r'^\*\*(.+?)\*\*$',  r'\1',                       line)
            parts.append(line)
        text  = ' '.join(parts)
        text  = _clean_text(text)
        text += f' Subscribe to {channel} for more insights.'
        return text

    def _get_duration(self, video_path: str) -> float:
        """Get video duration in seconds via ffprobe."""
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True
        )
        try:
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _generate_tts(self, text: str, audio_path: str, video_dur: float, tts_engine: str = "gtts"):
        """
        Generate TTS MP3 then stretch/pad to match video_dur exactly.
        tts_engine: 'gtts'     → gTTS (offline-friendly, requires: pip install gTTS)
                    'edge-tts' → Microsoft Edge TTS (higher quality, requires: pip install edge-tts)
        Both engines use atempo to sync audio length to video duration.
        """
        engine = tts_engine.strip().lower()
        print(f"[DebateVideo] 🔊 TTS engine: {engine}  ({len(text)} chars)  timeout=60s")

        tmp = audio_path.replace('.mp3', '_raw.mp3')

        try:
            if engine == "edge-tts":
                self._tts_edge(text, tmp)
            else:
                self._tts_gtts(text, tmp)

            if not os.path.exists(tmp):
                print(f"[DebateVideo] ⚠️ TTS produced no file — skipping audio")
                return

            raw_dur = self._get_duration(tmp)
            if raw_dur <= 0:
                os.rename(tmp, audio_path)
                return

            ratio = raw_dur / max(video_dur, 1)
            ratio = max(0.5, min(2.0, ratio))
            print(f"[DebateVideo] 🔊 TTS {raw_dur:.1f}s → video {video_dur:.1f}s  atempo={ratio:.3f}")

            result = subprocess.run([
                "ffmpeg", "-y", "-i", tmp,
                "-filter:a", f"atempo={ratio}",
                audio_path
            ], capture_output=True, check=False)

            if os.path.exists(tmp):
                os.remove(tmp)

            if result.returncode != 0:
                print(f"[DebateVideo] ⚠️ atempo failed: {result.stderr.decode()[:100]}")

        except Exception as e:
            print(f"[DebateVideo] ⚠️ TTS error: {e}")
            if os.path.exists(tmp):
                os.rename(tmp, audio_path)

    def _tts_gtts(self, text: str, out_path: str):
        """Generate audio using gTTS."""
        try:
            from gtts import gTTS
        except ImportError:
            print("[DebateVideo] ⚠️ gTTS not installed. Run: pip install gTTS --break-system-packages")
            return
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(out_path)
        print(f"[DebateVideo] ✅ gTTS saved: {out_path}")

    def _tts_edge(self, text: str, out_path: str, timeout: int = 60):
        """
        Generate audio using edge-tts (async) with a hard timeout.
        Falls back to gTTS if edge-tts is not installed, times out, or errors.
        timeout: seconds to wait before giving up (default 60s)
        """
        try:
            import edge_tts
            import asyncio
        except ImportError:
            print("[DebateVideo] ⚠️ edge-tts not installed. Run: pip install edge-tts --break-system-packages")
            print("[DebateVideo]    Falling back to gTTS ...")
            self._tts_gtts(text, out_path)
            return

        async def _generate():
            communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
            await communicate.save(out_path)

        async def _with_timeout():
            await asyncio.wait_for(_generate(), timeout=timeout)

        try:
            import asyncio
            asyncio.run(_with_timeout())
            if os.path.exists(out_path):
                print(f"[DebateVideo] ✅ edge-tts saved: {out_path}")
            else:
                raise RuntimeError("edge-tts produced no output file")
        except asyncio.TimeoutError:
            print(f"[DebateVideo] ⚠️ edge-tts timed out after {timeout}s — falling back to gTTS")
            if os.path.exists(out_path):
                os.remove(out_path)
            self._tts_gtts(text, out_path)
        except Exception as e:
            print(f"[DebateVideo] ⚠️ edge-tts failed ({e}) — falling back to gTTS")
            if os.path.exists(out_path):
                os.remove(out_path)
            self._tts_gtts(text, out_path)

    def _merge_audio_video(self, video_path: str, audio_path: str,
                            output_path: str, video_dur: float):
        """Merge audio into video; pad audio with silence if shorter than video."""
        print(f"[DebateVideo] 🎬 Merging audio+video → {os.path.basename(output_path)}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac",
            "-filter_complex", f"[1:a]apad,atrim=duration={video_dur:.3f}[aout]",
            "-map", "0:v", "-map", "[aout]",
            output_path
        ], capture_output=True, check=False)
        if result.returncode != 0:
            print(f"[DebateVideo] ⚠️ merge failed: {result.stderr.decode()[:150]}")

    def _parse_lines(self, raw: str) -> List[str]:
        """
        Parse debate markdown into display lines.
        Skips separator lines, cleans markdown bold (**text**),
        normalises section headers.
        """
        result = []
        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("━") or line.startswith("─") or line.startswith("==="):
                continue

            # Strip leading emoji
            line = re.sub(
                r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff'
                r'\u2600-\u27ff\u2000-\u206f\ufe00-\ufe0f]+\s*',
                '', line
            ).strip()
            if not line:
                continue

            # Clean markdown bold **text** → text
            line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)

            # Clean instruction leakage [like this]
            line = re.sub(r'\[.*?\]', '', line).strip()
            if not line:
                continue

            # Strip unicode math italic/bold to plain ASCII for font rendering
            line = _clean_text(line)
            if not line:
                continue
            # Capitalise first letter
            line = line[0].upper() + line[1:]

            result.append(line)

        return result

    def _pixel_wrap(self, text: str, font, max_px: int) -> List[str]:
        from PIL import Image as _Img, ImageDraw
        tmp  = _Img.new("RGB", (1, 1))
        draw = ImageDraw.Draw(tmp)
        def line_w(words):
            if not words: return 0
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

    def _neon_white(self, alpha: float, frame: int) -> Tuple[int, int, int]:
        import math
        t = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        return (
            min(255, int((200 + 55 * t) * alpha)),
            min(255, int((230 + 25 * t) * alpha)),
            min(255, int(255 * alpha)),
        )

    def _draw_neon(self, draw, x, y, text, font, alpha, frame):
        import math
        t     = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        halo  = (int(50*t*alpha),  int(130*t*alpha), int(210*t*alpha))
        inner = (int(150*t*alpha), int(210*t*alpha), int(255*t*alpha))
        face  = self._neon_white(alpha, frame)
        bloom = (int(255*alpha), int(255*alpha), int(255*alpha))
        draw.text((x+2, y+2), text, font=font, fill=halo)
        draw.text((x+1, y+1), text, font=font, fill=inner)
        draw.text((x,   y  ), text, font=font, fill=face)
        draw.text((x-1, y-1), text, font=font, fill=bloom)

    def _justify(self, draw, x, y, text, font, max_w, fill):
        words = text.split()
        if len(words) <= 1:
            draw.text((x, y), text, font=font, fill=fill)
            return
        word_widths = []
        for w2 in words:
            bb = draw.textbbox((0, 0), w2, font=font)
            word_widths.append(bb[2] - bb[0])
        sp_bb     = draw.textbbox((0, 0), ' ', font=font)
        sp_w      = sp_bb[2] - sp_bb[0]
        natural_w = sum(word_widths) + sp_w * (len(words) - 1)
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
        """Render debate video — identical layout engine to definition_video_tool._render."""
        from PIL import Image, ImageDraw, ImageFont
        FPS             = 24                          # same as definition_video_tool
        frames_per_line = int(secs_per_line * FPS)
        fade_frames     = min(6, frames_per_line // 5)
        BASE_ACTIVE     = w // 28
        SHRINK_STEP     = w // 130
        MIN_SIZE        = w // 58
        base_wm         = w // 52

        try:
            f_active = ImageFont.truetype(FONT_BOLD, BASE_ACTIVE)
            f_wm     = ImageFont.truetype(FONT_BOLD, base_wm)
        except Exception:
            f_active = f_wm = ImageFont.load_default()

        def get_font(age: int):
            size = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
            try:
                return ImageFont.truetype(FONT_BOLD if age == 0 else FONT_REGULAR, size)
            except Exception:
                return ImageFont.load_default()

        pad_x         = int(w * 0.05)
        header_h      = int(h * 0.10)
        pad_top       = header_h + int(h * 0.02)
        wm_zone       = int(h * 0.88)
        body_h        = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y      = pad_top + body_h // 2 - active_font_h // 2
        max_px        = w - pad_x - int(w * 0.05)

        hdr_topic_size = max(w // 22, 28)
        try:
            f_hdr_topic = ImageFont.truetype(FONT_BOLD, hdr_topic_size)
        except Exception:
            f_hdr_topic = ImageFont.load_default()

        hdr_line1 = _clean_text(topic) if topic else _clean_text(channel)

        lines: List[str] = []
        for raw in raw_lines:
            lines.extend(self._pixel_wrap(raw, f_active, max_px))

        total_frames = len(lines) * frames_per_line
        print(f"[DebateVideo]   Wrapped lines: {len(lines)}   "
              f"Total frames: {total_frames}   "
              f"Est: {total_frames/FPS:.0f}s ({total_frames/FPS/60:.1f}min)")

        cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
               '-s', f'{w}x{h}', '-pix_fmt', 'rgb24', '-r', str(FPS), '-i', '-',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
               '-pix_fmt', 'yuv420p', out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        t0   = time.time()

        try:
            from tqdm import tqdm
            import sys
            pbar = tqdm(
                total=total_frames,
                desc=f"  🎬 [{out_path.split('/')[-1]}]",
                unit="fr",
                bar_format=(
                    "{desc}: {percentage:3.0f}%|{bar:35}|  "
                    "{n_fmt}/{total_fmt} fr [{elapsed} <{remaining}, {rate_fmt}]"
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
                img   = Image.new("RGB", (w, h), (0, 0, 0))
                draw  = ImageDraw.Draw(img)

                # Header
                hdr_bbox = draw.textbbox((0, 0), hdr_line1, font=f_hdr_topic)
                hdr_w    = hdr_bbox[2] - hdr_bbox[0]
                hdr_x    = (w - hdr_w) // 2
                hdr_y    = int(h * 0.018)
                draw.text((hdr_x, hdr_y), hdr_line1, font=f_hdr_topic, fill=(255, 255, 255))

                # Separator
                sep_y = header_h - 2
                draw.line([(pad_x, sep_y), (w - pad_x, sep_y)], fill=(50, 60, 80), width=1)

                # Past lines (scroll up, shrinking)
                past_indices = list(range(max(0, line_idx - 30), line_idx))
                past_indices.reverse()
                y_cursor = active_y
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

                # Active line — neon white glow
                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)

                # Future lines (dim, below active)
                future_start = active_y + active_font_h + int(h * 0.025)
                y_cursor     = future_start
                for ahead, fi2 in enumerate(range(line_idx + 1, min(line_idx + 20, len(lines))), start=1):
                    fnt    = get_font(ahead)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - ahead * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    if y_cursor + line_h > wm_zone:
                        break
                    brightness = max(18, 110 - ahead * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_cursor, lines[fi2], fnt, max_px, c)
                    y_cursor += line_h

                # Progress bar
                prog   = (line_idx * frames_per_line + fi) / total_frames
                bar_y  = h - 2
                filled = int(w * prog)
                draw.line([(0, bar_y), (w - 1, bar_y)], fill=(40, 40, 40), width=1)
                if filled > 0:
                    draw.line([(0, bar_y), (filled, bar_y)], fill=(200, 200, 200), width=1)

                # Watermark
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
        print(f"[DebateVideo]   ✅ Encoded in {elapsed:.0f}s ({elapsed/60:.1f}min)")
