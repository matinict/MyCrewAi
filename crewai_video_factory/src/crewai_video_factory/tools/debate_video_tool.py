"""
Debate Video Tool (CLEAN VERSION)
- Strict Source Separation: Shorts use *-m.md ONLY, HD uses *.md ONLY.
- NO Text Cleaning: Speaks exact original content from .md files.
- NO Logic Filtering: Reads full content of the source file (no Arg1 cutoff).
- NO Auto-Outro: Disclaimer/Subscribe lines removed.
1.  **Strict Source Separation**:
    *   **Shorts** now **ONLY** read from `*-m.md` files.
    *   **HD/4K** now **ONLY** read from `*.md` files.
    *   Removed all fallback logic that might mix sources.
2.  **Zero Text Cleaning for Voice**:
    *   Disabled `_clean_text()` calls in `_parse_lines`, `_lines_to_spoken`, and `_section_to_spoken`.
    *   The TTS engine will now speak the **exact original text** from your markdown files (preserving symbols, formatting, and full sentences).
3.  **Removed Shorts Logic Filtering**:
    *   Even for Shorts, the tool now reads the **entire content** of the `-m.md` file. It no longer stops at "Argument 1". Since you are generating the `-m.md` files separately with the correct length, the video tool simply plays what is there.
4.  **Disabled Auto-Appended Outro**:
    *   Commented out the automatic addition of "Disclaimer" and "Subscribe" lines to ensure only your file content is spoken/shown.

Debate Video Tool
Bottom-to-top streaming debate visualization — identical rendering engine to definition_video_tool.py:
New (active) line appears at BOTTOM, bold, large, neon white glow
Previous lines scroll UP, shrinking smaller as they rise
Pure black background, all text white
Pixel-accurate word wrap — never breaks a word
Bottom 33% clear for YouTube subtitles
gTTS audio + atempo sync (same as definition_video_tool)
Input files: propose.md, oppose.md, decide.md in output/{filename}/
Triggered by: "debate_video_enabled": true in data.json
Output: debate_video_[format].mp4 + _audio.mp3 + _with_audio.mp4 in output/{filename}/
NO MERGE HERE — debate_merge_tool.py handles final concatenation
ALL CONFIG FROM data.json — NO HARDCODED VALUES
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

# ── DEFAULT VOICE CONFIG (only used if data.json provides nothing) ─────────
DEFAULT_PIPER_VOICES = {
    "propose": {"model": "models/alba_medium.onnx", "speed": 1.05},
    "oppose":  {"model": "models/en_GB-scott-medium.onnx", "speed": 1.0},
    "decide":  {"model": "models/joe_medium.onnx", "speed": 0.95},
}

DEFAULT_EDGE_TTS_VOICES = {
    "propose": "en-US-AriaNeural",
    "oppose":  "en-US-GuyNeural",
    "decide":  "en-GB-RyanNeural",
}

def _clean_text(text: str) -> str:
    """
    Kept for compatibility but NOT USED in parsing pipeline anymore.
    Converts Mathematical Alphanumeric Symbols to plain ASCII.
    """
    import unicodedata
    replacements = {
        '–': '-', '—': '--', '…': '...',
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '·': '.', '•': '-',
    }
    for uni, ascii_equiv in replacements.items():
        text = text.replace(uni, ascii_equiv)
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('ascii')

class DebateVideoInput(BaseModel):
    """Input schema for DebateVideoTool — ALL from data.json."""
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
    tts_engine:           str   = Field(default="gtts", description="TTS engine: 'gtts', 'edge-tts', or 'piper'")
    tts_voices:           dict  = Field(default_factory=dict, description="Per-section voice overrides from data.json")
    lang_suffix:          str   = Field(default="En", description="Language suffix for output filenames.")
    bg_opacity:           int   = Field(default=255, description="Background opacity")
    debate_background_enabled: bool = Field(default=False, description="Composite debate_bg_{fmt}.mp4 behind debate text")
    debate_background_prompt:  str  = Field(default="",    description="Prompt used to generate background")
    image_gen_backend:         str  = Field(default="auto", description="Backend used for background generation")

class DebateVideoTool(BaseTool):
    """
    Creates bottom-to-top streaming debate video.
    STRICT SOURCE RULES:
      - Shorts formats MUST use propose-m.md, oppose-m.md, decide-m.md
      - HD/4K formats MUST use propose.md, oppose.md, decide.md
    NO CLEANING: Raw text is passed directly to TTS.
    """
    name: str = "Debate Video Tool"
    description: str = (
        "Generates a debate video with bottom-to-top streaming text animation. "
        "Reads propose/oppose/decide .md files. Shorts use '-m.md' variants. "
        "NO text cleaning applied; speaks original content exactly."
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
        tts_voices: dict = None,
        lang_suffix: str = "En",
        bg_opacity: int = 255,
        debate_background_enabled: bool = False,
        debate_background_prompt: str = "",
        image_gen_backend: str = "auto",
    ) -> str:

        if not debate_video_enabled:
            return "⏭️ Debate video skipped (debate_video_enabled=false)"

        # ── ALL VOICE CONFIG FROM data.json (tts_voices) ───────────────────
        _voices = {}
        if tts_voices and isinstance(tts_voices, dict):
            for role in ['propose', 'oppose', 'decide']:
                if role in tts_voices:
                    _voices[role] = tts_voices[role]
            print(f"[DebateVideo] 🎤 Voice config from data.json: {list(_voices.keys())}")
        else:
            _voices = DEFAULT_PIPER_VOICES.copy()
            print(f"[DebateVideo] 🎤 Using default voice config")

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "❌ Pillow not installed."

        if not shutil.which('ffmpeg'):
            return "❌ ffmpeg not found."

        # ── Resolve output directory ────────────────────────────────────────
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        _lang = lang_suffix if lang_suffix else "En"
        _MOBILE_FORMATS = ("Shorts", "ShortsHD", "Shorts4K")

        def _resolve_md_files(fmt: str):
            """
            STRICT RESOLUTION:
            - Mobile formats: Look ONLY for *-m.md
            - Desktop formats: Look ONLY for *.md
            No fallback between them.
            """
            _is_mobile = fmt in _MOBILE_FORMATS
            _files = {}

            for role in ("propose", "oppose", "decide"):
                if _is_mobile:
                    # STRICT MOBILE: Only check -m.md variants
                    candidates = [
                        os.path.join(output_dir, f"{role}-m_{_lang}.md"),
                        os.path.join(output_dir, f"{role}-m.md")
                    ]
                else:
                    # STRICT DESKTOP: Only check standard variants
                    candidates = [
                        os.path.join(output_dir, f"{role}_{_lang}.md"),
                        os.path.join(output_dir, f"{role}.md")
                    ]

                resolved = None
                for c in candidates:
                    if os.path.exists(c):
                        resolved = c
                        break
                _files[role] = resolved

            return _files["propose"], _files["oppose"], _files["decide"]

        results, errors = [], []

        for fmt in video_formats:
            try:
                silent_video = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}.mp4")
                audio_file   = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_audio.mp3")
                final_merged = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_with_audio.mp4")
                cc_path      = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_cc.txt")

                # ✅ SMART SKIP
                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped ({os.path.basename(final_merged)} exists)")
                    continue

                # Clean stale files
                for _stale in [final_merged, silent_video, audio_file]:
                    if os.path.exists(_stale):
                        os.remove(_stale)

                # ── Load format-specific .md content ────────────────────────
                _is_short_form = fmt in _MOBILE_FORMATS
                propose_file, oppose_file, decide_file = _resolve_md_files(fmt)

                _missing = [role for role, f in
                            [("propose", propose_file), ("oppose", oppose_file), ("decide", decide_file)]
                            if f is None]

                if _missing:
                    suffix = "-m" if _is_short_form else ""
                    for _role in _missing:
                        errors.append(f"❌ {fmt}: {_role}{suffix}.md not found in {output_dir}")
                    continue

                with open(propose_file, 'r', encoding='utf-8') as f:
                    pro_text = f.read().strip()
                with open(oppose_file, 'r', encoding='utf-8') as f:
                    con_text = f.read().strip()
                with open(decide_file, 'r', encoding='utf-8') as f:
                    moderator_text = f.read().strip()

                print(f"[DebateVideo] [{fmt}] 📄 propose: {os.path.basename(propose_file)}")
                print(f"[DebateVideo] [{fmt}] 📄 oppose:  {os.path.basename(oppose_file)}")
                print(f"[DebateVideo] [{fmt}] 📄 decide:  {os.path.basename(decide_file)}")

                # ── Combine into single narrative ─────────────────────────
                raw = "\n\n".join([
                    f"PROPOSITION:\n{pro_text}",
                    f"OPPOSITION:\n{con_text}",
                    f"VERDICT:\n{moderator_text}",
                ])

                # ── Parse lines ─────────────────────────────────────────────
                # short_form flag is passed but logic inside _parse_lines is disabled
                # to ensure FULL content of the source file is used.
                raw_lines = self._parse_lines(raw, short_form=_is_short_form)

                # ❌ DISABLED: Auto-append disclaimer/subscribe
                # We want ONLY the content from the .md files to be spoken.
                # _disclaimer_text = ...
                # raw_lines.append(...)

                _debate_line_count = len(raw_lines)

                spoken_text = self._lines_to_spoken(raw_lines, topic, channel)

                print(f"[DebateVideo] [{fmt}] Parsed {len(raw_lines)} lines (Full content from source)")

                # ── Save narration text ───────────────────────────────────
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(spoken_text)

                # ── Build per-section spoken text ────────────────────────
                # Pass short_form=True but internal filtering is disabled
                _pro_spoken = self._section_to_spoken(pro_text, "propose", channel, short_form=_is_short_form)
                _con_spoken = self._section_to_spoken(con_text, "oppose", channel, short_form=_is_short_form)
                _mod_spoken = self._section_to_spoken(moderator_text, "decide", channel, short_form=_is_short_form)

                # Safety: if MOD parsed to empty, use raw text
                if not _mod_spoken.strip():
                    _mod_spoken = moderator_text.strip() # No cleaning

                audio_path = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_audio.mp3")
                _pro_audio = audio_path.replace('.mp3', '_pro.mp3')
                _con_audio = audio_path.replace('.mp3', '_con.mp3')
                _mod_audio = audio_path.replace('.mp3', '_mod.mp3')

                # ❌ DISABLED: Disclaimer/Subscribe audio generation

                # ── STEP 1: Generate each clip separately ─────────────────
                print(f"[DebateVideo] [{fmt}] 🔊 Step 1/3 — Generate per-section audio clips …")

                self._tts_single(_pro_spoken, _pro_audio, tts_engine, _voices, role="propose")
                self._tts_single(_con_spoken, _con_audio, tts_engine, _voices, role="oppose")
                self._tts_single(_mod_spoken, _mod_audio, tts_engine, _voices, role="decide")
                # ❌ DISABLED: Disclaimer/Subscribe audio

                _pro_dur = self._get_duration(_pro_audio) if os.path.exists(_pro_audio) else 0.0
                _con_dur = self._get_duration(_con_audio) if os.path.exists(_con_audio) else 0.0
                _mod_dur = self._get_duration(_mod_audio) if os.path.exists(_mod_audio) else 0.0
                # ❌ DISABLED: Disclaimer/Subscribe duration

                print(f"[DebateVideo]   PRO={_pro_dur:.1f}s  CON={_con_dur:.1f}s  MOD={_mod_dur:.1f}s")

                # ── STEP 2: Assemble final audio ──────────────────────────
                print(f"[DebateVideo] [{fmt}] 🔊 Step 2/3 — Assemble final audio …")
                _clips_exist = [c for c in [_pro_audio, _con_audio, _mod_audio] if os.path.exists(c)]

                if not _clips_exist:
                    errors.append(f"❌ {fmt}: no audio clips produced")
                    continue

                if len(_clips_exist) == 1:
                    os.replace(_clips_exist[0], audio_path)
                else:
                    _inputs = []
                    for c in _clips_exist:
                        _inputs += ["-i", c]
                    n = len(_clips_exist)
                    _resample = " ".join(f"[{i}:a]aresample=44100[a{i}]; " for i in range(n))
                    _concat_in = " ".join(f"[a{i}] " for i in range(n))
                    _filter = f"{_resample}{_concat_in}concat=n={n}:v=0:a=1[aout]"

                    _r = subprocess.run(
                        ["ffmpeg", "-y"] + _inputs +
                        ["-filter_complex", _filter, "-map", "[aout]", "-q:a", "2", audio_path],
                        capture_output=True, check=False
                    )
                    if _r.returncode != 0 or not os.path.exists(audio_path):
                        print(f"[DebateVideo] ⚠️ concat failed, using first clip")
                        os.replace(_clips_exist[0], audio_path)

                for _tmp in [_pro_audio, _con_audio, _mod_audio]:
                    if os.path.exists(_tmp):
                        os.remove(_tmp)

                # ── STEP 3: Build per-line frame map then render ──────────
                print(f"[DebateVideo] [{fmt}] 🎬 Step 3/3 — Render video synced per-section …")
                out_path = silent_video
                is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                w, h = (1080, 1920) if is_portrait else (1920, 1080)

                _frames_map = self._build_frames_map(
                    raw_lines, w, video_fps,
                    _pro_dur, _con_dur, _mod_dur,
                    0.0, 0.0, # disc_dur, sub_dur (disabled)
                    secs_per_line
                )

                _audio_dur = self._get_duration(audio_path)
                _video_est = sum(_frames_map.values()) / video_fps
                print(f"[DebateVideo]   audio={_audio_dur:.1f}s  video_est={_video_est:.1f}s")

                self._render(raw_lines, out_path, w, h, secs_per_line,
                             channel, watermark_enabled, watermark_text,
                             video_fps, topic=topic, bg_opacity=bg_opacity, bg_color=(0,0,0),
                             frames_per_line_map=_frames_map)

                # ── Composite background video if available ────────────────
                if debate_background_enabled:
                    _bg_vid = os.path.join(output_dir, f"debate_bg_{fmt}.mp4")
                    if os.path.exists(_bg_vid):
                        _comp = out_path.replace('.mp4', '_comp.mp4')
                        _op = max(0.0, min(1.0, bg_opacity / 255.0))
                        _cmd_comp = [
                            "ffmpeg", "-y",
                            "-i", _bg_vid, "-i", out_path,
                            "-filter_complex",
                            f"[0:v]scale={w}:{h},setpts=PTS-STARTPTS[bg]; "
                            f"[1:v]setpts=PTS-STARTPTS[fg]; "
                            f"[bg][fg]blend=all_mode=overlay:all_opacity={_op:.2f}[out]",
                            "-map", "[out]",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-r", str(video_fps),
                            "-t", str(self._get_duration(out_path)), _comp
                        ]
                        _cr = subprocess.run(_cmd_comp, capture_output=True)
                        if _cr.returncode == 0 and os.path.exists(_comp):
                            os.replace(_comp, out_path)
                            print(f"[DebateVideo] ✅ Background composited")

                if not os.path.exists(out_path):
                    errors.append(f"❌ {fmt}: video missing after render")
                    continue

                video_dur = self._get_duration(out_path)
                _final_dur = max(video_dur, _audio_dur)

                self._merge_audio_video(out_path, audio_path, final_merged, _final_dur)

                if os.path.exists(final_merged):
                    merged_kb = os.path.getsize(final_merged) // 1024
                    results.append(f"✅ {fmt}: {os.path.basename(final_merged)} ({merged_kb} KB) Duration: {_final_dur:.1f}s")
                else:
                    errors.append(f"❌ {fmt}: Final merge failed")

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

    # ── Helpers ───────────────────────────────────────────────────────────

    def _lines_to_spoken(self, lines: list, topic: str, channel: str) -> str:
        """Convert display tuples to spoken narration. NO CLEANING."""
        parts = []
        for item in lines:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text = ' '.join(parts)
        # ❌ REMOVED: text = _clean_text(text)
        return text

    def _section_to_spoken(self, raw_md: str, role: str, channel: str, short_form: bool = True) -> str:
        """Convert a single debate section to spoken text. NO CLEANING, NO FILTERING."""
        items = self._parse_lines(raw_md, default_section=role, short_form=short_form)
        parts = []
        for item in items:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text = ' '.join(parts)
        # ❌ REMOVED: text = _clean_text(text)
        return text

    def _get_duration(self, video_path: str) -> float:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True
        )
        try:
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _tts_single(self, text: str, out_path: str, engine: str, voices: dict, role: str = "decide"):
        eng = engine.strip().lower()
        if not text.strip():
            print(f"[DebateVideo] ⚠️ _tts_single: empty text for role={role} — skipped")
            return

        if eng == "piper":
            _v = voices if voices else DEFAULT_PIPER_VOICES
            vcfg = _v.get(role, DEFAULT_PIPER_VOICES.get(role, {}))
            import tempfile
            tmp_dir = tempfile.mkdtemp(prefix="debate_single_")
            wav_out = os.path.join(tmp_dir, "single.wav")
            model_path = vcfg.get("model", "") if isinstance(vcfg, dict) else ""
            if not os.path.isabs(model_path):
                model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), model_path)

            if model_path and os.path.exists(model_path):
                speed = vcfg.get("speed", 1.0) if isinstance(vcfg, dict) else 1.0
                r = subprocess.run(
                    ["piper", "--model", model_path,
                     "--length_scale", str(1.0 / max(0.1, speed)),
                     "--output_file", wav_out],
                    input=text.encode(), capture_output=True, check=False
                )
                if r.returncode == 0 and os.path.exists(wav_out):
                    subprocess.run(["ffmpeg", "-y", "-i", wav_out, "-q:a", "2", out_path], capture_output=True)
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return
            shutil.rmtree(tmp_dir, ignore_errors=True)
            self._tts_gtts(text, out_path)

        elif eng == "edge-tts":
            _v = voices if voices else {}
            vcfg = _v.get(role, "")
            if isinstance(vcfg, str) and vcfg.strip():
                voice = vcfg.strip()
            elif isinstance(vcfg, dict):
                voice = vcfg.get("edge_voice", DEFAULT_EDGE_TTS_VOICES.get(role, "en-US-AriaNeural"))
            else:
                voice = DEFAULT_EDGE_TTS_VOICES.get(role, "en-US-AriaNeural")

            print(f"[DebateVideo] 🎤 {role} | voice={voice}")
            self._tts_edge(text, out_path, voice=voice)
        else:
            self._tts_gtts(text, out_path)

    def _tts_gtts(self, text: str, out_path: str):
        import tempfile, os
        try:
            from gtts import gTTS
        except ImportError:
            print("[DebateVideo] ⚠️ gTTS not installed.")
            return
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.mp3')
        os.close(tmp_fd)
        try:
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(tmp_path)
            size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if size < 1000:
                raise RuntimeError(f"gTTS output too small ({size} bytes)")
            os.replace(tmp_path, out_path)
            print(f"[DebateVideo] ✅ gTTS saved: {out_path}")
        except Exception as e:
            print(f"[DebateVideo] ⚠️ gTTS failed: {e}")
            if os.path.exists(tmp_path): os.remove(tmp_path)
            if os.path.exists(out_path): os.remove(out_path)

    def _run_async(self, coro, timeout: int = 60):
        import asyncio, threading
        result_holder = [None]
        error_holder = [None]
        def _thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_holder[0] = loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
            except Exception as exc:
                error_holder[0] = exc
            finally:
                loop.close()
        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()
        t.join(timeout=timeout + 10)
        if t.is_alive(): raise TimeoutError(f"Thread timed out")
        if error_holder[0]: raise error_holder[0]
        return result_holder[0]

    def _tts_edge(self, text: str, out_path: str, voice: str = "en-US-AriaNeural", timeout: int = 60):
        try:
            import edge_tts
        except ImportError:
            print("[DebateVideo] ⚠️ edge-tts not installed — falling back to gTTS")
            self._tts_gtts(text, out_path)
            return

        async def _generate():
            communicate = edge_tts.Communicate(text, voice=voice)
            await communicate.save(out_path)

        try:
            self._run_async(_generate(), timeout=timeout)
            if not os.path.exists(out_path):
                raise RuntimeError("edge-tts produced no output file")
        except Exception as e:
            print(f"[DebateVideo] ⚠️ edge-tts failed ({e}) — falling back to gTTS")
            if os.path.exists(out_path): os.remove(out_path)
            self._tts_gtts(text, out_path)

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str, target_duration: float):
        print(f"[DebateVideo] 🎬 Merging audio+video → {os.path.basename(output_path)}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-filter_complex", f"[1:a]apad=whole_dur={target_duration:.3f}[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-t", str(round(target_duration, 3)),
            output_path
        ], capture_output=True, check=False)
        if result.returncode != 0:
            print(f"[DebateVideo] ⚠️ merge failed: {result.stderr.decode()[:200]}")

    def _build_frames_map(self, raw_lines: list, w: int, fps: int,
                          pro_dur: float, con_dur: float, mod_dur: float,
                          disc_dur: float, sub_dur: float, fallback_spl: float) -> dict:
        from PIL import ImageFont
        BASE_ACTIVE = w // 28
        pad_x = int(w * 0.05)
        max_px = w - pad_x - int(w * 0.05)
        try:
            f_active = ImageFont.truetype(FONT_BOLD, BASE_ACTIVE)
        except Exception:
            f_active = ImageFont.load_default()

        wrapped: list = []
        for item in raw_lines:
            raw_text, sec = item if isinstance(item, tuple) else (item, 'propose')
            for w_line in self._pixel_wrap(raw_text, f_active, max_px):
                wrapped.append((w_line, sec))

        total = len(wrapped)
        if total == 0: return {}

        # Since we disabled disclaimer/subscribe, disc_idx/sub_idx logic is simplified
        # But keeping structure for safety if you re-enable later
        disc_idx = total - 2 if total >= 2 and disc_dur > 0 else total
        sub_idx = total - 1 if total >= 1 and sub_dur > 0 else total

        sec_counts = {'propose': 0, 'oppose': 0, 'decide': 0}
        for i, (_, sec) in enumerate(wrapped):
            if i >= disc_idx: break
            sec_counts[sec] = sec_counts.get(sec, 0) + 1

        def _spl(sec_dur, count):
            if count <= 0: return fallback_spl
            v = sec_dur / count
            return max(1.0, min(12.0, v))

        _pro_spl = _spl(pro_dur, sec_counts.get('propose', 0))
        _con_spl = _spl(con_dur, sec_counts.get('oppose', 0))
        _mod_spl = _spl(mod_dur, sec_counts.get('decide', 0))
        _disc_spl = max(1.0, disc_dur) if disc_dur > 0 else fallback_spl
        _sub_spl = max(1.0, sub_dur) if sub_dur > 0 else fallback_spl

        fmap = {}
        for i, (_, sec) in enumerate(wrapped):
            if total >= 2 and i == sub_idx and sub_dur > 0: spl = _sub_spl
            elif total >= 2 and i == disc_idx and disc_dur > 0: spl = _disc_spl
            elif sec == 'propose': spl = _pro_spl
            elif sec == 'oppose': spl = _con_spl
            else: spl = _mod_spl
            fmap[i] = max(1, int(round(spl * fps)))
        return fmap

    def _parse_lines(self, raw: str, default_section: str = 'propose', short_form: bool = True) -> List[Tuple[str, str]]:
        """
        Parse debate markdown into (line_text, section) tuples.

        CHANGED BEHAVIOR:
        - NO CLEANING: Text is preserved exactly as in .md
        - NO FILTERING: Even if short_form=True, it reads ALL lines.
          (Assumes the source -m.md file is already the correct length).
        """
        result = []
        section = default_section

        _section_map = [
            (re.compile(r'^PROP(?:OSITION)?\s*[:\-]?', re.I), 'propose'),
            (re.compile(r'^OPP(?:OSITION)?\s*[:\-]?', re.I), 'oppose'),
            (re.compile(r'^VERDICT\s*[:\-]?', re.I), 'decide'),
            (re.compile(r'^VERD?\s*[:\-]?', re.I), 'decide'),
            (re.compile(r'^MODERATOR\s*[:\-]?', re.I), 'decide'),
            (re.compile(r'^JUDGE\s*[:\-]?', re.I), 'decide'),
        ]

        _skip = [
            re.compile(r'^-{3,}$'),
            re.compile(r'^\*{3,}$'),
            re.compile(r'^#{1,6}\s+'),
        ]

        # LOGIC CHANGE: Treat short_form and full_form identically regarding content inclusion.
        # We assume the input file (-m.md vs .md) already has the correct content.

        include_content = True
        decide_decision_reached = False

        _decision_re = re.compile(r'^(?:DECISION|DECIS(?:ION)?|DECID(?:E)?|DEC)\s*[:\-]?', re.I)

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("━") or line.startswith("─") or line.startswith("==="):
                continue

            # ❌ REMOVED: Emoji stripping
            # ❌ REMOVED: Bold stripping (**text**)
            # ❌ REMOVED: Link stripping [...]
            # ❌ REMOVED: _clean_text(line) call

            if not line: continue

            # Detect section changes
            matched_section = next((role for p, role in _section_map if p.match(line)), None)
            if matched_section:
                _pat = next(p for p, role in _section_map if role == matched_section and p.match(line))
                _rest_of_header = line[_pat.match(line).end():].strip()
                if matched_section != section:
                    section = matched_section
                    include_content = True
                    decide_decision_reached = False
                    print(f"[DebateVideo] 📄 Section switch: {section}")
                # Capture any content on the same line as the header (e.g. "Verd: text...")
                # Split long inline content at sentence boundaries for readable display
                if _rest_of_header:
                    _rest_of_header = _rest_of_header[0].upper() + _rest_of_header[1:]
                    if len(_rest_of_header) > 120:
                        for _sent in re.split(r'(?<=[.!?])\s+', _rest_of_header):
                            _sent = _sent.strip()
                            if _sent:
                                result.append((_sent[0].upper() + _sent[1:], section))
                    else:
                        result.append((_rest_of_header, section))
                continue

            # Handle DECISION header specifically to ensure we start capturing after it
            if _decision_re.match(line):
                if section == 'decide':
                    decide_decision_reached = True
                    include_content = True
                    rest = line[_decision_re.match(line).end():].strip()
                    if rest:
                        result.append((rest, section))
                continue

            # Skip structural headers only (e.g., "Argument 1:"), but KEEP the content below
            if re.match(r'^(ARGUMENT|POINT|COUNTER[\s\-]?ARGUMENT|OPENING|CLOSING|CONCLUSION|SUMMARY)\s*[:\-]?\s*\d*$', line, re.I):
                continue

            if any(p.match(line) for p in _skip):
                continue

            # Split long single-line paragraphs at sentence boundaries
            # (e.g. decide-m.md is one giant line — break into readable chunks)
            if line:
                line = line[0].upper() + line[1:]
                # If line is very long (>120 chars), split at ". " or ". " boundaries
                if len(line) > 120:
                    import re as _re_split
                    sentences = _re_split.split(r'(?<=[.!?])\s+', line)
                    for sent in sentences:
                        sent = sent.strip()
                        if sent:
                            result.append((sent[0].upper() + sent[1:], section))
                else:
                    result.append((line, section))

        print(f"[DebateVideo] 📊 Parsed {len(result)} content lines (Raw/No-Clean)")
        return result

    def _pixel_wrap(self, text: str, font, max_px: int) -> List[str]:
        from PIL import Image as _Img, ImageDraw
        tmp = _Img.new("RGB", (1, 1))
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
        t = (math.sin((frame % 96) / 96.0 * 2 * math.pi) + 1) / 2
        halo = (int(50*t*alpha), int(130*t*alpha), int(210*t*alpha))
        inner = (int(150*t*alpha), int(210*t*alpha), int(255*t*alpha))
        face = self._neon_white(alpha, frame)
        bloom = (int(255*alpha), int(255*alpha), int(255*alpha))
        draw.text((x+2, y+2), text, font=font, fill=halo)
        draw.text((x+1, y+1), text, font=font, fill=inner)
        draw.text((x, y), text, font=font, fill=face)
        draw.text((x-1, y-1), text, font=font, fill=bloom)

    def _draw_diamond_title(self, draw, x, y, text, font, frame: int):
        import math
        t = (frame % 600) / 600.0
        stops = [(0.00, (255, 255, 255)), (0.25, (255, 240, 180)), (0.50, (200, 235, 255)), (0.75, (235, 210, 255)), (1.00, (255, 255, 255))]
        c0, c1, f0, f1 = stops[0][1], stops[1][1], 0.0, 0.25
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i+1][0]:
                f0, c0 = stops[i]
                f1, c1 = stops[i+1]
                break
        seg = (f1 - f0) if f1 != f0 else 1
        local_t = (t - f0) / seg
        local_t = local_t * local_t * (3 - 2 * local_t)
        face_col = tuple(int(c0[i] + (c1[i] - c0[i]) * local_t) for i in range(3))
        shadow = (int(face_col[0]*0.08), int(face_col[1]*0.08), int(face_col[2]*0.08))
        for dx, dy in [(-3,3),(3,3),(-3,-3),(3,-3)]:
            draw.text((x+dx, y+dy), text, font=font, fill=shadow)
        bloom = (int(face_col[0]*0.35), int(face_col[1]*0.35), int(face_col[2]*0.35))
        for dx, dy in [(-2,2),(2,2),(-2,-2),(2,-2),(2,0),(-2,0),(0,2),(0,-2)]:
            draw.text((x+dx, y+dy), text, font=font, fill=bloom)
        inner = (int(face_col[0]*0.65), int(face_col[1]*0.65), int(face_col[2]*0.65))
        for dx, dy in [(-1,1),(1,1),(-1,-1),(1,-1),(1,0),(-1,0),(0,1),(0,-1)]:
            draw.text((x+dx, y+dy), text, font=font, fill=inner)
        draw.text((x, y), text, font=font, fill=face_col)

    def _justify(self, draw, x, y, text, font, max_w, fill):
        words = text.split()
        if len(words) <= 1:
            draw.text((x, y), text, font=font, fill=fill)
            return
        word_widths = []
        for w2 in words:
            bb = draw.textbbox((0, 0), w2, font=font)
            word_widths.append(bb[2] - bb[0])
        sp_bb = draw.textbbox((0, 0), ' ', font=font)
        sp_w = sp_bb[2] - sp_bb[0]
        natural_w = sum(word_widths) + sp_w * (len(words) - 1)
        if natural_w < max_w * 0.65:
            draw.text((x, y), text, font=font, fill=fill)
            return
        gap = (max_w - sum(word_widths)) / max(len(words) - 1, 1)
        cx = x
        for word, ww in zip(words, word_widths):
            draw.text((int(cx), y), word, font=font, fill=fill)
            cx += ww + gap

    def _render(self, raw_lines, out_path, w, h, secs_per_line, channel, wm_enabled, wm_text, video_fps, topic="", bg_opacity=255, bg_color=(0,0,0), frames_per_line_map: dict = None):
        from PIL import Image, ImageDraw, ImageFont
        FPS = video_fps
        _default_fpl = max(1, int(secs_per_line * FPS))
        fade_frames = min(6, _default_fpl // 5)
        BASE_ACTIVE = w // 28
        SHRINK_STEP = w // 130
        MIN_SIZE = w // 58
        base_wm = w // 52

        try:
            f_active = ImageFont.truetype(FONT_BOLD, BASE_ACTIVE)
            f_wm = ImageFont.truetype(FONT_BOLD, base_wm)
        except Exception:
            f_active = f_wm = ImageFont.load_default()

        def get_font(age: int):
            size = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
            try:
                return ImageFont.truetype(FONT_BOLD if age == 0 else FONT_REGULAR, size)
            except Exception:
                return ImageFont.load_default()

        pad_x = int(w * 0.05)
        header_h = int(h * 0.17)
        pad_top = header_h + int(h * 0.02)
        wm_zone = int(h * 0.80)
        body_h = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y = pad_top + body_h // 2 - active_font_h // 2
        max_px = w - pad_x - int(w * 0.05)

        # Header Title Processing (Minimal cleaning just for layout safety, not voice)
        hdr_title = topic if topic else channel
        _acronyms = {'ai', 'ml', 'api', 'ui', 'ux', 'llm', 'gpt', 'ceo', 'cto', 'it'}
        hdr_title = ' '.join(_word.upper() if _word.lower() in _acronyms else _word.capitalize() for _word in hdr_title.split())
        hdr_max_px = w - pad_x * 2

        hdr_topic_size = max(w // 30, 22)
        f_hdr_topic = None
        for size in range(hdr_topic_size, 18, -2):
            try: _f = ImageFont.truetype(FONT_BOLD, size)
            except: _f = ImageFont.load_default()
            hdr_lines = self._pixel_wrap(hdr_title, _f, hdr_max_px)
            from PIL import Image as _TmpImg, ImageDraw as _TmpDraw
            _tmp = _TmpImg.new("RGB", (1, 1))
            _d = _TmpDraw.Draw(_tmp)
            max_line_w = max((_d.textbbox((0,0), ln, font=_f)[2] - _d.textbbox((0,0), ln, font=_f)[0]) for ln in hdr_lines)
            if max_line_w <= hdr_max_px:
                hdr_topic_size = size
                f_hdr_topic = _f
                break
        if f_hdr_topic is None:
            try: f_hdr_topic = ImageFont.truetype(FONT_BOLD, 18)
            except: f_hdr_topic = ImageFont.load_default()
            hdr_lines = self._pixel_wrap(hdr_title, f_hdr_topic, hdr_max_px)

        #lines_ List[Tuple[str, str]] = []
        lines_data: List[Tuple[str, str]] = []
        for item in raw_lines:
            raw_text, sec = item if isinstance(item, tuple) else (item, 'propose')
            for wrapped in self._pixel_wrap(raw_text, f_active, max_px):
                lines_data.append((wrapped, sec))

        _fpl_list = []
        for i in range(len(lines_data)):
            _fpl_list.append(frames_per_line_map.get(i, _default_fpl) if frames_per_line_map else _default_fpl)

        total_frames = sum(_fpl_list)
        print(f"[DebateVideo] Wrapped lines: {len(lines_data)} Total frames: {total_frames}")

        cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-s', f'{w}x{h}', '-pix_fmt', 'rgb24', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        t0 = time.time()

        try:
            from tqdm import tqdm
            import sys
            pbar = tqdm(total=total_frames, desc=f" 🎬 [{out_path.split('/')[-1]}] ", unit="fr", bar_format="{desc}: {percentage:3.0f}%|{bar:35}| {n_fmt}/{total_fmt} fr [{elapsed} <{remaining}, {rate_fmt}]", dynamic_ncols=True, leave=True, colour="white", file=sys.stdout, position=0)
        except ImportError:
            pbar = None

        _section_labels = {'propose': 'Proposition', 'oppose': 'Opposition', 'decide': 'Verdict'}
        _sec_rgb = {'propose': (130, 210, 255), 'oppose': (255, 100, 100), 'decide': (140, 255, 140)}
        _prev_section = None

        import math as _math, random as _random
        _bg_v = max(0, min(255, bg_opacity))

        # ── Animated gradient background (same style as intro_clip_tool) ────
        def _gradient_base(frame_idx: int) -> Image.Image:
            shift = (frame_idx / max(total_frames, 1)) * _math.pi * 2
            _gi = Image.new('RGB', (w, h))
            _px = _gi.load()
            for _gy in range(h):
                _t = _gy / h
                _r0 = int(8  + 20  * _t)
                _g0 = int(6  + 10  * _t)
                _b0 = int(30 + 60  * _t)
                _wave = 0.5 + 0.5 * _math.sin(shift + _t * _math.pi * 3)
                _r1 = int(min(255, _r0 + 80  * _wave * (1 - _t)))
                _g1 = int(min(255, _g0 + 40  * _wave * _t))
                _b1 = int(min(255, _b0 + 120 * _wave))
                for _gx in range(w):
                    _px[_gx, _gy] = (_r1, _g1, _b1)
            return _gi

        _rng = _random.Random(42)
        _DEBATE_WORDS = [
            '?', '!', '...', '??', '?!',
            'Why', 'How', 'Who', 'Where', 'When', 'What', 'Which',
            'Yes', 'No', 'True', 'False', 'Pro', 'Con',
            'Agree', 'Disagree', 'For', 'Against',
            'AI', 'AGI', 'LLM', 'GPT', 'Bot', 'Data',
            'Code', 'Mind', 'Brain', 'Logic', 'Think',
            'Rights', 'Ethics', 'Human', 'Future', 'Risk',
            'Power', 'Truth', 'Bias', 'Fear', 'Trust',
            'Debate', 'Proof', 'Fact', 'Myth', 'Law',
        ]
        _N_PARTICLES = max(60, w // 16)
        _particles = [
            {
                'x':       _rng.uniform(0, w),
                'y':       _rng.uniform(0, h),
                'vx':      _rng.uniform(-0.3, 0.3) * (w / 1080),
                'vy':      _rng.uniform(0.4, 2.0) * (h / 1080),
                'font_size': _rng.randint(14, 32),
                'alpha':   _rng.randint(60, 180),
                'phase':   _rng.uniform(0, _math.tau),
                'word':    _DEBATE_WORDS[_rng.randint(0, len(_DEBATE_WORDS) - 1)],
            }
            for _ in range(_N_PARTICLES)
        ]

        _av_y = int(h * 0.875)
        _av_r = int(w * 0.080)
        _av_margin = int(_av_r * 1.34 * 1.15) + int(w * 0.010)
        _av_left = max(_av_margin, int(w * 0.16))
        _av_right = min(w - _av_margin, int(w * 0.84))
        _av_mid = w // 2
        _av_colors = {'propose': (100, 180, 255), 'oppose': (255, 90, 90), 'decide': (120, 240, 140)}
        _av_labels = {'propose': 'PRO', 'oppose': 'OPPO', 'decide': 'Verdict'}

        _WV_BARS = 32
        _WV_W = int(w * 0.38)
        _WV_H = int(h * 0.048)
        _WV_Y = _av_y + _av_r + int(h * 0.012)
        _flash_frames = int(FPS * 0.35)
        _flash_counter = 0
        _section_frame = 0
        _prev_sec_for_fr = None

        def _draw_avatar(draw, cx, cy, r, role, speaking, frame):
            import math as _m
            ac = _av_colors.get(role, (200, 200, 200))
            dim = tuple(int(c * 0.28) for c in ac)
            if speaking:
                wing_flap = _m.sin(frame * 0.22)
                wing_raise = int(r * 0.55 * abs(wing_flap))
                wing_span = int(r * 1.10)
                wing_thick = max(2, int(r * 0.10))
                for wi, (wspan, wthick, walpha) in enumerate([(wing_span, wing_thick, 140), (wing_span + r//3, wing_thick - 1, 80), (wing_span + r//2, max(1, wing_thick - 2), 40)]):
                    w_tip_y = cy - wing_raise - wi * int(r * 0.08)
                    draw.line([cx - r + int(r*0.2), cy, cx - r - wspan + int(r*0.2), w_tip_y], fill=(*ac, walpha), width=wthick)
                    curl_r = max(3, int(r * 0.18))
                    draw.arc([cx - r - wspan - curl_r + int(r*0.2), w_tip_y - curl_r, cx - r - wspan + curl_r + int(r*0.2), w_tip_y + curl_r], start=0, end=180 + int(40 * wing_flap), fill=(*ac, walpha), width=max(1, wthick - 1))
                for wi, (wspan, wthick, walpha) in enumerate([(wing_span, wing_thick, 140), (wing_span + r//3, wing_thick - 1, 80), (wing_span + r//2, max(1, wing_thick - 2), 40)]):
                    w_tip_y = cy - wing_raise - wi * int(r * 0.08)
                    draw.line([cx + r - int(r*0.2), cy, cx + r + wspan - int(r*0.2), w_tip_y], fill=(*ac, walpha), width=wthick)
                    curl_r = max(3, int(r * 0.18))
                    draw.arc([cx + r + wspan - curl_r - int(r*0.2), w_tip_y - curl_r, cx + r + wspan + curl_r - int(r*0.2), w_tip_y + curl_r], start=0, end=180 - int(40 * wing_flap), fill=(*ac, walpha), width=max(1, wthick - 1))

            if speaking:
                pulse = 0.55 + 0.45 * _m.sin(frame * 0.14)
                for dr in range(8, 0, -2):
                    ga = int(65 * (9 - dr) / 8 * pulse)
                    draw.ellipse([cx-r-dr*2, cy-r-dr*2, cx+r+dr*2, cy+r+dr*2], outline=(*ac, ga), width=1)
                bob = int(r * 0.04 * _m.sin(frame * 0.08))
                head_fill = tuple(int(c * 0.38) for c in ac)
                draw.ellipse([cx-r, cy-r+bob, cx+r, cy+r+bob], fill=(*head_fill, 250), outline=(*ac, 255), width=3)
                _face_cy = cy + bob
            else:
                draw.ellipse([cx-r-1, cy-r-1, cx+r+1, cy+r+1], outline=(*ac, 30), width=1)
                head_fill = tuple(int(c * 0.07) for c in ac)
                draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*head_fill, 160), outline=(*ac, 50), width=1)
                _face_cy = cy

            eye_y = _face_cy - int(r * 0.20)
            eye_dx = int(r * 0.28)
            eye_r = max(2, int(r * 0.12))
            if speaking:
                blink = _m.sin(frame * 0.041 + 1.2) > 0.93
                eye_col = (*ac, 255)
                for ex_off in [-eye_dx, eye_dx]:
                    if not blink:
                        draw.ellipse([cx+ex_off-eye_r, eye_y-eye_r, cx+ex_off+eye_r, eye_y+eye_r], fill=eye_col)
                        sh = max(1, eye_r // 3)
                        draw.ellipse([cx+ex_off+eye_r//3, eye_y-eye_r+1, cx+ex_off+eye_r//3+sh, eye_y-eye_r+1+sh], fill=(255, 255, 255, 200))
                    else:
                        draw.line([cx+ex_off-eye_r, eye_y, cx+ex_off+eye_r, eye_y], fill=eye_col, width=max(2, eye_r//2))
                brow_y = eye_y - eye_r - int(r * 0.09)
                brow_w = int(eye_r * 1.5)
                brow_raise = int(r * 0.03 * _m.sin(frame * 0.06))
                for ex_off in [-eye_dx, eye_dx]:
                    draw.line([cx+ex_off-brow_w, brow_y - brow_raise, cx+ex_off+brow_w, brow_y - brow_raise - int(r*0.04)], fill=(*ac, 200), width=max(2, int(r * 0.06)))
            else:
                for ex_off in [-eye_dx, eye_dx]:
                    draw.ellipse([cx+ex_off-eye_r, eye_y-eye_r//2, cx+ex_off+eye_r, eye_y+eye_r//2], fill=(*ac, 45))

            mouth_cy = _face_cy + int(r * 0.26)
            mouth_w = int(r * 0.44)
            mouth_h = int(r * 0.18)
            if speaking:
                talk_open = abs(_m.sin(frame * 0.52)) * int(r * 0.20) + int(r * 0.06)
                smile_lift = int(r * 0.08)
                draw.arc([cx - mouth_w, mouth_cy - smile_lift, cx + mouth_w, mouth_cy + mouth_h + smile_lift], start=200, end=340, fill=(*ac, 255), width=max(2, int(r * 0.07)))
                inner_h = max(2, int(talk_open * 0.6))
                inner_w = int(mouth_w * 0.72)
                draw.ellipse([cx - inner_w, mouth_cy - inner_h//2, cx + inner_w, mouth_cy + inner_h], fill=(*tuple(int(c*0.12) for c in ac), 220))
                if talk_open > int(r * 0.08):
                    teeth_h = max(1, int(inner_h * 0.45))
                    draw.rectangle([cx - inner_w + 2, mouth_cy - teeth_h//2, cx + inner_w - 2, mouth_cy - teeth_h//2 + teeth_h], fill=(240, 240, 245, 200))
            else:
                draw.arc([cx - int(mouth_w*0.55), mouth_cy - int(r*0.04), cx + int(mouth_w*0.55), mouth_cy + int(r*0.10)], start=15, end=165, fill=(*ac, 38), width=max(1, int(r * 0.05)))

            if speaking:
                n_sparks = 5
                spark_ring = r + int(r * 0.55)
                for si in range(n_sparks):
                    ang = _m.tau * si / n_sparks + frame * 0.06
                    sx = cx + int(spark_ring * _m.cos(ang))
                    sy = _face_cy + int(spark_ring * _m.sin(ang))
                    spulse = 0.4 + 0.6 * abs(_m.sin(frame * 0.15 + si * 1.2))
                    sr = max(1, int(r * 0.07 * spulse))
                    sa = int(180 * spulse)
                    draw.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(*ac, sa))
                    cl = max(1, int(sr * 1.6))
                    draw.line([sx-cl, sy, sx+cl, sy], fill=(*ac, int(sa*0.6)), width=1)
                    draw.line([sx, sy-cl, sx, sy+cl], fill=(*ac, int(sa*0.6)), width=1)

            role_label = _av_labels.get(role, role.upper())
            lbl_size = max(16, int(r * 0.50)) if speaking else max(10, int(r * 0.36))
            try: _fl = ImageFont.truetype(FONT_BOLD, lbl_size)
            except: _fl = ImageFont.load_default()
            lb = draw.textbbox((0, 0), role_label, font=_fl)
            lw = lb[2] - lb[0]
            lbl_y = cy + r + int(r * 0.22)
            if speaking:
                for ddx, ddy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1)]:
                    draw.text((cx - lw//2 + ddx, lbl_y + ddy), role_label, font=_fl, fill=(*ac, 90))
                draw.text((cx - lw//2, lbl_y), role_label, font=_fl, fill=(*ac, 255))
            else:
                draw.text((cx - lw//2, lbl_y), role_label, font=_fl, fill=(*ac, 55))

        def _draw_waveform(draw, cx, cy_top, bar_w_total, bar_h_max, n_bars, frame, sec_col, speaking):
            import math as _m
            bar_w = (bar_w_total // n_bars) - 2
            bar_gap = bar_w + 2
            start_x = cx - bar_w_total // 2
            for i in range(n_bars):
                phase = i * 0.38 + frame * 0.18
                amp = 0.3 + 0.7 * abs(_m.sin(phase))
                if not speaking: amp = 0.08 + 0.06 * abs(_m.sin(phase * 0.3))
                bh = max(3, int(bar_h_max * amp))
                bx = start_x + i * bar_gap
                by = cy_top + bar_h_max - bh
                center_dist = abs(i - n_bars / 2) / (n_bars / 2)
                brightness = int(255 * (0.5 + 0.5 * (1 - center_dist)) * (0.9 if speaking else 0.3))
                bar_col = tuple(min(255, int(c * brightness / 180)) for c in sec_col)
                draw.rectangle([bx, by, bx+bar_w, cy_top+bar_h_max], fill=(*bar_col, 200 if speaking else 80))

        def _draw_particles(draw, particles, sec_col, frame):
            import math as _m
            from PIL import ImageFont as _IFont
            for p in particles:
                # debate word-snow: fall with wobble
                _wobble = _m.sin(frame * 0.03 + p['phase']) * 1.8
                _sx = int((p['x'] + frame * p['vx'] + _wobble) % w)
                _sy = int((p['y'] + frame * p['vy']) % h)
                _a  = p['alpha']
                _word = p['word']
                _fs = p['font_size']
                try:
                    _wf = _IFont.truetype(
                        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf', _fs)
                except Exception:
                    _wf = _IFont.load_default()
                # soft glow shadow
                for _dx, _dy in [(-1,1),(1,1),(-1,-1),(1,-1)]:
                    draw.text((_sx+_dx*2, _sy+_dy*2), _word, font=_wf,
                              fill=(100, 160, 255, max(0, _a // 5)))
                # bright word
                draw.text((_sx, _sy), _word, font=_wf,
                          fill=(200, 230, 255, _a))

        def _draw_flash(draw, w, h, sec_col, intensity):
            if intensity <= 0: return
            alpha = int(60 * intensity)
            draw.rectangle([0, 0, w, h], fill=(*sec_col, alpha))

        global_frame = 0
        for line_idx, (ltext, cur_section) in enumerate(lines_data):
            if line_idx > 0 and lines_data[line_idx-1][1] != cur_section:
                _flash_counter = _flash_frames
                _section_frame = 0
                _prev_sec_for_fr = cur_section

            frames_per_line = _fpl_list[line_idx]
            fade_frames = min(6, max(1, frames_per_line // 5))

            for fi in range(frames_per_line):
                alpha = min(1.0, fi / max(fade_frames, 1))
                sec_col = _sec_rgb.get(cur_section, (200, 200, 200))
                _section_frame += 1

                _base = _gradient_base(global_frame).convert("RGBA")
                img = Image.new("RGBA", (w, h), (0, 0, 0, _bg_v))
                draw = ImageDraw.Draw(img)
                _draw_particles(draw, _particles, sec_col, global_frame)

                if _flash_counter > 0:
                    _flash_intensity = _flash_counter / _flash_frames
                    _draw_flash(draw, w, h, sec_col, _flash_intensity)
                    _flash_counter -= 1

                hdr_line_h = int(hdr_topic_size * 1.35)
                hdr_y = int(h * 0.018)
                for hdr_ln in hdr_lines:
                    hdr_bbox = draw.textbbox((0, 0), hdr_ln, font=f_hdr_topic)
                    hdr_w = hdr_bbox[2] - hdr_bbox[0]
                    hdr_x = (w - hdr_w) // 2
                    self._draw_diamond_title(draw, hdr_x, hdr_y, hdr_ln, f_hdr_topic, global_frame)
                    hdr_y += hdr_line_h

                _sec_label = _section_labels.get(cur_section, cur_section.capitalize())
                _sec_size = max(w // 44, 22)
                try: _f_sec = ImageFont.truetype(FONT_BOLD, _sec_size)
                except: _f_sec = ImageFont.load_default()
                _sec_gap = int(h * 0.005)
                _sec_y = hdr_y + _sec_gap
                _sec_bbox = draw.textbbox((0, 0), _sec_label, font=_f_sec)
                _sec_w = _sec_bbox[2] - _sec_bbox[0]
                _sec_h = _sec_bbox[3] - _sec_bbox[1]
                _sec_x = (w - _sec_w) // 2
                _sec_alpha = min(1.0, fi / max(fade_frames, 1)) if cur_section != _prev_section else 1.0
                _pad_x2, _pad_y2 = int(w * 0.018), int(h * 0.004)
                _bg_badge = tuple(int(ch * 0.28 * _sec_alpha) for ch in sec_col)
                _border = tuple(int(ch * _sec_alpha) for ch in sec_col)
                draw.rectangle([_sec_x - _pad_x2, _sec_y - _pad_y2, _sec_x + _sec_w + _pad_x2, _sec_y + _sec_h + _pad_y2], fill=_bg_badge, outline=_border, width=2)
                _ca = (int(255 * _sec_alpha),) * 3
                for _dx, _dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                    draw.text((_sec_x+_dx, _sec_y+_dy), _sec_label, font=_f_sec, fill=tuple(int(ch * 0.5 * _sec_alpha) for ch in sec_col))
                draw.text((_sec_x, _sec_y), _sec_label, font=_f_sec, fill=_ca)
                _prev_section = cur_section
                _ul_y = _sec_y + _sec_h + _pad_y2 + 2
                sep_y = max(header_h - 2, _ul_y + int(h * 0.008))
                draw.line([(pad_x, sep_y), (w - pad_x, sep_y)], fill=(50, 60, 80), width=1)

                glow_h = active_font_h + int(h * 0.012)
                glow_y = active_y - int(h * 0.006)
                glow_a = int(35 * alpha)
                glow_c = tuple(int(c * 0.5) for c in sec_col)
                draw.rectangle([0, glow_y, w, glow_y + glow_h], fill=(*glow_c, glow_a))

                past_indices = list(range(max(0, line_idx - 30), line_idx))
                past_indices.reverse()
                y_cursor = active_y
                for age, pi in enumerate(past_indices, start=1):
                    fnt = get_font(age)
                    fsize = max(MIN_SIZE, BASE_ACTIVE - age * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    y_pos = y_cursor - line_h
                    if y_pos < pad_top: break
                    brightness = max(25, 160 - age * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_pos, lines_data[pi][0], fnt, max_px, c)
                    y_cursor = y_pos

                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)

                future_start = active_y + active_font_h + int(h * 0.025)
                y_cursor = future_start
                for ahead, fi2 in enumerate(range(line_idx + 1, min(line_idx + 20, len(lines_data))), start=1):
                    fnt = get_font(ahead)
                    fsize = max(MIN_SIZE, BASE_ACTIVE - ahead * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    if y_cursor + line_h > wm_zone: break
                    brightness = max(18, 110 - ahead * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_cursor, lines_data[fi2][0], fnt, max_px, c)
                    y_cursor += line_h

                import math as _mav
                _pop_frames = 18
                _pop_t = min(1.0, _section_frame / _pop_frames)
                _bounce = 1.0 + 0.25 * _mav.sin(_pop_t * _mav.pi) * (1.0 - _pop_t)
                _SPK = 1.34 * _bounce
                _SIL = 0.74
                _pro_r = int(_av_r * (_SPK if cur_section == 'propose' else _SIL))
                _con_r = int(_av_r * (_SPK if cur_section == 'oppose' else _SIL))
                _mod_r = int(_av_r * (_SPK * 0.78 if cur_section == 'decide' else _SIL * 0.72))
                _draw_avatar(draw, _av_left, _av_y, _pro_r, 'propose', cur_section == 'propose', global_frame)
                _draw_avatar(draw, _av_right, _av_y, _con_r, 'oppose', cur_section == 'oppose', global_frame)
                _draw_avatar(draw, _av_mid, _av_y, _mod_r, 'decide', cur_section == 'decide', global_frame)

                _draw_waveform(draw, w//2, _WV_Y, _WV_W, _WV_H, _WV_BARS, global_frame, sec_col, speaking=True)

                prog = (line_idx * frames_per_line + fi) / total_frames
                bar_y = h - int(h * 0.008)
                bar_h = max(3, int(h * 0.007))
                filled = int(w * prog)
                draw.rectangle([0, bar_y, w, bar_y + bar_h], fill=(25, 25, 35, 200))
                if filled > 0:
                    draw.rectangle([0, bar_y, filled, bar_y + bar_h], fill=(*sec_col, 220))

                tag = wm_text if wm_enabled else f"@{channel}"
                tw_bbox = draw.textbbox((0, 0), tag, font=f_wm)
                tw = tw_bbox[2] - tw_bbox[0]
                wm_x = (w - tw) // 2
                wm_y = wm_zone + int(h * 0.005)
                draw.text((wm_x, wm_y), tag, font=f_wm, fill=(30, 30, 38))

                _composited = Image.alpha_composite(_base, img)
                proc.stdin.write(_composited.convert("RGB").tobytes())
                global_frame += 1
                if pbar is not None: pbar.update(1)

        if pbar is not None: pbar.close()
        proc.stdin.close()
        proc.wait()
        elapsed = time.time() - t0
        print(f"[DebateVideo] ✅ Encoded in {elapsed:.0f}s")
