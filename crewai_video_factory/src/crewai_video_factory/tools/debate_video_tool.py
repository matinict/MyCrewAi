"""
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

# ── Piper voice configuration ─────────────────────────────────────────────────
# Default model paths — override in data.json via piper_voices config
PIPER_VOICES = {
    "propose": {
        "model":   "models/alba_medium.onnx",   # Female, confident
        "speed":  1.05,
    },
    "oppose": {
        "model":   "models/en_GB-scott-medium.onnx",  # Male, firm
        "speed":  1.0,
    },
    "decide": {
        "model":   "models/joe_medium.onnx",    # Male, authoritative moderator
        "speed":  0.95,
    },
}

# ── Edge-TTS 3-voice configuration ────────────────────────────────────────────
# 3 distinct neural voices for edge-tts mode — override in data.json via tts_voices
EDGE_TTS_VOICES = {
    "propose": "en-US-AriaNeural",    # Female, confident, expressive
    "oppose":  "en-US-GuyNeural",     # Male, firm, authoritative
    "decide":  "en-GB-RyanNeural",    # Male, neutral British — moderator feel
}


def _clean_text(text: str) -> str:
    """
    Convert Mathematical Alphanumeric Symbols (e.g. italic 𝘔𝘪𝘥-𝘭𝘦𝘷𝘦𝘭) to plain ASCII
    so LiberationSans can render them. Preserves common punctuation that NFKD would drop:
    en-dash (–), em-dash (—), ellipsis (…), curly quotes, etc.
    """
    import unicodedata
    # Replace common punctuation with ASCII equivalents BEFORE NFKD strips them
    replacements = {
        '–': '-',   # en-dash  –  → -
        '—': '--',  # em-dash  —  → --
        '…': '...', # ellipsis …  → ...
        '‘': "'",   # left single quote
        '’': "'",   # right single quote
        '"': '"',   # left double quote
        '"': '"',   # right double quote
        '·': '.',   # middle dot
        '•': '-',   # bullet
    }
    for uni, ascii_equiv in replacements.items():
        text = text.replace(uni, ascii_equiv)
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
    tts_engine:           str   = Field(default="gtts", description="TTS engine: 'gtts', 'edge-tts', or 'piper'")
    tts_voices:           dict  = Field(default_factory=dict, description="Per-section voice overrides for piper engine")


class DebateVideoTool(BaseTool):
    """Creates bottom-to-top streaming debate video — same engine as DefinitionVideoTool."""
    name: str = "Debate Video Tool"
    description: str = (
        "Generates a debate video with bottom-to-top streaming text animation.  "
        "Reads propose.md (PRO), oppose.md (CON), decide.md (Moderator) from output_dir.  "
        "Same rendering engine as Definition Video Tool.  "
        "Triggered by debate_video_enabled=true. "
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
    ) -> str:

        if not debate_video_enabled:
            return "⏭️ Debate video skipped (debate_video_enabled=false)"

        # ── Merge per-run voice overrides into PIPER_VOICES ───────────────
        # tts_voices from debate_config.piper_voices overrides module-level defaults
        import copy
        _voices = copy.deepcopy(PIPER_VOICES)
        if tts_voices and isinstance(tts_voices, dict):
            for role, vcfg in tts_voices.items():
                if role in _voices and isinstance(vcfg, dict):
                    _voices[role].update(vcfg)
                elif isinstance(vcfg, dict):
                    _voices[role] = vcfg
            print(f"[DebateVideo] 🎤 Voice overrides applied: {list(tts_voices.keys())}")

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
        # Pre-tag each section so _parse_lines always has correct context
        raw = "\n\n".join([
            f"PROPOSITION:\n{pro_text}",
            f"OPPOSITION:\n{con_text}",
            f"VERDICT:\n{moderator_text}",
        ])

        results, errors = [], []

        for fmt in video_formats:
            try:
                # ── Smart skip ────────────────────────────────────────────
                silent_video = os.path.join(output_dir, f"debate_video_{fmt}.mp4")
                audio_file   = os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")
                final_merged = os.path.join(output_dir, f"debate_video_{fmt}_with_audio.mp4")

                # Check intro upfront so skip gate can handle prepend
                _intro_candidates = [
                    os.path.join(output_dir, f"intro_{fmt}_with_audio.mp4"),
                    os.path.join(output_dir, f"intro_{fmt}.mp4"),
                ]
                _intro_clip = next((p for p in _intro_candidates if os.path.exists(p)), None)
                _flag_file  = os.path.join(output_dir, f"debate_video_{fmt}_intro_done.flag")
                _intro_done = os.path.exists(_flag_file)

                # Always re-render — delete stale outputs first
                for _stale in [final_merged, silent_video,
                                os.path.join(output_dir, f"debate_video_{fmt}_audio.mp3")]:
                    if os.path.exists(_stale):
                        os.remove(_stale)
                        print(f"[DebateVideo] 🗑️  Removed stale: {os.path.basename(_stale)}")

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
                # Pass raw section texts for piper 3-voice mode
                self._generate_tts(
                    spoken_text, audio_path, video_dur, tts_engine,
                    pro_text=self._section_to_spoken(pro_text,   "propose", channel),
                    con_text=self._section_to_spoken(con_text,   "oppose",  channel),
                    mod_text=self._section_to_spoken(moderator_text,  "decide", channel),
                    voices=_voices,
                )

                # ── Merge audio + video ───────────────────────────────────
                if os.path.exists(audio_path):
                    self._merge_audio_video(out_path, audio_path, final_path, video_dur)

                    # ── Prepend intro if found ────────────────────────────
                    if _intro_clip and os.path.exists(final_path) and not _intro_done:
                        print(f"[DebateVideo] 🎬 Intro found: {os.path.basename(_intro_clip)} — prepending")
                        intro_merged = os.path.join(output_dir, f"debate_video_{fmt}_with_intro.mp4")
                        self._prepend_intro(_intro_clip, final_path, intro_merged)
                        if os.path.exists(intro_merged):
                            os.replace(intro_merged, final_path)
                            open(os.path.join(output_dir, f"debate_video_{fmt}_intro_done.flag"), 'w').close()
                            print(f"[DebateVideo] ✅ Intro prepended → {os.path.basename(final_path)}")
                        else:
                            print(f"[DebateVideo] ⚠️ Intro prepend failed — keeping debate-only video")
                    elif _intro_clip is None:
                        print(f"[DebateVideo]   ℹ️ No intro clip found for {fmt}")

                    merged_kb = os.path.getsize(final_path) // 1024 if os.path.exists(final_path) else 0
                    kb        = os.path.getsize(out_path) // 1024
                    results.append(
                        f"✅ {fmt}: {os.path.basename(final_path)} ({merged_kb} KB)   "
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
        """Convert display (line, section) tuples to spoken narration."""
        parts = []
        for item in lines:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text  = ' '.join(parts)
        text  = _clean_text(text)
        text += f'  Subscribe to {channel} for more insights.'
        return text

    def _section_to_spoken(self, raw_md: str, role: str, channel: str) -> str:
        """
        Convert a single debate section (propose/oppose/decide) markdown
        into clean spoken text suitable for piper TTS.
        role: 'propose' | 'oppose' | 'decide'
        """
        items = self._parse_lines(raw_md)
        parts = []
        for item in items:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text = ' '.join(parts)
        text  = _clean_text(text)
        if role == "decide":
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

    def _generate_tts(self, text: str, audio_path: str, video_dur: float,
                      tts_engine: str = "gtts",
                      pro_text: str = "", con_text: str = "", mod_text: str = "",
                      voices: dict = None):
        """
        Generate TTS audio then stretch to match video_dur exactly.

        tts_engine:
          'gtts'     → single gTTS voice for full text
          'edge-tts' → single edge-tts voice for full text (en-US-AriaNeural)
          'piper'    → 3 separate local ONNX voices:
                         propose → alba_medium   (female, confident)
                         oppose  → scott_medium  (male, firm)
                         decide  → joe_medium    (male, authoritative)
                       Requires: pip install piper-tts
                       Falls back to gtts if piper not available.

        pro_text / con_text / mod_text: section texts for piper 3-voice mode.
        If empty, full `text` is used for all sections.
        """
        engine = tts_engine.strip().lower()
        print(f"[DebateVideo] 🔊 TTS engine: {engine}")
        print(f"[DebateVideo]   PRO text: {len(pro_text)} chars")
        print(f"[DebateVideo]   CON text: {len(con_text)} chars")
        print(f"[DebateVideo]   MOD text: {len(mod_text)} chars")
        print(f"[DebateVideo]   Total text: {len(text)} chars  timeout=60s")

        tmp = audio_path.replace('.mp3', '_raw.mp3')

        try:
            if engine == "piper":
                self._tts_piper_3voice(
                    pro_text or text,
                    con_text or text,
                    mod_text or text,
                    tmp,
                    voices=voices or PIPER_VOICES,
                )
            elif engine == "edge-tts":
                # Use 3 distinct voices if section texts are available
                if pro_text and con_text and mod_text:
                    self._tts_edge_3voice(pro_text, con_text, mod_text, tmp, voices=voices)
                else:
                    self._tts_edge(text, tmp)
            else:
                self._tts_gtts(text, tmp)

            if not os.path.exists(tmp):
                print(f"[DebateVideo] ⚠️ TTS produced no file — skipping audio")
                return

            raw_dur = self._get_duration(tmp)
            print(f"[DebateVideo] 🔊 TTS raw_dur={raw_dur:.1f}s  video_dur={video_dur:.1f}s — no stretch, sync in merge")
            os.rename(tmp, audio_path)

        except Exception as e:
            print(f"[DebateVideo] ⚠️ TTS error: {e}")
            if os.path.exists(tmp):
                os.rename(tmp, audio_path)

    def _tts_piper_3voice(self, pro_text: str, con_text: str, mod_text: str, out_path: str, voices: dict = None):
        """
        Generate 3-voice audio using local piper-tts ONNX models:
          PRO  → alba_medium.onnx      (female, confident)
          CON  → scott_medium.onnx     (male, firm)
          MOD  → joe_medium.onnx       (male, authoritative)
        Concatenates the 3 WAV clips → single MP3 via ffmpeg.
        Falls back to gTTS on any error.
        """
        import tempfile

        # Resolve model paths relative to project root
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        def _abs_model(rel: str) -> str:
            if os.path.isabs(rel):
                return rel
            # Try next to this file first, then project root
            local = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
            if os.path.exists(local):
                return local
            return os.path.join(_project_root, rel)

        _v = voices if voices else PIPER_VOICES
        sections  = [
            ("PRO",  pro_text, _v.get("propose", PIPER_VOICES["propose"])),
            ("CON",  con_text, _v.get("oppose",  PIPER_VOICES["oppose"])),
            ("MOD",  mod_text, _v.get("decide",  PIPER_VOICES["decide"])),
        ]

        try:
            import piper
        except ImportError:
            print("[DebateVideo] ⚠️ piper-tts not installed. Run: pip install piper-tts --break-system-packages")
            print("[DebateVideo]    Falling back to gTTS...")
            full_text = f"{pro_text} {con_text} {mod_text}".strip()
            self._tts_gtts(full_text, out_path)
            return

        wav_clips = []
        tmp_dir   = tempfile.mkdtemp(prefix="debate_piper_")

        try:
            for label, text_chunk, vcfg in sections:
                if not text_chunk.strip():
                    print(f"[DebateVideo]   ⚠️ {label}: empty text — skipping")
                    continue

                model_path = _abs_model(vcfg["model"])
                if not os.path.exists(model_path):
                    print(f"[DebateVideo]   ⚠️ {label}: model not found: {model_path} — skipping")
                    continue

                wav_out = os.path.join(tmp_dir, f"debate_{label.lower()}.wav")
                speed   = vcfg.get("speed", 1.0)

                print(f"[DebateVideo]   🎤 {label}: piper {os.path.basename(model_path)}  "
                      f"speed={speed}  ({len(text_chunk)} chars)")

                # piper CLI: echo "text" | piper --model model.onnx --output_file out.wav
                result = subprocess.run(
                    ["piper",
                     "--model",       model_path,
                     "--output_file", wav_out,
                     "--length_scale", str(round(1.0 / speed, 3))],
                    input=text_chunk.encode("utf-8"),
                    capture_output=True,
                    check=False
                )
                if result.returncode != 0 or not os.path.exists(wav_out):
                    print(f"[DebateVideo]   ⚠️ {label}: piper failed — {result.stderr.decode()[:100]}")
                    continue

                wav_clips.append(wav_out)
                print(f"[DebateVideo]   ✅ {label}: {wav_out}")

            if not wav_clips:
                print("[DebateVideo] ⚠️ No piper clips generated — falling back to gTTS")
                full_text = f"{pro_text} {con_text} {mod_text}".strip()
                self._tts_gtts(full_text, out_path)
                return

            # Concatenate WAV clips → single MP3
            # Write ffmpeg concat list
            concat_list = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list, "w") as _f:
                for clip in wav_clips:
                    _f.write(f"file '{clip}'\n")

            concat_wav = os.path.join(tmp_dir, "debate_combined.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", concat_wav],
                capture_output=True, check=False
            )

            # Convert combined WAV → MP3
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", concat_wav, "-q:a", "2", out_path],
                capture_output=True, check=False
            )
            if result.returncode == 0 and os.path.exists(out_path):
                print(f"[DebateVideo] ✅ piper 3-voice MP3 saved: {out_path}")
            else:
                print(f"[DebateVideo] ⚠️ WAV→MP3 failed — falling back to gTTS")
                full_text = f"{pro_text} {con_text} {mod_text}".strip()
                self._tts_gtts(full_text, out_path)

        finally:
            # Cleanup temp files
            import shutil as _sh
            _sh.rmtree(tmp_dir, ignore_errors=True)

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
            print("[DebateVideo]    Falling back to gTTS...")
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

    def _tts_edge_3voice(self, pro_text: str, con_text: str, mod_text: str,
                         out_path: str, voices: dict = None, timeout: int = 60):
        """
        Generate 3-voice audio using edge-tts neural voices:
          PRO  → en-US-AriaNeural   (female, confident)
          CON  → en-US-GuyNeural    (male, firm)
          MOD  → en-GB-RyanNeural   (male, neutral British moderator)
        Override voices via data.json debate_config.piper_voices (reuses same config key).
        Concatenates 3 MP3 clips → single MP3 via ffmpeg.
        Falls back to single-voice edge-tts on any error.
        """
        import asyncio, tempfile

        # Resolve voice names — tts_voices dict reused for edge-tts too
        _v = voices or {}
        voice_map = {
            "propose": _v.get("propose", {}).get("edge_voice", EDGE_TTS_VOICES["propose"])
                      if isinstance(_v.get("propose"), dict) else EDGE_TTS_VOICES["propose"],
            "oppose":  _v.get("oppose",  {}).get("edge_voice", EDGE_TTS_VOICES["oppose"])
                      if isinstance(_v.get("oppose"), dict) else EDGE_TTS_VOICES["oppose"],
            "decide":  _v.get("decide",  {}).get("edge_voice", EDGE_TTS_VOICES["decide"])
                      if isinstance(_v.get("decide"), dict) else EDGE_TTS_VOICES["decide"],
        }

        try:
            import edge_tts
        except ImportError:
            print("[DebateVideo] ⚠️ edge-tts not installed — falling back to gTTS")
            full = f"{pro_text} {con_text} {mod_text}".strip()
            self._tts_gtts(full, out_path)
            return

        sections = [
            ("PRO", pro_text, voice_map["propose"]),
            ("CON", con_text, voice_map["oppose"]),
            ("MOD", mod_text, voice_map["decide"]),
        ]

        tmp_dir  = tempfile.mkdtemp(prefix="debate_edge_")
        mp3_clips = []

        async def _gen_clip(text: str, voice: str, clip_path: str):
            communicate = edge_tts.Communicate(text, voice=voice)
            await communicate.save(clip_path)

        async def _gen_all():
            for label, text_chunk, voice in sections:
                if not text_chunk.strip():
                    print(f"[DebateVideo]   ⚠️ {label}: empty — skipping")
                    continue
                clip_path = os.path.join(tmp_dir, f"debate_{label.lower()}.mp3")
                print(f"[DebateVideo]   🎤 {label}: {voice}  ({len(text_chunk)} chars)")
                try:
                    await asyncio.wait_for(_gen_clip(text_chunk, voice, clip_path), timeout=timeout)
                    if os.path.exists(clip_path):
                        mp3_clips.append(clip_path)
                        print(f"[DebateVideo]   ✅ {label}: saved {os.path.basename(clip_path)}")
                    else:
                        print(f"[DebateVideo]   ⚠️ {label}: no output file")
                except asyncio.TimeoutError:
                    print(f"[DebateVideo]   ⚠️ {label}: timed out after {timeout}s — skipping clip")
                except Exception as e:
                    print(f"[DebateVideo]   ⚠️ {label}: failed ({e}) — skipping clip")

        try:
            asyncio.run(_gen_all())

            if not mp3_clips:
                print("[DebateVideo] ⚠️ No edge-tts clips — falling back to single-voice")
                full = f"{pro_text} {con_text} {mod_text}".strip()
                self._tts_edge(full, out_path)
                return

            # Concatenate clips → single MP3 via ffmpeg concat demuxer
            concat_list = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list, "w") as _f:
                for clip in mp3_clips:
                    _f.write(f"file '{clip}'\n")

            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", out_path],
                capture_output=True, check=False
            )
            if result.returncode == 0 and os.path.exists(out_path):
                print(f"[DebateVideo] ✅ edge-tts 3-voice MP3 saved: {out_path}")
            else:
                print(f"[DebateVideo] ⚠️ concat failed — falling back to single-voice")
                full = f"{pro_text} {con_text} {mod_text}".strip()
                self._tts_edge(full, out_path)

        finally:
            import shutil as _sh
            _sh.rmtree(tmp_dir, ignore_errors=True)

    def _merge_audio_video(self, video_path: str, audio_path: str,
                            output_path: str, video_dur: float):
        """
        Merge audio into video.
        - If audio is shorter than video: pad with silence so video plays fully.
        - If audio is longer than video: let audio continue (no cut).
        Neither stream is ever trimmed or speed-adjusted.
        """
        print(f"[DebateVideo] 🎬 Merging audio+video → {os.path.basename(output_path)}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-filter_complex", "[1:a]apad[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-shortest",
            output_path
        ], capture_output=True, check=False)
        if result.returncode != 0:
            print(f"[DebateVideo] ⚠️ merge failed: {result.stderr.decode()[:150]}")

    def _prepend_intro(self, intro_path: str, main_path: str, out_path: str):
        """Concatenate intro + debate via ffmpeg filter_complex concat."""
        print(f"[DebateVideo]   intro : {os.path.basename(intro_path)}")
        print(f"[DebateVideo]   debate: {os.path.basename(main_path)}")
        result = subprocess.run(
            ["ffmpeg", "-y",
             "-i", intro_path, "-i", main_path,
             "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[vout][aout]",
             "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-ar", "44100", "-ac", "2",
             "-pix_fmt", "yuv420p", out_path],
            capture_output=True, check=False
        )
        if result.returncode != 0:
            print(f"[DebateVideo] ⚠️ prepend failed: {result.stderr.decode()[:200]}")
     
    def _parse_lines(self, raw: str) -> List[Tuple[str, str]]:
        """
        Parse debate markdown into (line_text, section) tuples.
        section header lines switch context but are NOT rendered.
        Structural sub-headers are skipped ONLY if they're standalone (no content on same line).
        """
        result  = []
        section = 'propose'

        # ── Section headers: NO $ anchor, allow text after colon ─────────────
        _section_map = [
            (re.compile(r'^PROPOSITION\s*[:\-]?', re.I), 'propose'),
            (re.compile(r'^OPPOSITION\s*[:\-]?',     re.I), 'oppose'),
            (re.compile(r'^VERDICT\s*[:\-]?',        re.I), 'decide'),
            (re.compile(r'^MODERATOR\s*[:\-]?',      re.I), 'decide'),
            (re.compile(r'^JUDGE\s*[:\-]?',          re.I), 'decide'),
            (re.compile(r'^DECISION\s*[:\-]?',       re.I), 'decide'),
        ]

        # ── FIXED: Add $ anchor to skip ONLY standalone headers ──────────────
        # Lines with content after colon (e.g., "SUMMARY: text...") are NOT skipped
        _skip = [
            re.compile(r'^SUMMARY\s+OF\s+(PROPOSITION|OPPOSITION|VERDICT)\s*$', re.I),  # ← Added $
            re.compile(r'^SUMMARY\s*[:\-]\s*$',                    re.I),  # ← Added $
            re.compile(r'^(COUNTER[\s\-]?ARGUMENT|COUNTER[\s\-]?POINT)\s*\d*\s*[:\-]?\s*$', re.I),  # ← Added $
            re.compile(r'^(ARGUMENT|POINT)\s+\d+\s*[:\-]\s*$',     re.I),  # ← Added $
            re.compile(r'^(SUPPORTING\s+)?(ARGUMENT|POINT)\s+\d+\s*$', re.I),  # ← Added $
            re.compile(r'^(PRO|CON)\s+ARGUMENT\s+\d+\s*$',         re.I),  # ← Added $
            re.compile(r'^OPENING\s+STATEMENT\s*[:\-]?\s*$',       re.I),  # ← Added $
            re.compile(r'^CLOSING\s+STATEMENT\s*[:\-]?\s*$',       re.I),  # ← Added $
            re.compile(r'^CONCLUSION\s*[:\-]?\s*$',                re.I),  # ← Added $
            re.compile(r'^ANALYSIS\s*[:\-]?\s*$',                  re.I),  # ← Added $
            re.compile(r'^REBUTTAL\s*[:\-]?\d*\s*$',               re.I),  # ← Added $
            re.compile(r'^KEY\s+(POINTS?|ARGUMENTS?)\s*$',         re.I),  # ← Added $
            re.compile(r'^MAIN\s+(POINTS?|ARGUMENTS?)\s*$',        re.I),  # ← Added $
            re.compile(r'^IN\s+CONCLUSION\s*[:\-]?\s*$',           re.I),  # ← Added $
            re.compile(r'^FINAL\s+(VERDICT|DECISION|THOUGHTS?)\s*[:\-]?\s*$', re.I),  # ← Added $
            re.compile(r'^-{3,}$'),
            re.compile(r'^\*{3,}$'),
            re.compile(r'^#{1,6}\s+'),
        ]

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("━") or line.startswith("─") or line.startswith("==="):
                continue
            line = re.sub(
                r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff'
                r'\u2600-\u27ff\u2000-\u206f\ufe00-\ufe0f]+\s*',
                '', line
            ).strip()
            if not line: continue
            line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
            line = re.sub(r'\[.*?\]', '', line).strip()
            if not line: continue
            line = _clean_text(line)
            if not line: continue

            # Check section header FIRST
            matched = next((role for p, role in _section_map if p.match(line)), None)
            if matched:
                section = matched
                print(f"[DebateVideo] 📑 Section switch: {section}")
                continue

            # Then check skip patterns (only standalone headers now)
            if any(p.match(line) for p in _skip):
                print(f"[DebateVideo]   ⏭️  Skipped header: {line[:50]}")
                continue

            line = line[0].upper() + line[1:]
            result.append((line, section))

        print(f"[DebateVideo] 📊 Parsed {len(result)} content lines")
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

    def _draw_diamond_title(self, draw, x, y, text, font, frame: int):
        """
        Diamond light effect for the header title.
        Very slow, smooth prismatic colour shift — no flicker, no blink.
        Cycle: pure white → soft gold → ice blue → soft violet → back to white.
        Full cycle takes ~600 frames (~25s at 24fps) — barely perceptible drift.
        """
        import math

        # Extremely slow cycle — 600 frames = ~25 seconds, barely noticeable
        t = (frame % 600) / 600.0

        # Gentle colour stops — all high-brightness, no jarring saturated jumps
        stops = [
            (0.00, (255, 255, 255)),   # pure white
            (0.25, (255, 240, 180)),   # warm gold-white
            (0.50, (200, 235, 255)),   # ice blue-white
            (0.75, (235, 210, 255)),   # soft lavender-white
            (1.00, (255, 255, 255)),   # back to pure white
        ]

        # Find surrounding stops and interpolate
        c0, c1, f0, f1 = stops[0][1], stops[1][1], 0.0, 0.25
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i+1][0]:
                f0, c0 = stops[i]
                f1, c1 = stops[i+1]
                break
        seg     = (f1 - f0) if f1 != f0 else 1
        local_t = (t - f0) / seg
        # Smooth ease in-out — no abrupt transitions
        local_t = local_t * local_t * (3 - 2 * local_t)
        face_col = tuple(int(c0[i] + (c1[i] - c0[i]) * local_t) for i in range(3))

        # Layer 1 — soft deep shadow (grounded, no harsh edges)
        shadow = (int(face_col[0]*0.08), int(face_col[1]*0.08), int(face_col[2]*0.08))
        for dx, dy in [(-3,3),(3,3),(-3,-3),(3,-3)]:
            draw.text((x+dx, y+dy), text, font=font, fill=shadow)

        # Layer 2 — gentle colour bloom (constant, no pulse)
        bloom = (int(face_col[0]*0.35), int(face_col[1]*0.35), int(face_col[2]*0.35))
        for dx, dy in [(-2,2),(2,2),(-2,-2),(2,-2),(2,0),(-2,0),(0,2),(0,-2)]:
            draw.text((x+dx, y+dy), text, font=font, fill=bloom)

        # Layer 3 — inner soft glow (constant brightness)
        inner = (int(face_col[0]*0.65), int(face_col[1]*0.65), int(face_col[2]*0.65))
        for dx, dy in [(-1,1),(1,1),(-1,-1),(1,-1),(1,0),(-1,0),(0,1),(0,-1)]:
            draw.text((x+dx, y+dy), text, font=font, fill=inner)

        # Layer 4 — crisp face at full colour (no flicker multiplier)
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
        header_h      = int(h * 0.17)  # title + section badge + separator
        pad_top       = header_h + int(h * 0.02)
        wm_zone       = int(h * 0.88)
        body_h        = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y      = pad_top + body_h // 2 - active_font_h // 2
        max_px        = w - pad_x - int(w * 0.05)

        hdr_title  = _clean_text(topic) if topic else _clean_text(channel)
        # Capitalize each word, but preserve known acronyms
        _acronyms  = {'ai', 'ml', 'api', 'ui', 'ux', 'llm', 'gpt', 'ceo', 'cto', 'it'}
        hdr_title  = ' '.join(
            _word.upper() if _word.lower() in _acronyms else _word.capitalize()
            for _word in hdr_title.split()
        )
        hdr_max_px = w - pad_x * 2

        # Auto-shrink header font until every word fits within hdr_max_px (no word clipping)
        hdr_topic_size = max(w // 30, 22)
        f_hdr_topic    = None
        for size in range(hdr_topic_size, 18, -2):
            try:
                _f = ImageFont.truetype(FONT_BOLD, size)
            except Exception:
                _f = ImageFont.load_default()
            hdr_lines = self._pixel_wrap(hdr_title, _f, hdr_max_px)
            # Check no single wrapped line overflows
            from PIL import Image as _TmpImg, ImageDraw as _TmpDraw
            _tmp = _TmpImg.new("RGB", (1, 1))
            _d   = _TmpDraw.Draw(_tmp)
            max_line_w = max(
                (_d.textbbox((0,0), ln, font=_f)[2] - _d.textbbox((0,0), ln, font=_f)[0])
                for ln in hdr_lines
            )
            if max_line_w <= hdr_max_px:
                hdr_topic_size = size
                f_hdr_topic    = _f
                break
        if f_hdr_topic is None:
            try:
                f_hdr_topic = ImageFont.truetype(FONT_BOLD, 18)
            except Exception:
                f_hdr_topic = ImageFont.load_default()
            hdr_lines = self._pixel_wrap(hdr_title, f_hdr_topic, hdr_max_px)

        print(f"[DebateVideo]   Header font: {hdr_topic_size}pt  lines: {len(hdr_lines)}")

        lines_data: List[Tuple[str, str]] = []
        for item in raw_lines:
            raw_text, sec = item if isinstance(item, tuple) else (item, 'propose')
            for wrapped in self._pixel_wrap(raw_text, f_active, max_px):
                lines_data.append((wrapped, sec))

        total_frames = len(lines_data) * frames_per_line
        print(f"[DebateVideo]   Wrapped lines: {len(lines_data)}    "
              f"Total frames: {total_frames}    "
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
                    "{desc}: {percentage:3.0f}%|{bar:35}|   "
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

        _section_labels = {'propose': 'Proposition', 'oppose': 'Opposition', 'decide': 'Verdict'}
        _section_colors = {'propose': (130, 210, 255), 'oppose': (255, 100, 100), 'decide': (140, 255, 140)}
        _prev_section   = None

        global_frame = 0
        for line_idx, (ltext, cur_section) in enumerate(lines_data):
            for fi in range(frames_per_line):
                alpha = min(1.0, fi / max(fade_frames, 1))
                img   = Image.new("RGB", (w, h), (0, 0, 0))
                draw  = ImageDraw.Draw(img)

                # Header — multi-line centered with diamond prismatic light effect
                hdr_line_h = int(hdr_topic_size * 1.35)
                hdr_y      = int(h * 0.018)
                for hdr_ln in hdr_lines:
                    hdr_bbox = draw.textbbox((0, 0), hdr_ln, font=f_hdr_topic)
                    hdr_w    = hdr_bbox[2] - hdr_bbox[0]
                    hdr_x    = (w - hdr_w) // 2
                    self._draw_diamond_title(draw, hdr_x, hdr_y, hdr_ln, f_hdr_topic, global_frame)
                    hdr_y   += hdr_line_h

                # Separator — sits below however many header lines were drawn
                # Section pill badge — centered, just below title
                _sec_label = _section_labels.get(cur_section, cur_section.capitalize())
                _sec_color = _section_colors.get(cur_section, (220, 220, 220))
                _sec_size  = max(w // 44, 22)
                try:    _f_sec = ImageFont.truetype(FONT_BOLD, _sec_size)
                except: _f_sec = ImageFont.load_default()
                _sec_gap  = int(h * 0.005)
                _sec_y    = hdr_y + _sec_gap
                _sec_bbox = draw.textbbox((0, 0), _sec_label, font=_f_sec)
                _sec_w    = _sec_bbox[2] - _sec_bbox[0]
                _sec_h    = _sec_bbox[3] - _sec_bbox[1]
                _sec_x    = (w - _sec_w) // 2
                _sec_alpha = min(1.0, fi / max(fade_frames, 1)) if cur_section != _prev_section else 1.0
                _pad_x2, _pad_y2 = int(w * 0.018), int(h * 0.004)
                _bg      = tuple(int(ch * 0.28 * _sec_alpha) for ch in _sec_color)
                _border  = tuple(int(ch * _sec_alpha) for ch in _sec_color)
                draw.rectangle(
                    [_sec_x - _pad_x2, _sec_y - _pad_y2, _sec_x + _sec_w + _pad_x2, _sec_y + _sec_h + _pad_y2],
                    fill=_bg, outline=_border, width=2
                )
                _ca = (int(255 * _sec_alpha),) * 3
                for _dx, _dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                    draw.text((_sec_x+_dx, _sec_y+_dy), _sec_label, font=_f_sec,
                              fill=tuple(int(ch * 0.5 * _sec_alpha) for ch in _sec_color))
                draw.text((_sec_x, _sec_y), _sec_label, font=_f_sec, fill=_ca)
                _prev_section = cur_section
                _ul_y = _sec_y + _sec_h + _pad_y2 + 2

                sep_y = max(header_h - 2, _ul_y + int(h * 0.008))
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
                    self._justify(draw, pad_x, y_pos, lines_data[pi][0], fnt, max_px, c)
                    y_cursor = y_pos

                # Active line — neon white glow
                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)

                # Future lines (dim, below active)
                future_start = active_y + active_font_h + int(h * 0.025)
                y_cursor     = future_start
                for ahead, fi2 in enumerate(range(line_idx + 1, min(line_idx + 20, len(lines_data))), start=1):
                    fnt    = get_font(ahead)
                    fsize  = max(MIN_SIZE, BASE_ACTIVE - ahead * SHRINK_STEP)
                    line_h = int(fsize * 1.7)
                    if y_cursor + line_h > wm_zone:
                        break
                    brightness = max(18, 110 - ahead * 18)
                    c = (brightness, brightness, brightness)
                    self._justify(draw, pad_x, y_cursor, lines_data[fi2][0], fnt, max_px, c)
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
