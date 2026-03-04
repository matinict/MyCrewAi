"""
Debate Video Tool
Bottom-to-top streaming debate visualization with TTS audio:
- Combines PRO arguments (propose.md) and CON arguments (oppose.md)
- Moderator conclusion (decide.md)
- Same animation style as definition_video: neon white glow, bottom-to-top streaming
- Auto-generated TTS audio synchronized with video
- Watermark support
- Multiple video format support (Shorts, HD, 4K)
- Pure black background, bottom 33% clear for YouTube subtitles

Triggered by: "debate_video_enabled": true in data.json
Input files: propose.md, oppose.md, decide.md in output/{filename}/
Output: debate_video_[format]_with_audio.mp4 in output/{filename}/
"""
import os
import re
import shutil
import subprocess
import time
from typing import Type, List, Tuple
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from PIL import Image

FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

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
    video_fps:            int   = Field(default=30, description="Output video frame rate")


class DebateVideoTool(BaseTool):
    """Creates bottom-to-top streaming debate video with TTS audio."""
    name: str = "Debate Video Tool"
    description: str = (
        "Generates a debate video with bottom-to-top streaming text animation. "
        "Combines PRO arguments (propose.md), CON arguments (oppose.md), "
        "and moderator conclusion (decide.md) with auto-generated TTS audio. "
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
        _tool_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # ── Load debate content ───────────────────────────────────────────
        propose_file = os.path.join(output_dir, "propose.md")
        oppose_file = os.path.join(output_dir, "oppose.md")
        decide_file = os.path.join(output_dir, "decide.md")

        if not os.path.exists(propose_file):
            return f"❌ propose.md not found in {output_dir}"
        if not os.path.exists(oppose_file):
            return f"❌ oppose.md not found in {output_dir}"
        if not os.path.exists(decide_file):
            return f"❌ decide.md not found in {output_dir}"

        # Read debate content
        with open(propose_file, 'r', encoding='utf-8') as f:
            pro_text = f.read().strip()
        with open(oppose_file, 'r', encoding='utf-8') as f:
            con_text = f.read().strip()
        with open(decide_file, 'r', encoding='utf-8') as f:
            moderator_text = f.read().strip()

        # ── Build debate narrative ────────────────────────────────────────
        debate_narrative = self._build_debate_narrative(
            topic, pro_text, con_text, moderator_text
        )

        print(f"[DebateVideo] Built narrative: {len(debate_narrative)} chars")

        results, errors = [], []

        for fmt in video_formats:
            try:
                # ✅ SMART SKIP — check what already exists
                silent_video = os.path.join(output_dir, f"debate_video_{fmt}.mp4")
                audio_file   = os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")
                final_merged = os.path.join(output_dir, f"debate_video_{fmt}_with_audio.mp4")

                # Skip everything if final merged exists
                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped (final exists: {os.path.basename(final_merged)})")
                    continue

                # Parse lines
                raw_lines = self._parse_lines(debate_narrative)
                spoken_text = debate_narrative  # Entire narrative is spoken

                print(f"[DebateVideo] [{fmt}] Parsed {len(raw_lines)} lines")

                # ✅ Save narration text per format
                cc_path = os.path.join(output_dir, f"debate_video_{fmt}_cc_en.txt")
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(spoken_text)
                print(f"[DebateVideo] 📝 Narration saved: {cc_path} ({len(spoken_text)} chars)")

                # If silent video exists but merged doesn't, skip rendering
                if os.path.exists(silent_video):
                    print(f"[DebateVideo] ⏭️ {fmt}: Silent video exists — skipping render")
                    out_path = silent_video
                else:
                    # Render silent video (missing)
                    out_path = silent_video
                    is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                    w, h = (1080, 1920) if is_portrait else (1920, 1080)
                    print(f"\n[DebateVideo] [{fmt}] {w}x{h}  secs_per_line={secs_per_line}")

                    self._render(raw_lines, out_path, w, h, secs_per_line,
                                 channel, watermark_enabled, watermark_text,
                                 topic=topic, video_fps=video_fps)

                    if not os.path.exists(out_path):
                        errors.append(f"❌ {fmt}: video missing after render")
                        continue

                # Generate TTS audio matching video duration
                audio_path = os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")
                final_path = os.path.join(output_dir, f"debate_video_{fmt}_with_audio.mp4")
                video_dur  = self._get_duration(out_path)
                self._generate_tts(spoken_text, audio_path, video_dur)

                # Merge audio into video
                if os.path.exists(audio_path):
                    self._merge_audio_video(out_path, audio_path, final_path, video_dur)
                    merged_kb = os.path.getsize(final_path) // 1024 if os.path.exists(final_path) else 0
                    kb = os.path.getsize(out_path) // 1024
                    results.append(
                        f"✅ {fmt}: {os.path.basename(final_path)} ({merged_kb} KB)  "
                        f"Duration: {video_dur:.1f}s"
                    )
                else:
                    results.append(f"⚠️ {fmt}: Video created but TTS failed")

            except Exception as e:
                errors.append(f"❌ {fmt}: {str(e)}")

        if errors:
            results.extend(errors)

        return "\n".join(results)

    def _build_debate_narrative(self, topic: str, pro_text: str, con_text: str, moderator_text: str) -> str:
        """Build a cohesive narrative combining all debate elements."""
        narrative = f"Debate: {topic}\n\n"
        narrative += "ARGUMENTS IN FAVOR:\n" + pro_text + "\n\n"
        narrative += "ARGUMENTS IN OPPOSITION:\n" + con_text + "\n\n"
        narrative += "CONCLUSION:\n" + moderator_text
        return narrative

    def _parse_lines(self, raw: str) -> List[str]:
        """Parse text into logical lines/paragraphs."""
        # Split by double newlines for paragraphs, then by single newlines
        paragraphs = [p.strip() for p in raw.split('\n\n') if p.strip()]
        return paragraphs

    def _lines_to_spoken(self, raw_lines: List[str], topic: str, channel: str) -> str:
        """Convert lines to spoken text for TTS."""
        return '\n'.join(raw_lines)

    def _pixel_wrap(self, text: str, font, max_w: int) -> List[str]:
        """Wrap text to fit pixel width, never breaking words."""
        from PIL import ImageDraw
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox((0, 0), test_line, font=font)
            test_w = bbox[2] - bbox[0]

            if test_w <= max_w:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines

    def _neon_white(self, alpha: float, frame: int) -> Tuple[int, int, int]:
        """Generate neon white color with glow effect."""
        import math
        t = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        return (
            min(255, int((200 + 55 * t) * alpha)),
            min(255, int((230 + 25 * t) * alpha)),
            min(255, int(255 * alpha)),
        )

    def _draw_neon(self, draw, x, y, text, font, alpha, frame):
        """Draw text with neon glow effect."""
        import math
        t = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        halo  = (int(50*t*alpha), int(130*t*alpha), int(210*t*alpha))
        inner = (int(150*t*alpha), int(210*t*alpha), int(255*t*alpha))
        face  = self._neon_white(alpha, frame)
        bloom = (int(255*alpha), int(255*alpha), int(255*alpha))
        draw.text((x+2, y+2), text, font=font, fill=halo)
        draw.text((x+1, y+1), text, font=font, fill=inner)
        draw.text((x,   y  ), text, font=font, fill=face)
        draw.text((x-1, y-1), text, font=font, fill=bloom)

    def _justify(self, draw, x, y, text, font, max_w, fill):
        """Draw justified text."""
        words = text.split()
        if len(words) <= 1:
            draw.text((x, y), text, font=font, fill=fill)
            return
        word_widths = []
        for w2 in words:
            bb = draw.textbbox((0, 0), w2, font=font)
            word_widths.append(bb[2] - bb[0])
        sp_bb = draw.textbbox((0, 0), ' ', font=font)
        sp_w  = sp_bb[2] - sp_bb[0]
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
                channel, wm_enabled, wm_text, topic="", video_fps=30):
        """Render debate video with bottom-to-top streaming animation."""
        from PIL import Image, ImageDraw, ImageFont
        FPS             = video_fps
        frames_per_line = int(secs_per_line * FPS)
        fade_frames     = min(6, frames_per_line // 5)
        BASE_ACTIVE = w // 28
        SHRINK_STEP = w // 130
        MIN_SIZE    = w // 58
        base_wm     = w // 52
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
        pad_x       = int(w * 0.05)
        header_h    = int(h * 0.10)
        pad_top     = header_h + int(h * 0.02)
        wm_zone     = int(h * 0.88)
        body_h      = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y    = pad_top + body_h // 2 - active_font_h // 2
        max_px      = w - pad_x - int(w * 0.05)
        hdr_topic_size = max(w // 22, 28)
        try:
            f_hdr_topic = ImageFont.truetype(FONT_BOLD, hdr_topic_size)
        except Exception:
            f_hdr_topic = ImageFont.load_default()
        hdr_line1 = topic if topic else channel
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
        t0 = time.time()
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
                img  = Image.new("RGB", (w, h), (0, 0, 0))
                draw = ImageDraw.Draw(img)
                hdr_bbox = draw.textbbox((0, 0), hdr_line1, font=f_hdr_topic)
                hdr_w    = hdr_bbox[2] - hdr_bbox[0]
                hdr_x    = (w - hdr_w) // 2
                hdr_y    = int(h * 0.018)
                draw.text((hdr_x, hdr_y), hdr_line1, font=f_hdr_topic, fill=(255, 255, 255))
                sep_y = header_h - 2
                draw.line([(pad_x, sep_y), (w - pad_x, sep_y)], fill=(50, 60, 80), width=1)
                past_indices = list(range(max(0, line_idx - 30), line_idx))
                past_indices.reverse()
                y_cursor = active_y
                for age, pi in enumerate(past_indices, start=1):
                    fnt    = get_font(age)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    y_pos  = y_cursor - line_h
                    if y_pos < pad_top: break
                    brightness = max(25, 160 - age * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_pos, lines[pi], fnt, max_px, c)
                    y_cursor = y_pos
                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)
                future_start = active_y + active_font_h + int(h * 0.025)
                y_cursor     = future_start
                for ahead, fi2 in enumerate(range(line_idx + 1, min(line_idx + 20, len(lines))), start=1):
                    fnt    = get_font(ahead)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - ahead * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    if y_cursor + line_h > wm_zone: break
                    brightness = max(18, 110 - ahead * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_cursor, lines[fi2], fnt, max_px, c)
                    y_cursor += line_h
                prog   = (line_idx * frames_per_line + fi) / total_frames
                bar_y  = h - 2
                filled = int(w * prog)
                draw.line([(0, bar_y), (w - 1, bar_y)], fill=(40, 40, 40), width=1)
                if filled > 0:
                    draw.line([(0, bar_y), (filled, bar_y)], fill=(200, 200, 200), width=1)
                tag      = wm_text if wm_enabled else f"@{channel}"
                tw_bbox = draw.textbbox((0, 0), tag, font=f_wm)
                tw      = tw_bbox[2] - tw_bbox[0]
                wm_x    = (w - tw) // 2
                wm_y    = wm_zone + int(h * 0.02)
                draw.text((wm_x, wm_y), tag, font=f_wm, fill=(30, 30, 38))
                proc.stdin.write(img.tobytes())
                global_frame += 1
                if pbar is not None: pbar.update(1)
        if pbar is not None: pbar.close()
        proc.stdin.close()
        proc.wait()
        elapsed = time.time() - t0
        print(f"[DebateVideo]   ✅ Encoded in {elapsed:.0f}s ({elapsed/60:.1f}min)")

    def _get_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1:noprint_wrappers=1',
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return float(result.stdout.strip())
        except Exception:
            return 60.0  # Default fallback

    def _generate_tts(self, text: str, output_audio: str, duration: float) -> bool:
        """Generate TTS audio using edge-tts or festival."""
        try:
            import edge_tts
            import asyncio

            async def generate():
                communicate = edge_tts.Communicate(text, "en-US")
                await communicate.save(output_audio)

            asyncio.run(generate())
            print(f"[DebateVideo] 🔊 TTS generated: {output_audio}")
            return True
        except Exception as e:
            print(f"[DebateVideo] ⚠️ Edge-TTS failed, trying festival: {e}")
            try:
                # Fallback to festival
                with open('/tmp/debate_text.txt', 'w') as f:
                    f.write(text)
                cmd = f"festival --tts /tmp/debate_text.txt --output-file {output_audio}"
                result = subprocess.run(cmd, shell=True, capture_output=True)
                if result.returncode == 0:
                    print(f"[DebateVideo] 🔊 Festival TTS generated: {output_audio}")
                    return True
            except Exception as e2:
                print(f"[DebateVideo] ❌ Festival TTS also failed: {e2}")
            return False

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str, duration: float) -> bool:
        """Merge audio with video using ffmpeg."""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-shortest',
                output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"[DebateVideo] 🎵 Audio merged: {output_path}")
            return True
        except Exception as e:
            print(f"[DebateVideo] ❌ Merge failed: {e}")
            return False
