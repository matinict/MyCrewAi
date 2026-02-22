import os
import re
import shutil
import glob
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class BarRaceAudioToolInput(BaseModel):
    """Input schema for BarRaceAudioTool."""
    topic: str = Field(..., description="Topic/title for narration")
    filename: str = Field(..., description="Base filename slug (e.g. LLMPopularity)")
    output_dir: str = Field(..., description="Output directory containing bar race videos")
    video_formats: list = Field(..., description="List of video formats used (HD, Shorts, etc.)")
    bar_race_audio_enabled: bool = Field(default=False, description="Whether to generate bar race audio")
    audio_speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed for Shorts via ffmpeg atempo. 0.5=half speed, 1.0=normal, 2.0=double speed.")
    audio_speed_hd: float = Field(default=0.0, ge=0.0, le=2.0, description="Speech speed for HD via ffmpeg atempo. 0.0=use audio_speed for both. Set explicitly to override HD independently.")
    channel: str = Field(default="PlayOwnAi", description="Channel name for narration (e.g. PlayOwnAi). No @ prefix needed.")


class BarRaceAudioTool(BaseTool):
    """
    Generates audio narration for bar race videos (bar_race_*.mp4).
    Reads every year from CSV and generates one spoken line per year.
    Triggered by bar_race_audio_enabled=true in data.json.
    """
    name: str = "Bar Race Audio Tool"
    description: str = (
        "Generates audio narration MP3 files for bar race videos. "
        "Targets bar_race_*.mp4 files in the output directory. "
        "Triggered by bar_race_audio_enabled=true."
    )
    args_schema: Type[BaseModel] = BarRaceAudioToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        video_formats: list,
        bar_race_audio_enabled: bool = False,
        audio_speed: float = 1.0,
        audio_speed_hd: float = 0.0,
        channel: str = "PlayOwnAi",
    ) -> str:

        # --- IMMEDIATE SKIP ---
        if not bar_race_audio_enabled:
            return "🔇 Bar race audio skipped (bar_race_audio_enabled=false)"

        # --- SANITIZE FILENAME ---
        # Agent may pass full topic string instead of slug — fix it here
        filename_clean = ''.join(re.findall(r'\w+', filename)[:3])
        print(f"[BarRaceAudioTool] filename sanitized: '{filename}' → '{filename_clean}'")

        # --- DEPENDENCY CHECK ---
        if not self._ffmpeg_available():
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        try:
            from gtts import gTTS
        except ImportError:
            return "❌ FATAL: gTTS not installed. Run: pip install gTTS"

        # --- VALIDATE OUTPUT DIR ---
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        # --- FIND CSV (try many locations) ---
        parent_dir = os.path.dirname(os.path.abspath(output_dir))
        csv_candidates = [
            # Relative paths (when cwd is project root)
            f"output/{filename_clean}.csv",
            f"output/{filename}.csv",
            # Using output_dir parent (most reliable)
            os.path.join(parent_dir, f"{filename_clean}.csv"),
            os.path.join(parent_dir, f"{filename}.csv"),
            # Inside output_dir itself
            os.path.join(output_dir, f"{filename_clean}.csv"),
            os.path.join(output_dir, f"{filename}.csv"),
            # Glob fallback: any CSV in parent
        ]
        csv_path = next((p for p in csv_candidates if os.path.exists(p)), None)

        # Last resort: glob for any .csv in parent dir
        if not csv_path:
            import glob as _glob
            found = _glob.glob(os.path.join(parent_dir, "*.csv"))
            if found:
                csv_path = found[0]
                print(f"[BarRaceAudioTool] CSV found via glob fallback: {csv_path}")

        if csv_path:
            print(f"[BarRaceAudioTool] CSV found: {csv_path}")
        else:
            print(f"[BarRaceAudioTool] ❌ CSV not found. Tried: {csv_candidates}")
            print(f"[BarRaceAudioTool]    parent_dir={parent_dir}, cwd={os.getcwd()}")

        # --- GENERATE NARRATION ---
        narration = self._generate_narration(topic, csv_path, channel=channel,
                                               filename_clean=filename_clean, output_dir=output_dir)
        print(f"[BarRaceAudioTool] Narration length: {len(narration)} chars")

        # --- SAVE NARRATION TEXT (Shorts only) ---
        cc_path = os.path.join(output_dir, "bar_race_Shorts_cc_en.txt")
        with open(cc_path, 'w', encoding='utf-8') as f:
            f.write(narration)
        print(f"[BarRaceAudioTool] Narration saved: {cc_path}")

        # --- FIND ALL BAR RACE VIDEOS ---
        all_mp4 = glob.glob(os.path.join(output_dir, "bar_race_*.mp4"))
        all_bar_videos = [
            f for f in all_mp4
            if "_with_audio" not in f and "_audio" not in f
        ]
        shorts_videos = [f for f in all_bar_videos if "Shorts" in os.path.basename(f)]
        hd_videos     = [f for f in all_bar_videos if "Shorts" not in os.path.basename(f)]
        print(f"[BarRaceAudioTool] Shorts videos: {[os.path.basename(v) for v in shorts_videos]}")
        print(f"[BarRaceAudioTool] HD videos:     {[os.path.basename(v) for v in hd_videos]}")

        if not all_bar_videos:
            existing = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return (
                f"❌ No bar_race_*.mp4 files found in {output_dir}\n"
                f"All mp4s present: {', '.join(existing) if existing else 'None'}"
            )

        # Narration variants
        narration_short = narration  # no points (already generated above)
        narration_full  = self._generate_narration(topic, csv_path, with_points=True, channel=channel,
                                                    filename_clean=filename_clean, output_dir=output_dir)

        # Save HD cc_en
        if hd_videos:
            hd_cc_path = os.path.join(output_dir, "bar_race_HD_cc_en.txt")
            with open(hd_cc_path, 'w', encoding='utf-8') as f:
                f.write(narration_full)
            print(f"[BarRaceAudioTool] HD narration saved: {hd_cc_path}")

        # --- GENERATE AUDIO ---
        results = []
        errors = []

        shorts_speed = audio_speed  # Shorts uses audio_speed directly
        hd_speed = audio_speed_hd if audio_speed_hd > 0.0 else audio_speed  # HD: explicit override or fallback
        print(f"[BarRaceAudioTool] Speed — Shorts: {shorts_speed}, HD: {hd_speed}")

        for video_path in shorts_videos:
            audio_path = video_path.replace('.mp4', '_audio.mp3')
            print(f"[BarRaceAudioTool] Generating Shorts audio: {audio_path}")
            try:
                self._generate_audio(narration_short, audio_path, shorts_speed)
                if os.path.exists(audio_path):
                    size_kb = os.path.getsize(audio_path) // 1024
                    results.append(f"{os.path.basename(audio_path)} ({size_kb}KB)")
                    print(f"[BarRaceAudioTool] ✅ Shorts audio: {audio_path} ({size_kb}KB)")
                else:
                    errors.append(f"❌ Not created: {audio_path}")
            except Exception as e:
                errors.append(f"❌ Shorts error: {e}")

        for video_path in hd_videos:
            audio_path = video_path.replace('.mp4', '_audio.mp3')
            print(f"[BarRaceAudioTool] Generating HD audio: {audio_path}")
            try:
                self._generate_audio(narration_full, audio_path, hd_speed)
                if os.path.exists(audio_path):
                    size_kb = os.path.getsize(audio_path) // 1024
                    results.append(f"{os.path.basename(audio_path)} ({size_kb}KB)")
                    print(f"[BarRaceAudioTool] ✅ HD audio: {audio_path} ({size_kb}KB)")
                else:
                    errors.append(f"❌ Not created: {audio_path}")
            except Exception as e:
                errors.append(f"❌ HD error: {e}")

        if not results:
            return "❌ Audio generation failed for all bar race videos.\nErrors:\n" + "\n".join(errors)

        summary = (
            f"🎵 Bar race audio files created:\n"
            + "\n".join([f"   • {r}" for r in results])
            + f"\n\n📝 Narration saved: {cc_path}"
            + f'\n\nNarration preview: "{narration[:120]}..."'
        )
        if errors:
            summary += "\n\n⚠️ Some errors:\n" + "\n".join(errors)
        return summary

    def _read_definition_txt(self, filename_clean: str, output_dir: str) -> str:
        """
        Read and clean the topic definition .txt file.
        Returns plain spoken text starting from WHAT IS...
        Strips ━━━, 📖, Channel:, Subscribe:, [instructions], doubled terms.
        """
        parent_dir = os.path.dirname(os.path.abspath(output_dir))
        candidates = [
            os.path.join(parent_dir, f"{filename_clean}.txt"),
            f"output/{filename_clean}.txt",
        ]
        txt_path = next((p for p in candidates if os.path.exists(p)), None)
        if not txt_path:
            return ""

        import re as _re
        with open(txt_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        lines_out = []
        skip = False
        for ln in raw.splitlines():
            s = ln.strip()
            if not s or s.startswith('━') or s.startswith('─'):
                continue
            # Strip emoji icons
            s = _re.sub(r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff\u2600-\u27ff]+\s*', '', s).strip()
            if not s:
                continue
            if _re.match(r'^(TOPIC:|Channel:|Subscribe to)', s, _re.I):
                continue
            if _re.match(r'^(TIMELINE|WHAT YOU WILL SEE)', s, _re.I):
                skip = True
            if skip:
                continue
            # Remove [instruction leakage]
            s = _re.sub(r'\[.*?\]', '', s).strip()
            if not s:
                continue
            # Fix doubled term numbers
            s = _re.sub(r'KEY\s+TERMS\s+(\d+):\s*\1:\s*', r'KEY TERMS \1: ', s)
            s = _re.sub(r'KEY\s+TERMS\s+(\d+):', r'KEY TERMS \1:', s)
            s = _re.sub(r'\bTerm\s+(\d+):\s*', r'\1: ', s)
            s = _re.sub(r'\b(\d+):\s+\1:\s*', r'\1: ', s)
            # Replace section headers with spoken versions
            s = _re.sub(r'^WHAT IS (.+?)\?\s*$', r'What is \1?', s, flags=_re.I)
            s = _re.sub(r'^WHY DOES IT MATTER\?\s*$', 'Why does it matter?', s, flags=_re.I)
            s = _re.sub(r'^KEY TERMS\s*$', 'Key terms.', s, flags=_re.I)
            s = _re.sub(r'^KEY TERMS\s*(\d+):', r'Term \1:', s)
            lines_out.append(s)

        return ' '.join(lines_out).strip()

    def _generate_narration(self, topic: str, csv_path: str | None, with_points: bool = False, channel: str = "PlayOwnAi", filename_clean: str = "", output_dir: str = "") -> str:
        """Generate narration: definition intro + year-by-year race commentary."""
        if csv_path and os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)

                time_col = df.columns[0]
                data_cols = df.columns[1:]
                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])

                # Read definition .txt for intro narration
                definition_intro = self._read_definition_txt(filename_clean, output_dir) if filename_clean and output_dir else ""

                if not with_points:
                    parts = [
                        f"Welcome to {channel}.",
                        f"{topic} Race {start_year} to {end_year}.",
                        "Let's watch the race year by year.",
                    ]
                else:
                    parts = [
                        f"Welcome to {channel}.",
                        f"Today, we're exploring the {topic} Race from {start_year} to {end_year}.",
                        "Let's see how the landscape evolved, year by year.",
                    ]

                # One narration line per year
                for _, row in df.iterrows():
                    year = int(row[time_col])
                    leader = row[data_cols].idxmax()
                    value = int(row[data_cols].max())

                    if value == 0:
                        parts.append(f"{year}. Race not yet begun." if not with_points else f"{year}. The race has not yet begun.")
                    elif value <= 20:
                        if with_points:
                            parts.append(f"{year}. {leader} leads with {value} points. The market is forming.")
                        else:
                            parts.append(f"{year}. {leader} leads. Market forming.")
                    elif value <= 40:
                        if with_points:
                            parts.append(f"{year}. {leader} leads with {value} points. Gaining traction.")
                        else:
                            parts.append(f"{year}. {leader} leads. Gaining traction.")
                    elif value <= 70:
                        if with_points:
                            parts.append(f"{year}. {leader} leads with {value} points. Showing real strength.")
                        else:
                            parts.append(f"{year}. {leader} leads. Showing strength.")
                    else:
                        if with_points:
                            parts.append(f"{year}. {leader} dominates with {value} points.")
                        else:
                            parts.append(f"{year}. {leader} dominates.")

                final_leader = df.iloc[-1][data_cols].idxmax()
                if with_points:
                    parts.append(f"And that brings us to {end_year}, where {final_leader} continues to lead the pack.")
                    parts.append("The evolution of technology and trends never stops.")
                    if definition_intro:
                        parts.append(definition_intro)
                    parts.append(f"Subscribe to {channel} for more data-driven insights.")
                else:
                    parts.append(f"{end_year}. {final_leader} leads the pack.")
                    parts.append("Evolution of technology trends continuing.")
                    if definition_intro:
                        parts.append(definition_intro)
                    parts.append(f"Subscribe to {channel} for more insights.")
                return " ".join(parts)

            except Exception as e:
                print(f"[BarRaceAudioTool] CSV parse error: {e}")

        # Fallback
        return (
            f"Welcome to {channel}. Today, we're exploring {topic} trends. "
            "Let's see how the landscape evolved over time. "
            "The evolution of technology and trends continues. "
            f"Subscribe to {channel} for more insights."
        )

    def _generate_audio(self, text: str, output_path: str, speed: float):
        """Generate MP3 from text via gTTS, with ffmpeg atempo speed adjustment.

        gTTS only has binary slow/normal mode — actual speed is always set via
        ffmpeg atempo filter so Shorts and HD are always independently controlled.
        gTTS is always generated at normal speed (slow=False); atempo handles all
        speed differences including values at exactly 1.0 vs 0.8 etc.
        """
        from gtts import gTTS
        import subprocess
        import threading
        import time

        label = os.path.basename(output_path)
        char_count = len(text)
        est_total = max(5, int(char_count * 0.015)) + 3
        print(f"[BarRaceAudioTool] ⏱  {label} — ~{est_total}s estimated ({char_count} chars)")

        # --- Progress: single line every 5s ---
        _stop = threading.Event()
        def _ticker(label, start):
            while not _stop.is_set():
                time.sleep(5)
                if not _stop.is_set():
                    print(f"[BarRaceAudioTool] ⏳ {label} ... {int(time.time()-start)}s")
        t_start = time.time()
        ticker = threading.Thread(target=_ticker, args=(label, t_start), daemon=True)
        ticker.start()

        try:
            # --- Step 1: gTTS ---
            temp_path = output_path.replace('.mp3', '_temp.mp3')
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(temp_path)

            # --- Step 2: ffmpeg atempo ---
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

        total_elapsed = time.time() - t_start
        if result.returncode != 0 and not os.path.exists(output_path):
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:200]}")

        size_kb = os.path.getsize(output_path) // 1024 if os.path.exists(output_path) else 0
        print(f"[BarRaceAudioTool] ✅ {label} done in {total_elapsed:.1f}s ({size_kb}KB, atempo={atempo})")

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None
