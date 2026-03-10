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
    "propose": {
        "model":    "models/alba_medium.onnx",
        "speed":  1.05,
    },
    "oppose": {
        "model":    "models/en_GB-scott-medium.onnx",
        "speed":  1.0,
    },
    "decide": {
        "model":    "models/joe_medium.onnx",
        "speed":  0.95,
    },
}

DEFAULT_EDGE_TTS_VOICES = {
    "propose": "en-US-AriaNeural",
    "oppose":  "en-US-GuyNeural",
    "decide":  "en-GB-RyanNeural",
}

def _clean_text(text: str) -> str:
    """
    Convert Mathematical Alphanumeric Symbols (e.g. italic 𝘔𝘪𝘥-𝘭𝘦𝘷𝘦𝘭) to plain ASCII
    so LiberationSans can render them. Preserves common punctuation that NFKD would drop.
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
    lang_suffix:          str   = Field(default="En", description="Language suffix for output filenames. e.g. 'En', 'Bn', 'Fr'")
    bg_opacity:           int   = Field(default=255, description="Background opacity: 0=fully transparent, 255=pure black. e.g. 180=semi-transparent dark")

class DebateVideoTool(BaseTool):
    """
    Creates bottom-to-top streaming debate video.
    ALL CONFIG FROM data.json — NO HARDCODED VALUES.
    Reads propose.md (PRO), oppose.md (CON), decide.md (Moderator) from output_dir.
    Output: debate_video_[format]_with_audio.mp4 (intermediate file for merge tool)
    Triggered by debate_video_enabled=true.
    NO MERGE HERE — debate_merge_tool.py handles intro + debate concatenation.
    """
    name: str = "Debate Video Tool"
    description: str = (
        "Generates a debate video with bottom-to-top streaming text animation.  "
        "Reads propose.md (PRO), oppose.md (CON), decide.md (Moderator) from output_dir.  "
        "ALL CONFIG FROM data.json — tts_voices defines piper/edge-tts voices.  "
        "Output: debate_video_[format]_with_audio.mp4 (intermediate for merge tool).  "
        "Triggered by debate_video_enabled=true.  "
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
            print(f"[DebateVideo] 🎤 Using default voice config (data.json provided none)")

        for role, vcfg in _voices.items():
            if isinstance(vcfg, dict):
                print(f"[DebateVideo]   {role}: {vcfg.get('model', vcfg.get('edge_voice', 'N/A'))}")
            else:
                print(f"[DebateVideo]   {role}: {vcfg}")

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "❌ Pillow not installed. Run: pip install Pillow --break-system-packages"

        if not shutil.which('ffmpeg'):
            return "❌ ffmpeg not found. Run: sudo apt install ffmpeg"

        # ── Resolve output directory ────────────────────────────────────────
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # ── Load debate content (lang-suffixed md files) ─────────────────────
        _lang = lang_suffix if lang_suffix else "En"
        propose_file = os.path.join(output_dir, f"propose_{_lang}.md")
        oppose_file  = os.path.join(output_dir, f"oppose_{_lang}.md")
        decide_file  = os.path.join(output_dir, f"decide_{_lang}.md")

        # Fallback to plain .md if lang-suffixed not found (backward compat)
        for label, path, fallback in [
            (f"propose_{_lang}.md", propose_file, os.path.join(output_dir, "propose.md")),
            (f"oppose_{_lang}.md",  oppose_file,  os.path.join(output_dir, "oppose.md")),
            (f"decide_{_lang}.md",  decide_file,  os.path.join(output_dir, "decide.md")),
        ]:
            if not os.path.exists(path):
                if os.path.exists(fallback):
                    print(f"[DebateVideo] ⚠️  {label} not found — using fallback {os.path.basename(fallback)}")
                    if 'propose' in label: propose_file = fallback
                    elif 'oppose' in label: oppose_file = fallback
                    else: decide_file = fallback
                else:
                    return f"❌ {label} not found in {output_dir}"

        with open(propose_file, 'r', encoding='utf-8') as f:
            pro_text = f.read().strip()
        with open(oppose_file, 'r', encoding='utf-8') as f:
            con_text = f.read().strip()
        with open(decide_file, 'r', encoding='utf-8') as f:
            moderator_text = f.read().strip()

        # ── Combine into single narrative ─────────────────────────────────
        raw = "\n\n".join([
            f"PROPOSITION:\n{pro_text}",
            f"OPPOSITION:\n{con_text}",
            f"VERDICT:\n{moderator_text}",
        ])

        results, errors = [], []

        for fmt in video_formats:
            try:
                # ── File paths (intermediate — merge tool handles final naming) ──
                _lang = lang_suffix if lang_suffix else "En"
                silent_video = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}.mp4")
                audio_file   = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_audio.mp3")
                final_merged = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_with_audio.mp4")
                cc_path      = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_cc.txt")

                # ✅ SMART SKIP: Check if debate video with audio already exists
                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped ({os.path.basename(final_merged)} exists)")
                    print(f"[DebateVideo] ⏭️ {fmt}: Debate video exists — skipping")
                    continue

                # Always re-render intermediate files
                for _stale in [final_merged, silent_video, audio_file]:
                    if os.path.exists(_stale):
                        os.remove(_stale)
                        print(f"[DebateVideo] 🗑️  Removed stale: {os.path.basename(_stale)}")

                # ── Parse lines ─────────────────────────────────────────────
                # HD/4K/landscape formats → full content, no filtering
                # Shorts/portrait formats → short-form (ARG 1 + COUNTER-ARG 1 + DECISION only)
                _is_short_form = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                raw_lines = self._parse_lines(raw, short_form=_is_short_form)

                # Append disclaimer + subscribe line to video lines so audio & video end together
                _disclaimer_text = _clean_text('This video is created for educational and research purposes, shared to spread knowledge and awareness.')
                _subscribe_text  = _clean_text(f'Subscribe to {channel} for more insights.')
                raw_lines.append((_disclaimer_text, 'decide'))
                raw_lines.append((_subscribe_text, 'decide'))

                spoken_text = self._lines_to_spoken(raw_lines, topic, channel)

                print(f"[DebateVideo] [{fmt}] Parsed {len(raw_lines)} lines   "
                      f"({'short-form: opening+ARG1/COUNTER-ARG1, DECISION-only verdict' if _is_short_form else 'full content'})")

                # ── Save narration text ───────────────────────────────────
                with open(cc_path, 'w', encoding='utf-8') as _f:
                    _f.write(spoken_text)
                print(f"[DebateVideo] 📝 Narration saved: {cc_path} ({len(spoken_text)} chars)")

                # ── Render silent video ───────────────────────────────────
                out_path    = silent_video
                is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                w, h        = (1080, 1920) if is_portrait else (1920, 1080)
                print(f"\n[DebateVideo] [{fmt}] {w}x{h}  secs_per_line={secs_per_line}")

                _bg_color = tuple(int(x) for x in str(bg_opacity).split(", "))[:3] if ", " in str(bg_opacity) else (0, 0, 0)
                self._render(raw_lines, out_path, w, h, secs_per_line,
                             channel, watermark_enabled, watermark_text,
                             video_fps, topic=topic, bg_opacity=bg_opacity, bg_color=_bg_color)

                if not os.path.exists(out_path):
                    errors.append(f"❌ {fmt}: video missing after render")
                    continue

                # ── TTS audio ─────────────────────────────────────────────
                audio_path = os.path.join(output_dir, f"debate_video_{fmt}_{_lang}_audio.mp3")
                video_dur  = self._get_duration(out_path)

                # Build per-section spoken text
                _pro_spoken = self._section_to_spoken(pro_text,       "propose", channel, short_form=_is_short_form)
                _con_spoken = self._section_to_spoken(con_text,       "oppose",  channel, short_form=_is_short_form)
                _mod_spoken = self._section_to_spoken(moderator_text, "decide",  channel, short_form=_is_short_form)

                # spoken_text_no_sub = pro + con + mod only
                _spoken_no_sub = f"{_pro_spoken} {_con_spoken} {_mod_spoken}".strip()

                # Separate gTTS clips for disclaimer and subscribe (independent — if one fails the other still plays)
                _disclaimer_spoken = _clean_text(
                    'This video is created for educational and research purposes, '
                    'shared to spread knowledge and awareness.'
                )
                _subscribe_spoken = _clean_text(f'Subscribe to {channel} for more insights.')

                _pre_sub_audio    = audio_path.replace('.mp3', '_presub.mp3')
                _disclaimer_audio = audio_path.replace('.mp3', '_disclaimer.mp3')
                _subscribe_audio  = audio_path.replace('.mp3', '_subscribe.mp3')

                # 1. Generate main debate audio (PRO + CON + MOD, engine-specific voices)
                self._generate_tts(
                    _spoken_no_sub, _pre_sub_audio,
                    max(1.0, video_dur - secs_per_line * 2 - 1.0),
                    tts_engine,
                    pro_text=_pro_spoken,
                    con_text=_con_spoken,
                    mod_text=_mod_spoken,
                    voices=_voices,
                )

                # 2. Generate disclaimer clip via gTTS (independent temp file)
                self._tts_gtts(_disclaimer_spoken, _disclaimer_audio)
                print(f"[DebateVideo] 🎤 Disclaimer: {'✅' if os.path.exists(_disclaimer_audio) else '⚠️ failed'}")

                # 3. Generate subscribe clip via gTTS (independent temp file)
                self._tts_gtts(_subscribe_spoken, _subscribe_audio)
                print(f"[DebateVideo] 🎤 Subscribe: {'✅' if os.path.exists(_subscribe_audio) else '⚠️ failed'}")

                # 4. Concat: main + disclaimer + subscribe → final audio_path
                _clips = [_pre_sub_audio, _disclaimer_audio, _subscribe_audio]
                _clips_exist = [c for c in _clips if os.path.exists(c)]

                if len(_clips_exist) >= 1:
                    if len(_clips_exist) == 1:
                        # Only main audio — just rename
                        os.replace(_clips_exist[0], audio_path)
                        print(f"[DebateVideo] 🎤 Only main audio available — no disclaimer/subscribe appended")
                    else:
                        # Build ffmpeg inputs + filter_complex for N clips
                        _inputs = []
                        for c in _clips_exist:
                            _inputs += ["-i", c]
                        n = len(_clips_exist)
                        _resample = " ".join(f"[{i}:a]aresample=44100[a{i}];" for i in range(n))
                        _concat_in = " ".join(f"[a{i}]" for i in range(n))
                        _filter = f"{_resample}{_concat_in}concat=n={n}:v=0:a=1[aout]"
                        _r = subprocess.run(
                            ["ffmpeg", "-y"] + _inputs +
                            ["-filter_complex", _filter,
                             "-map", "[aout]", "-q:a", "2", audio_path],
                            capture_output=True, check=False
                        )
                        if _r.returncode == 0 and os.path.exists(audio_path):
                            print(f"[DebateVideo] 🎤 Final audio assembled ({len(_clips_exist)} clips) ✅")
                        else:
                            print(f"[DebateVideo] ⚠️ Concat failed: {_r.stderr.decode()[:120]}")
                            os.replace(_pre_sub_audio, audio_path)
                    # Cleanup temp clips
                    for _tmp in [_pre_sub_audio, _disclaimer_audio, _subscribe_audio]:
                        if os.path.exists(_tmp):
                            os.remove(_tmp)

                # ── Merge audio + video ───────────────────────────────────
                if os.path.exists(audio_path):
                    _audio_dur = self._get_duration(audio_path)
                    print(f"[DebateVideo] 🔊 audio={_audio_dur:.1f}s  video={video_dur:.1f}s   "
                          f"delta={_audio_dur - video_dur:+.1f}s")
                    self._merge_audio_video(out_path, audio_path, final_merged, max(video_dur, _audio_dur))

                    merged_kb = os.path.getsize(final_merged) // 1024
                    results.append(
                        f"✅ {fmt}: {os.path.basename(final_merged)} ({merged_kb} KB)    "
                        f"Duration: {max(video_dur, _audio_dur):.1f}s"
                    )
                    print(f"[DebateVideo] ✅ {fmt}: {os.path.basename(final_merged)} ({merged_kb} KB)")
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


# ── Helpers ───────────────────────────────────────────────────────────

    def _lines_to_spoken(self, lines: list, topic: str, channel: str) -> str:
        """Convert display (line, section) tuples to spoken narration.
        Subscribe line is already appended to raw_lines before this is called.
        """
        parts = []
        for item in lines:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text = ' '.join(parts)
        text = _clean_text(text)
        return text

    def _section_to_spoken(self, raw_md: str, role: str, channel: str,
                           short_form: bool = True) -> str:
        """Convert a single debate section to clean spoken text.
        short_form=True  → Shorts filtering (ARG 1 / COUNTER-ARG 1 / post-DECISION only)
        short_form=False → HD full content, no restrictions
        """
        items = self._parse_lines(raw_md, default_section=role, short_form=short_form)
        parts = []
        for item in items:
            parts.append(item[0] if isinstance(item, tuple) else item)
        text = ' '.join(parts)
        text = _clean_text(text)
        # Subscribe is appended as the last raw_line — spoken via the main spoken_text
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
        Generate TTS audio — ALL VOICE CONFIG FROM data.json.

        tts_engine: 'gtts' | 'edge-tts' | 'piper'
        voices: from data.json debate_config.piper_voices (flattened to tts_voices by main.py)
        """
        engine = tts_engine.strip().lower()
        print(f"[DebateVideo] 🔊 TTS engine: {engine}")
        print(f"[DebateVideo]   PRO text: {len(pro_text)} chars")
        print(f"[DebateVideo]   CON text: {len(con_text)} chars")
        print(f"[DebateVideo]   MOD text: {len(mod_text)} chars")
        print(f"[DebateVideo]   Total text: {len(text)} chars  timeout=60s")

        _voices = voices if voices else DEFAULT_PIPER_VOICES
        tmp = audio_path.replace('.mp3', '_raw.mp3')

        try:
            if engine == "piper":
                self._tts_piper_3voice(
                    pro_text or text,
                    con_text or text,
                    mod_text or text,
                    tmp,
                    voices=_voices,
                )
            elif engine == "edge-tts":
                if pro_text and con_text and mod_text:
                    self._tts_edge_3voice(pro_text, con_text, mod_text, tmp, voices=_voices)
                else:
                    _fallback_voice = DEFAULT_EDGE_TTS_VOICES.get("propose", "en-US-AriaNeural")
                    if isinstance(_voices.get("propose"), dict):
                        _fallback_voice = _voices["propose"].get("edge_voice", _fallback_voice)
                    self._tts_edge(text, tmp, voice=_fallback_voice)
            else:
                self._tts_gtts(text, tmp)

            if not os.path.exists(tmp):
                print(f"[DebateVideo] ⚠️ TTS produced no file — skipping audio")
                return

            raw_dur = self._get_duration(tmp)
            print(f"[DebateVideo] 🔊 TTS raw_dur={raw_dur:.1f}s  video_dur={video_dur:.1f}s")

            # ── atempo sync: stretch/compress audio to exactly match video ──
            # Keeps voice pitch natural while eliminating silence gaps.
            # atempo range: 0.5–2.0 per filter; chain two filters for extreme ratios.
            if video_dur > 0 and raw_dur > 0:
                ratio = raw_dur / video_dur
                ratio = max(0.25, min(4.0, ratio))   # safety clamp
                print(f"[DebateVideo] 🔊 atempo ratio={ratio:.4f}   "
                      f"({'speeding up' if ratio > 1 else 'slowing down'} audio to match video)")

                # Build atempo filter chain (each filter handles 0.5–2.0)
                if ratio <= 2.0 and ratio >= 0.5:
                    atempo_filter = f"atempo={ratio:.6f}"
                elif ratio > 2.0:
                    # e.g. ratio=3.0 → atempo=1.732,atempo=1.732
                    import math
                    r1 = math.sqrt(ratio)
                    atempo_filter = f"atempo={r1:.6f},atempo={r1:.6f}"
                else:
                    # ratio < 0.5 → atempo=0.707,atempo=0.707
                    import math
                    r1 = math.sqrt(ratio)
                    atempo_filter = f"atempo={r1:.6f},atempo={r1:.6f}"

                synced = audio_path.replace('.mp3', '_synced.mp3')
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp,
                     "-filter:a", atempo_filter,
                     "-q:a", "2", synced],
                    capture_output=True, check=False
                )
                if r.returncode == 0 and os.path.exists(synced):
                    synced_dur = self._get_duration(synced)
                    print(f"[DebateVideo] ✅ atempo synced: {synced_dur:.1f}s  "
                          f"(target={video_dur:.1f}s  delta={synced_dur-video_dur:+.2f}s)")
                    os.replace(synced, audio_path)
                    if os.path.exists(tmp):
                        os.remove(tmp)
                else:
                    print(f"[DebateVideo] ⚠️ atempo failed — using raw audio")
                    os.rename(tmp, audio_path)
            else:
                os.rename(tmp, audio_path)

        except Exception as e:
            print(f"[DebateVideo] ⚠️ TTS error: {e}")
            if os.path.exists(tmp):
                os.rename(tmp, audio_path)

    def _tts_piper_3voice(self, pro_text: str, con_text: str, mod_text: str, out_path: str, voices: dict = None):
        """Generate 3-voice audio using piper-tts ONNX models — ALL CONFIG FROM data.json."""
        import tempfile

        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_tool_dir)))

        def _abs_model(rel: str) -> str:
            if os.path.isabs(rel):
                return rel
            local = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
            if os.path.exists(local):
                return local
            return os.path.join(_project_root, rel)

        _v = voices if voices else DEFAULT_PIPER_VOICES
        sections = [
            ("PRO",  pro_text, _v.get("propose", DEFAULT_PIPER_VOICES["propose"])),
            ("CON",  con_text, _v.get("oppose",  DEFAULT_PIPER_VOICES["oppose"])),
            ("MOD",  mod_text, _v.get("decide",  DEFAULT_PIPER_VOICES["decide"])),
        ]

        try:
            import piper
        except ImportError:
            print("[DebateVideo] ⚠️ piper-tts not installed. Run: pip install piper-tts")
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

                model_path = _abs_model(vcfg.get("model", ""))
                if not model_path or not os.path.exists(model_path):
                    print(f"[DebateVideo]   ⚠️ {label}: model not found: {model_path} — skipping")
                    continue

                wav_out = os.path.join(tmp_dir, f"debate_{label.lower()}.wav")
                speed   = vcfg.get("speed", 1.0)

                print(f"[DebateVideo]   🎤 {label}: piper {os.path.basename(model_path)}   "
                      f"speed={speed}  ({len(text_chunk)} chars)")

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
            import shutil as _sh
            _sh.rmtree(tmp_dir, ignore_errors=True)

    def _tts_gtts(self, text: str, out_path: str):
        """Generate audio using gTTS. Saves to temp file first, then renames atomically."""
        import tempfile, os
        try:
            from gtts import gTTS
        except ImportError:
            print("[DebateVideo] ⚠️ gTTS not installed. Run: pip install gTTS")
            return
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.mp3')
        os.close(tmp_fd)
        try:
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(tmp_path)
            size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if size < 1000:
                raise RuntimeError(f"gTTS output too small ({size} bytes) — likely empty/corrupt")
            os.replace(tmp_path, out_path)
            print(f"[DebateVideo] ✅ gTTS saved: {out_path} ({size//1024}KB)")
        except Exception as e:
            print(f"[DebateVideo] ⚠️ gTTS failed: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            # Remove corrupt output if it exists
            if os.path.exists(out_path):
                os.remove(out_path)

    def _tts_edge(self, text: str, out_path: str, voice: str = "en-US-AriaNeural", timeout: int = 60):
        """Generate audio using edge-tts with timeout."""
        try:
            import edge_tts
            import asyncio
        except ImportError:
            print("[DebateVideo] ⚠️ edge-tts not installed. Run: pip install edge-tts")
            print("[DebateVideo]    Falling back to gTTS...")
            self._tts_gtts(text, out_path)
            return

        async def _generate():
            communicate = edge_tts.Communicate(text, voice=voice)
            await communicate.save(out_path)

        async def _with_timeout():
            await asyncio.wait_for(_generate(), timeout=timeout)

        try:
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
        """Generate 3-voice audio using edge-tts neural voices — ALL CONFIG FROM data.json."""
        import asyncio, tempfile

        _v = voices if voices else DEFAULT_EDGE_TTS_VOICES

        def _get_voice(role: str) -> str:
            vcfg = _v.get(role, {})
            if isinstance(vcfg, dict):
                return vcfg.get("edge_voice", DEFAULT_EDGE_TTS_VOICES.get(role, "en-US-AriaNeural"))
            return str(vcfg) if vcfg else DEFAULT_EDGE_TTS_VOICES.get(role, "en-US-AriaNeural")

        voice_map = {
            "propose": _get_voice("propose"),
            "oppose":  _get_voice("oppose"),
            "decide":  _get_voice("decide"),
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
                            output_path: str, target_duration: float):
        """Merge audio into video, ensuring both are exactly target_duration.
        Uses target_duration (max of video_dur and audio_dur) so subscribe line is never cut.
        apad ensures silence fills any gap if audio finishes before video ends.
        """
        print(f"[DebateVideo] 🎬 Merging audio+video → {os.path.basename(output_path)}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            # Pad audio with silence then trim/extend to exact target duration
            "-filter_complex", f"[1:a]apad=whole_dur={target_duration:.3f}[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-t", str(round(target_duration, 3)),
            output_path
        ], capture_output=True, check=False)
        if result.returncode != 0:
            print(f"[DebateVideo] ⚠️ merge failed: {result.stderr.decode()[:200]}")

    def _parse_lines(self, raw: str, default_section: str = 'propose', short_form: bool = True) -> List[Tuple[str, str]]:
        """
        Parse debate markdown into (line_text, section) tuples.

        short_form=True  (Shorts/portrait) → PROPOSITION and OPPOSITION show
                                              OPENING STATEMENT + ARG 1 / COUNTER-ARG 1
                                              only. Stops permanently at ARG 2+.
                                              VERDICT: starts from DECISION: header only.
        short_form=False (HD/landscape)    → full content, no restrictions
        """
        result  = []
        section = default_section

        # Section-switch markers — DECISION handled separately so its content isn't lost
        _section_map = [
            (re.compile(r'^PROPOSITION\s*[:\-]?', re.I), 'propose'),
            (re.compile(r'^OPPOSITION\s*[:\-]?',  re.I), 'oppose'),
            (re.compile(r'^VERDICT\s*[:\-]?',     re.I), 'decide'),
            (re.compile(r'^MODERATOR\s*[:\-]?',   re.I), 'decide'),
            (re.compile(r'^JUDGE\s*[:\-]?',       re.I), 'decide'),
        ]

        # Numbered argument headers — we extract the digit
        _arg_re         = re.compile(r'^ARGUMENT\s+(\d+)\s*[:\-]', re.I)
        _counter_arg_re = re.compile(r'^COUNTER[\s\-]?ARGUMENT\s+(\d+)\s*[:\-]', re.I)
        _decision_re    = re.compile(r'^DECISION\s*[:\-]?', re.I)

        # Headers that close the currently-open includable block
        _block_end_headers = [
            re.compile(r'^OPENING\s+STATEMENT\s*[:\-]?',  re.I),
            re.compile(r'^CLOSING\s+STATEMENT\s*[:\-]?',  re.I),
            re.compile(r'^CONCLUSION\s*[:\-]?',            re.I),
            re.compile(r'^SUMMARY\s+OF\s+\w+',             re.I),
            re.compile(r'^SUMMARY\s*[:\-]?\s*$',          re.I),
            re.compile(r'^ANALYSIS\s*[:\-]?',             re.I),
            re.compile(r'^IN\s+CONCLUSION\s*[:\-]?\s*$',  re.I),
            re.compile(r'^FINAL\s+(VERDICT|DECISION|THOUGHTS?)\s*[:\-]?\s*$', re.I),
        ]

        # Pure structural lines always dropped
        _skip = [
            re.compile(r'^-{3,}$'),
            re.compile(r'^\*{3,}$'),
            re.compile(r'^#{1,6}\s+'),
            re.compile(r'^KEY\s+(POINTS?|ARGUMENTS?)\s*$',  re.I),
            re.compile(r'^MAIN\s+(POINTS?|ARGUMENTS?)\s*$', re.I),
            re.compile(r'^REBUTTAL\s*[:\-]?\d*\s*$',        re.I),
        ]

        # ── HD / full-content mode: no filtering ──────────────────────────
        if not short_form:
            for raw_line in raw.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("━") or line.startswith("─") or line.startswith("=== "):
                    continue
                line = re.sub(
                    r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff'
                    r'\u2600-\u27ff\u2000-\u206f\ufe00-\ufe0f]+\s*',
                    '', line
                ).strip()
                if not line: continue
                line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                line = re.sub(r'\[.*?\]',  '', line).strip()
                if not line: continue
                line = _clean_text(line)
                if not line: continue
                # detect section changes (section headers are skipped from output)
                matched_section = next((role for p, role in [
                    (re.compile(r'^PROPOSITION\s*[:\-]?', re.I), 'propose'),
                    (re.compile(r'^OPPOSITION\s*[:\-]?',  re.I), 'oppose'),
                    (re.compile(r'^VERDICT\s*[:\-]?',     re.I), 'decide'),
                    (re.compile(r'^MODERATOR\s*[:\-]?',   re.I), 'decide'),
                    (re.compile(r'^JUDGE\s*[:\-]?',       re.I), 'decide'),
                ] if p.match(line)), None)
                if matched_section:
                    section = matched_section
                    print(f"[DebateVideo] 📑 Section: {section}")
                    continue
                # drop pure structural markers
                _hdr_skip = [
                    re.compile(r'^-{3,}$'), re.compile(r'^\*{3,}$'), re.compile(r'^#{1,6}\s+'),
                    re.compile(r'^(ARGUMENT|POINT)\s+\d+\s*[:\-]\s*$', re.I),
                    re.compile(r'^COUNTER[\s\-]?ARGUMENT\s+\d+\s*[:\-]\s*$', re.I),
                    re.compile(r'^OPENING\s+STATEMENT\s*[:\-]?\s*$',  re.I),
                    re.compile(r'^CLOSING\s+STATEMENT\s*[:\-]?\s*$',  re.I),
                    re.compile(r'^CONCLUSION\s*[:\-]?\s*$',            re.I),
                    re.compile(r'^SUMMARY\s+OF\s+\w+',                 re.I),
                    re.compile(r'^SUMMARY\s*[:\-]?\s*$',               re.I),
                    re.compile(r'^ANALYSIS\s*[:\-]?\s*$',              re.I),
                ]
                if any(p.match(line) for p in _hdr_skip):
                    continue
                line = line[0].upper() + line[1:]
                result.append((line, section))
            print(f"[DebateVideo] 📊 Parsed {len(result)} content lines (full)")
            return result

        # ── Short-form state ───────────────────────────────────────────────
        # propose / oppose : include OPENING STATEMENT + ARGUMENT 1 /
        #   COUNTER-ARGUMENT 1 body only. Gate closes permanently at ARG 2+.
        # decide            : starts False; opens only after DECISION: header.
        include_content         = (default_section in ('propose', 'oppose'))
        decide_decision_reached = False

        _opening_re = re.compile(r'^OPENING\s+STATEMENT\s*[:\-]?', re.I)
        _closing_re = re.compile(
            r'^(CLOSING\s+STATEMENT|CONCLUSION|IN\s+CONCLUSION'
            r'|FINAL\s+(VERDICT|DECISION|THOUGHTS?))\s*[:\-]?', re.I)

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("\u254b") or line.startswith("\u2500") or line.startswith("=== "):
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

            # ── Section switch ──────────────────────────────────────────────
            matched_section = next((role for p, role in _section_map if p.match(line)), None)
            if matched_section:
                if matched_section != section:
                    section                 = matched_section
                    # Re-open gate for new propose/oppose section; close for decide
                    include_content         = (section in ('propose', 'oppose'))
                    decide_decision_reached = False
                    print(f"[DebateVideo] 📄 Section switch: {section}")
                continue  # never render a section-header line

            # ── DECISION header (decide section) ───────────────────────────
            if _decision_re.match(line):
                if section == 'decide':
                    decide_decision_reached = True
                    include_content         = True
                    print(f"[DebateVideo]   ✅ DECISION: reached — including content")
                    rest = line[_decision_re.match(line).end():].strip()
                    if rest:
                        rest = rest[0].upper() + rest[1:]
                        result.append((rest, section))
                continue  # skip the header token itself

            # ── propose / oppose: structural header handling ────────────────
            if section in ('propose', 'oppose'):
                arg_m     = _arg_re.match(line)
                counter_m = _counter_arg_re.match(line)
                if arg_m or counter_m:
                    m   = arg_m or counter_m
                    num = int(m.group(1))
                    tag = "ARG" if arg_m else "COUNTER-ARG"
                    if num == 1:
                        # ARGUMENT 1 / COUNTER-ARGUMENT 1 — keep gate open
                        include_content = True
                        print(f"[DebateVideo]   ✅ {tag} 1 — continuing to include")
                        # Capture any inline content on the header line itself
                        rest = line[m.end():].strip()
                        if rest:
                            rest = rest[0].upper() + rest[1:]
                            result.append((rest, section))
                    else:
                        # ARGUMENT 2+ / COUNTER-ARGUMENT 2+ — stop permanently
                        include_content = False
                        print(f"[DebateVideo]   ⏭️  {tag} {num} — short-form limit reached, stopping")
                    continue  # skip the header token itself

                # OPENING STATEMENT — skip the token, capture any inline text
                if _opening_re.match(line):
                    print(f"[DebateVideo]   📢 OPENING STATEMENT header — content included")
                    rest = line[_opening_re.match(line).end():].strip()
                    if rest and include_content:
                        rest = rest[0].upper() + rest[1:]
                        result.append((rest, section))
                    continue

                # Closing / conclusion headers — close the gate
                if _closing_re.match(line):
                    include_content = False
                    print(f"[DebateVideo]   ⏭️  Closing block: {line[:50]}")
                    continue

                # SUMMARY / ANALYSIS — always skip the header line
                if any(p.match(line) for p in _block_end_headers):
                    print(f"[DebateVideo]   ⏭️  Header skipped: {line[:50]}")
                    continue

            # ── decide: skip everything before DECISION: ────────────────────
            if section == 'decide' and not decide_decision_reached:
                print(f"[DebateVideo]   ⏭️  Pre-DECISION skipped: {line[:50]}")
                continue

            # ── Always-skip structural lines ────────────────────────────────
            if any(p.match(line) for p in _skip):
                continue

            # ── Gate: only emit when inside an includable block ─────────────
            if not include_content:
                continue

            line = line[0].upper() + line[1:]
            result.append((line, section))

        print(f"[DebateVideo] 📊 Parsed {len(result)} content lines (short-form)")
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
        """Diamond light effect for header title."""
        import math
        t = (frame % 600) / 600.0
        stops = [
            (0.00, (255, 255, 255)),
            (0.25, (255, 240, 180)),
            (0.50, (200, 235, 255)),
            (0.75, (235, 210, 255)),
            (1.00, (255, 255, 255)),
        ]
        c0, c1, f0, f1 = stops[0][1], stops[1][1], 0.0, 0.25
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i+1][0]:
                f0, c0 = stops[i]
                f1, c1 = stops[i+1]
                break
        seg     = (f1 - f0) if f1 != f0 else 1
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
                channel, wm_enabled, wm_text, video_fps, topic="", bg_opacity=255, bg_color=(0,0,0)):
        """Render debate video — identical layout engine to definition_video_tool."""
        from PIL import Image, ImageDraw, ImageFont
        FPS             = video_fps
        frames_per_line = int(secs_per_line * FPS)
        fade_frames     = min(6, frames_per_line // 5)
        BASE_ACTIVE     = w // 28
        SHRINK_STEP     = w // 130
        MIN_SIZE        = w // 58
        base_wm         = w // 52

        try:
            f_active = ImageFont.truetype(FONT_BOLD,  BASE_ACTIVE)
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
        header_h      = int(h * 0.17)
        pad_top       = header_h + int(h * 0.02)
        wm_zone       = int(h * 0.80)           # raised: more space for avatar section
        body_h        = wm_zone - pad_top
        active_font_h = int(BASE_ACTIVE * 1.9)
        active_y      = pad_top + body_h // 2 - active_font_h // 2
        max_px        = w - pad_x - int(w * 0.05)

        hdr_title  = _clean_text(topic) if topic else _clean_text(channel)
        _acronyms  = {'ai', 'ml', 'api',  'ui', 'ux', 'llm', 'gpt', 'ceo', 'cto', 'it'}
        hdr_title  = ' '.join(
            _word.upper() if _word.lower() in _acronyms else _word.capitalize()
            for _word in hdr_title.split()
        )
        hdr_max_px = w - pad_x * 2

        hdr_topic_size = max(w // 30, 22)
        f_hdr_topic    = None
        for size in range(hdr_topic_size, 18, -2):
            try:
                _f = ImageFont.truetype(FONT_BOLD, size)
            except Exception:
                _f = ImageFont.load_default()
            hdr_lines = self._pixel_wrap(hdr_title, _f, hdr_max_px)
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
        print(f"[DebateVideo]   Wrapped lines: {len(lines_data)}     "
              f"Total frames: {total_frames}     "
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
                    "{desc}: {percentage:3.0f}%|{bar:35}|    "
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

        _section_labels = {'propose': 'Proposition', 'oppose': 'Opposition', 'decide': 'Verdict'}
        _section_colors = {'propose': (130, 210, 255), 'oppose': (255, 100, 100), 'decide': (140, 255, 140)}
        _prev_section   = None

        import math as _math
        import random as _random

        # ── Base background ───────────────────────────────────────────────
        _bg_v  = max(0, min(255, bg_opacity))
        _base  = Image.new("RGBA", (w, h), (bg_color[0], bg_color[1], bg_color[2], 255))

        # ── Section color map ─────────────────────────────────────────────
        _sec_rgb = {
            'propose': (130, 210, 255),
            'oppose':  (255, 100, 100),
            'decide':  (140, 255, 140),
        }

        # ── Particle system (seeded for reproducibility) ──────────────────
        _rng = _random.Random(42)
        _N_PARTICLES = 22
        _particles = [
            {
                'x':   _rng.uniform(0, w),
                'y':   _rng.uniform(0, h),
                'vx':  _rng.uniform(-0.18, 0.18),
                'vy':  _rng.uniform(-0.22, -0.06),
                'r':   _rng.uniform(1.2, 3.0),
                'phase': _rng.uniform(0, _math.tau),
            }
            for _ in range(_N_PARTICLES)
        ]

        # ── Avatar layout constants (+30% section height) ────────────────
        # Left: PRO  |  Center: Verdict  |  Right: OPPO
        # Inset by (r * 1.34 * 1.10 + margin)  so wings never clip at edges
        _av_y      = int(h * 0.875)         # lower — bigger avatar zone below text
        _av_r      = int(w * 0.080)         # base radius
        _av_margin = int(_av_r * 1.34 * 1.15) + int(w * 0.010)  # wing-tip safe margin
        _av_left   = max(_av_margin, int(w * 0.16))   # PRO x-centre (inset from left edge)
        _av_right  = min(w - _av_margin, int(w * 0.84))  # OPPO x-centre (inset from right edge)
        _av_mid    = w // 2                 # Verdict x-centre

        # Each avatar always uses its own fixed color — never the active section color
        _av_colors = {
            'propose': (100, 180, 255),   # blue  — PRO
            'oppose':  (255, 90,  90),    # red   — OPPO
            'decide':  (120, 240, 140),   # green — Verdict
        }
        # Display labels under each avatar
        _av_labels = {
            'propose': 'PRO',
            'oppose':  'OPPO',
            'decide':  'Verdict',
        }

        # ── Waveform bar constants ────────────────────────────────────────
        _WV_BARS   = 32
        _WV_W      = int(w * 0.38)
        _WV_H      = int(h * 0.048)
        _WV_Y      = _av_y + _av_r + int(h * 0.012)  # below avatars
        _WV_X      = (w - _WV_W) // 2
        _BAR_GAP   = _WV_W // _WV_BARS

        # ── Section transition flash + avatar pop-in state ──────────────
        _flash_frames    = int(FPS * 0.35)   # 0.35s flash on section change
        _flash_counter   = 0
        _section_frame   = 0                 # frames elapsed in current section
        _prev_sec_for_fr = None              # tracks section changes for _section_frame

        def _draw_avatar(draw, cx, cy, r, role, speaking, frame):
            """
            Animated speaker avatar.
            Speaking  → 45% visual area (r * 1.34×) — wings, smile, confidence
            Silent    → 55% base (r * 0.74×) — dim, closed, waiting
            """
            import math as _m
            ac  = _av_colors.get(role, (200, 200, 200))
            dim = tuple(int(c * 0.28) for c in ac)   # dim version of color

            # ── WINGS (speaking only) ────────────────────────────────────
            # Two curved arcs fanning out left/right, flapping sinusoidally
            if speaking:
                wing_flap  = _m.sin(frame * 0.22)          # -1..1 flap cycle
                wing_raise = int(r * 0.55 * abs(wing_flap)) # how high wings lift
                wing_span  = int(r * 1.10)                  # lateral reach
                wing_thick = max(2, int(r * 0.10))

                # Left wing — 3 arcs getting lighter toward tip
                for wi, (wspan, wthick, walpha) in enumerate([
                    (wing_span,         wing_thick,     140),
                    (wing_span + r//3,  wing_thick - 1, 80),
                    (wing_span + r//2,  max(1, wing_thick - 2), 40),
                ]):
                    w_tip_y = cy - wing_raise - wi * int(r * 0.08)
                    draw.line(
                        [cx - r + int(r*0.2), cy,
                         cx - r - wspan + int(r*0.2), w_tip_y],
                        fill=(*ac, walpha), width=wthick
                    )
                    # Feather curl at tip
                    curl_r = max(3, int(r * 0.18))
                    draw.arc(
                        [cx - r - wspan - curl_r + int(r*0.2),
                         w_tip_y - curl_r,
                         cx - r - wspan + curl_r + int(r*0.2),
                         w_tip_y + curl_r],
                        start=0, end=180 + int(40 * wing_flap),
                        fill=(*ac, walpha), width=max(1, wthick - 1)
                    )

                # Right wing (mirror)
                for wi, (wspan, wthick, walpha) in enumerate([
                    (wing_span,         wing_thick,     140),
                    (wing_span + r//3,  wing_thick - 1, 80),
                    (wing_span + r//2,  max(1, wing_thick - 2), 40),
                ]):
                    w_tip_y = cy - wing_raise - wi * int(r * 0.08)
                    draw.line(
                        [cx + r - int(r*0.2), cy,
                         cx + r + wspan - int(r*0.2), w_tip_y],
                        fill=(*ac, walpha), width=wthick
                    )
                    curl_r = max(3, int(r * 0.18))
                    draw.arc(
                        [cx + r + wspan - curl_r - int(r*0.2),
                         w_tip_y - curl_r,
                         cx + r + wspan + curl_r - int(r*0.2),
                         w_tip_y + curl_r],
                        start=0, end=180 - int(40 * wing_flap),
                        fill=(*ac, walpha), width=max(1, wthick - 1)
                    )

            # ── HEAD CIRCLE ──────────────────────────────────────────────
            if speaking:
                # Multi-layer pulsing glow halo
                pulse = 0.55 + 0.45 * _m.sin(frame * 0.14)
                for dr in range(8, 0, -2):
                    ga = int(65 * (9 - dr) / 8 * pulse)
                    draw.ellipse([cx-r-dr*2, cy-r-dr*2, cx+r+dr*2, cy+r+dr*2],
                                outline=(*ac, ga), width=1)
                # Confident posture: slight upward bob
                bob = int(r * 0.04 * _m.sin(frame * 0.08))
                head_fill = tuple(int(c * 0.38) for c in ac)
                draw.ellipse([cx-r, cy-r+bob, cx+r, cy+r+bob],
                            fill=(*head_fill, 250), outline=(*ac, 255), width=3)
                _face_cy = cy + bob   # shift face features with bob
            else:
                # Dim ring only
                draw.ellipse([cx-r-1, cy-r-1, cx+r+1, cy+r+1],
                            outline=(*ac, 30), width=1)
                head_fill = tuple(int(c * 0.07) for c in ac)
                draw.ellipse([cx-r, cy-r, cx+r, cy+r],
                            fill=(*head_fill, 160), outline=(*ac, 50), width=1)
                _face_cy = cy

            # ── EYES ──────────────────────────────────────────────────────
            eye_y  = _face_cy - int(r * 0.20)
            eye_dx = int(r * 0.28)
            eye_r  = max(2, int(r * 0.12))

            if speaking:
                # Confident wide eyes with shine dot
                blink = _m.sin(frame * 0.041 + 1.2) > 0.93
                eye_col = (*ac, 255)
                for ex_off in [-eye_dx, eye_dx]:
                    if not blink:
                        # Main iris
                        draw.ellipse([cx+ex_off-eye_r, eye_y-eye_r,
                                      cx+ex_off+eye_r, eye_y+eye_r],
                                    fill=eye_col)
                        # White shine dot (top-right of each eye)
                        sh = max(1, eye_r // 3)
                        draw.ellipse([cx+ex_off+eye_r//3, eye_y-eye_r+1,
                                      cx+ex_off+eye_r//3+sh, eye_y-eye_r+1+sh],
                                    fill=(255, 255, 255, 200))
                    else:
                        draw.line([cx+ex_off-eye_r, eye_y,
                                    cx+ex_off+eye_r, eye_y],
                                  fill=eye_col, width=max(2, eye_r//2))
                # Raised eyebrows (confidence)
                brow_y = eye_y - eye_r - int(r * 0.09)
                brow_w = int(eye_r * 1.5)
                brow_raise = int(r * 0.03 * _m.sin(frame * 0.06))
                for ex_off in [-eye_dx, eye_dx]:
                    draw.line([cx+ex_off-brow_w, brow_y - brow_raise,
                              cx+ex_off+brow_w, brow_y - brow_raise - int(r*0.04)],
                             fill=(*ac, 200), width=max(2, int(r * 0.06)))
            else:
                # Dim half-closed eyes
                for ex_off in [-eye_dx, eye_dx]:
                    draw.ellipse([cx+ex_off-eye_r, eye_y-eye_r//2,
                                  cx+ex_off+eye_r, eye_y+eye_r//2],
                                fill=(*ac, 45))

            # ── SMILE / MOUTH ───────────────────────────────────────────
            mouth_cy = _face_cy + int(r * 0.26)
            mouth_w  = int(r * 0.44)
            mouth_h  = int(r * 0.18)

            if speaking:
                # Animated talking mouth — cycles open/closed
                talk_open = abs(_m.sin(frame * 0.52)) * int(r * 0.20) + int(r * 0.06)
                # Smile: arc bottom lip curves up at corners
                smile_lift = int(r * 0.08)
                # Draw smile arc (upper lip)
                draw.arc([cx - mouth_w, mouth_cy - smile_lift,
                          cx + mouth_w, mouth_cy + mouth_h + smile_lift],
                         start=200, end=340,
                         fill=(*ac, 255), width=max(2, int(r * 0.07)))
                # Inner mouth (dark gap, opens/closes)
                inner_h = max(2, int(talk_open * 0.6))
                inner_w = int(mouth_w * 0.72)
                draw.ellipse([cx - inner_w, mouth_cy - inner_h//2,
                              cx + inner_w, mouth_cy + inner_h],
                             fill=(*tuple(int(c*0.12) for c in ac), 220))
                # Teeth flash (bright strip)
                if talk_open > int(r * 0.08):
                    teeth_h = max(1, int(inner_h * 0.45))
                    draw.rectangle([cx - inner_w + 2, mouth_cy - teeth_h//2,
                                    cx + inner_w - 2, mouth_cy - teeth_h//2 + teeth_h],
                                   fill=(240, 240, 245, 200))
            else:
                # Neutral slight frown — not speaking
                draw.arc([cx - int(mouth_w*0.55), mouth_cy - int(r*0.04),
                          cx + int(mouth_w*0.55), mouth_cy + int(r*0.10)],
                         start=15, end=165,
                         fill=(*ac, 38), width=max(1, int(r * 0.05)))

            # ── CONFIDENCE SPARKLES (speaking only) ─────────────────────
            if speaking:
                import math as _ms
                n_sparks = 5
                spark_ring = r + int(r * 0.55)
                for si in range(n_sparks):
                    ang   = _ms.tau * si / n_sparks + frame * 0.06
                    sx    = cx + int(spark_ring * _ms.cos(ang))
                    sy    = _face_cy + int(spark_ring * _ms.sin(ang))
                    spulse = 0.4 + 0.6 * abs(_ms.sin(frame * 0.15 + si * 1.2))
                    sr    = max(1, int(r * 0.07 * spulse))
                    sa    = int(180 * spulse)
                    draw.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(*ac, sa))
                    # Star cross
                    cl = max(1, int(sr * 1.6))
                    draw.line([sx-cl, sy, sx+cl, sy], fill=(*ac, int(sa*0.6)), width=1)
                    draw.line([sx, sy-cl, sx, sy+cl], fill=(*ac, int(sa*0.6)), width=1)

            # ── LABEL ────────────────────────────────────────────────────
            role_label = _av_labels.get(role, role.upper())
            lbl_size   = max(16, int(r * 0.50)) if speaking else max(10, int(r * 0.36))
            try:    _fl = ImageFont.truetype(FONT_BOLD, lbl_size)
            except: _fl = ImageFont.load_default()
            lb    = draw.textbbox((0, 0), role_label, font=_fl)
            lw    = lb[2] - lb[0]
            lbl_y = cy + r + int(r * 0.22)
            if speaking:
                for ddx, ddy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1)]:
                    draw.text((cx - lw//2 + ddx, lbl_y + ddy), role_label,
                              font=_fl, fill=(*ac, 90))
                draw.text((cx - lw//2, lbl_y), role_label, font=_fl, fill=(*ac, 255))
            else:
                draw.text((cx - lw//2, lbl_y), role_label, font=_fl, fill=(*ac, 55))

        def _draw_waveform(draw, cx, cy_top, bar_w_total, bar_h_max, n_bars, frame, sec_col, speaking):
            """Draw animated equalizer waveform bars."""
            import math as _m
            bar_w   = (bar_w_total // n_bars) - 2
            bar_gap = bar_w + 2
            start_x = cx - bar_w_total // 2
            for i in range(n_bars):
                # Each bar oscillates at a slightly different phase/frequency
                phase  = i * 0.38 + frame * 0.18
                amp    = 0.3 + 0.7 * abs(_m.sin(phase))
                if not speaking:
                    amp = 0.08 + 0.06 * abs(_m.sin(phase * 0.3))
                bh = max(3, int(bar_h_max * amp))
                bx = start_x + i * bar_gap
                by = cy_top + bar_h_max - bh
                # Color gradient: section color, brighter in center
                center_dist = abs(i - n_bars / 2) / (n_bars / 2)
                brightness  = int(255 * (0.5 + 0.5 * (1 - center_dist)) * (0.9 if speaking else 0.3))
                bar_col = tuple(min(255, int(c * brightness / 180)) for c in sec_col)
                draw.rectangle([bx, by, bx+bar_w, cy_top+bar_h_max],
                               fill=(*bar_col, 200 if speaking else 80))

        def _draw_particles(draw, particles, sec_col, frame):
            """Draw floating ambient particles."""
            import math as _m
            for p in particles:
                # Drift upward, wrap around
                p['x'] = (p['x'] + p['vx']) % w
                p['y'] = p['y'] + p['vy']
                if p['y'] < -5:
                    p['y'] = h + 5
                pulse  = 0.4 + 0.6 * abs(_m.sin(frame * 0.04 + p['phase']))
                alpha  = int(40 * pulse)
                r_now  = max(1, int(p['r'] * pulse))
                pcol   = tuple(int(c * 0.6) for c in sec_col)
                x, y   = int(p['x']), int(p['y'])
                draw.ellipse([x-r_now, y-r_now, x+r_now, y+r_now],
                             fill=(*pcol, alpha))

        def _draw_flash(draw, w, h, sec_col, intensity):
            """Draw section-change color flash overlay."""
            if intensity <= 0:
                return
            alpha = int(60 * intensity)
            draw.rectangle([0, 0, w, h], fill=(*sec_col, alpha))

        global_frame = 0
        for line_idx, (ltext, cur_section) in enumerate(lines_data):

            # Detect section change for flash + avatar pop-in
            if line_idx > 0 and lines_data[line_idx-1][1] != cur_section:
                _flash_counter = _flash_frames
                _section_frame = 0
                _prev_sec_for_fr = cur_section

            for fi in range(frames_per_line):
                alpha    = min(1.0, fi / max(fade_frames, 1))
                sec_col  = _sec_rgb.get(cur_section, (200, 200, 200))
                _section_frame  += 1

                # ── Base frame (dark bg with opacity) ───────────────────
                img  = Image.new("RGBA", (w, h), (0, 0, 0, _bg_v))
                draw = ImageDraw.Draw(img)

                # ── Particles (behind everything) ────────────────────────
                _draw_particles(draw, _particles, sec_col, global_frame)

                # ── Section transition flash ──────────────────────────────
                if _flash_counter > 0:
                    _flash_intensity = _flash_counter / _flash_frames
                    _draw_flash(draw, w, h, sec_col, _flash_intensity)
                    _flash_counter -= 1

                # ── Header title ─────────────────────────────────────────
                hdr_line_h = int(hdr_topic_size * 1.35)
                hdr_y      = int(h * 0.018)
                for hdr_ln in hdr_lines:
                    hdr_bbox = draw.textbbox((0, 0), hdr_ln, font=f_hdr_topic)
                    hdr_w    = hdr_bbox[2] - hdr_bbox[0]
                    hdr_x    = (w - hdr_w) // 2
                    self._draw_diamond_title(draw, hdr_x, hdr_y, hdr_ln, f_hdr_topic, global_frame)
                    hdr_y   += hdr_line_h

                # ── Section badge ───────────────────────────────────────────
                _sec_label = _section_labels.get(cur_section, cur_section.capitalize())
                _sec_size  = max(w // 44, 22)
                try:     _f_sec = ImageFont.truetype(FONT_BOLD, _sec_size)
                except: _f_sec = ImageFont.load_default()
                _sec_gap  = int(h * 0.005)
                _sec_y    = hdr_y + _sec_gap
                _sec_bbox = draw.textbbox((0, 0), _sec_label, font=_f_sec)
                _sec_w    = _sec_bbox[2] - _sec_bbox[0]
                _sec_h    = _sec_bbox[3] - _sec_bbox[1]
                _sec_x    = (w - _sec_w) // 2
                _sec_alpha = min(1.0, fi / max(fade_frames, 1)) if cur_section != _prev_section else 1.0
                _pad_x2, _pad_y2 = int(w * 0.018), int(h * 0.004)
                _bg_badge = tuple(int(ch * 0.28 * _sec_alpha) for ch in sec_col)
                _border   = tuple(int(ch * _sec_alpha) for ch in sec_col)
                draw.rectangle(
                    [_sec_x - _pad_x2, _sec_y - _pad_y2, _sec_x + _sec_w + _pad_x2, _sec_y + _sec_h + _pad_y2],
                    fill=_bg_badge, outline=_border, width=2
                )
                _ca = (int(255 * _sec_alpha),) * 3
                for _dx, _dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                    draw.text((_sec_x+_dx, _sec_y+_dy), _sec_label, font=_f_sec,
                              fill=tuple(int(ch * 0.5 * _sec_alpha) for ch in sec_col))
                draw.text((_sec_x, _sec_y), _sec_label, font=_f_sec, fill=_ca)
                _prev_section = cur_section
                _ul_y = _sec_y + _sec_h + _pad_y2 + 2

                sep_y = max(header_h - 2, _ul_y + int(h * 0.008))
                draw.line([(pad_x, sep_y), (w - pad_x, sep_y)], fill=(50, 60, 80), width=1)

                # ── Active line glow highlight bar ───────────────────────
                glow_h  = active_font_h + int(h * 0.012)
                glow_y  = active_y - int(h * 0.006)
                glow_a  = int(35 * alpha)
                glow_c  = tuple(int(c * 0.5) for c in sec_col)
                draw.rectangle([0, glow_y, w, glow_y + glow_h],
                               fill=(*glow_c, glow_a))

                # ── Past lines (scroll up, fade/shrink) ──────────────────
                past_indices  = list(range(max(0, line_idx - 30), line_idx))
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

                # ── Active line (neon glow) ───────────────────────────────
                neon_c = self._neon_white(alpha, global_frame)
                self._justify(draw, pad_x, active_y, ltext, f_active, max_px, neon_c)

                # ── Future lines (fade in below) ──────────────────────────
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

                # ── Avatars ──────────────────────────────────────────────────
                # Active  → 1.34× base radius  → ~45% visual area
                # Inactive→ 0.74× base radius  → ~55% relative area (smaller, dim)
                # Pop-in bounce: overshoots 25% then settles over 18 frames
                import math as _mav
                _pop_frames = 18
                _pop_t      = min(1.0, _section_frame / _pop_frames)
                _bounce     = 1.0 + 0.25 * _mav.sin(_pop_t * _mav.pi) * (1.0 - _pop_t)
                _SPK = 1.34 * _bounce   # active radius multiplier
                _SIL = 0.74             # inactive radius multiplier
                _pro_r = int(_av_r * (_SPK if cur_section == 'propose' else _SIL))
                _con_r = int(_av_r * (_SPK if cur_section == 'oppose' else _SIL))
                _mod_r = int(_av_r * (_SPK * 0.78 if cur_section == 'decide' else _SIL * 0.72))
                _draw_avatar(draw, _av_left,  _av_y, _pro_r, 'propose',
                             cur_section == 'propose', global_frame)
                _draw_avatar(draw, _av_right, _av_y, _con_r, 'oppose',
                             cur_section == 'oppose', global_frame)
                _draw_avatar(draw, _av_mid,   _av_y, _mod_r, 'decide',
                             cur_section == 'decide', global_frame)

                # ── Waveform equalizer bars ────────────────────────────────
                _draw_waveform(draw, w//2, _WV_Y, _WV_W, _WV_H, _WV_BARS,
                               global_frame, sec_col, speaking=True)

                # ── Progress bar (section-colored) ───────────────────────
                prog   = (line_idx * frames_per_line + fi) / total_frames
                bar_y  = h - int(h * 0.008)
                bar_h  = max(3, int(h * 0.007))
                filled = int(w * prog)
                draw.rectangle([0, bar_y, w, bar_y + bar_h], fill=(25, 25, 35, 200))
                if filled > 0:
                    draw.rectangle([0, bar_y, filled, bar_y + bar_h],
                                   fill=(*sec_col, 220))

                # ── Watermark ─────────────────────────────────────────────
                tag     = wm_text if wm_enabled else f"@{channel}"
                tw_bbox = draw.textbbox((0, 0), tag, font=f_wm)
                tw      = tw_bbox[2] - tw_bbox[0]
                wm_x    = (w - tw) // 2
                wm_y    = wm_zone + int(h * 0.005)
                draw.text((wm_x, wm_y), tag, font=f_wm, fill=(30, 30, 38))

                # ── Composite and pipe ────────────────────────────────────
                _composited  = Image.alpha_composite(_base, img)
                proc.stdin.write(_composited.convert("RGB").tobytes())
                global_frame += 1
                if pbar is not None:
                    pbar.update(1)

        if pbar is not None:
            pbar.close()
        proc.stdin.close()
        proc.wait()
        elapsed = time.time() - t0
        print(f"[DebateVideo]   ✅ Encoded in {elapsed:.0f}s ({elapsed/60:.1f}min)")
