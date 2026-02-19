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
    audio_speed: float = Field(default=1.0, ge=0.7, le=1.3, description="Speech speed for HD. Shorts uses audio_speed+0.2.")
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
        narration = self._generate_narration(topic, csv_path, channel=channel)
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
        narration_full  = self._generate_narration(topic, csv_path, with_points=True, channel=channel)

        # Save HD cc_en
        if hd_videos:
            hd_cc_path = os.path.join(output_dir, "bar_race_HD_cc_en.txt")
            with open(hd_cc_path, 'w', encoding='utf-8') as f:
                f.write(narration_full)
            print(f"[BarRaceAudioTool] HD narration saved: {hd_cc_path}")

        # --- GENERATE AUDIO ---
        results = []
        errors = []

        shorts_speed = min(1.3, audio_speed + 0.2)  # Shorts: base + 0.2, capped at 1.3
        print(f"[BarRaceAudioTool] Speed — HD: {audio_speed}, Shorts: {shorts_speed}")

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
                self._generate_audio(narration_full, audio_path, audio_speed)
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

    def _generate_narration(self, topic: str, csv_path: str | None, with_points: bool = False, channel: str = "PlayOwnAi") -> str:
        """Generate narration with one spoken line per year from CSV."""
        if csv_path and os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)

                time_col = df.columns[0]
                data_cols = df.columns[1:]
                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])

                # Shorts: concise narration / HD: full narration
                if not with_points:
                    parts = [
                        f"Welcome to {channel}.",
                        f"{topic} Race {start_year} to {end_year}.",
                        "Basic trending idea. Let's landscape year by year.",
                    ]
                else:
                    parts = [
                        f"Welcome to {channel}.",
                        f"Today, we're exploring the {topic} Race from {start_year} to {end_year}.",
                        "This is for a basic idea about trending.",
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
                    parts.extend([
                        f"And that brings us to {end_year}, where {final_leader} continues to lead the pack.",
                        "The evolution of technology and trends never stops.",
                        f"Subscribe to {channel} for more data-driven insights.",
                    ])
                else:
                    parts.extend([
                        f"{end_year}. {final_leader} leads the pack.",
                        "Evolution of technology trends continuing.",
                        f"Subscribe to {channel} for more insights.",
                    ])
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
        """Generate MP3 from text via gTTS, with ffmpeg speed adjustment."""
        from gtts import gTTS
        import subprocess

        temp_path = output_path.replace('.mp3', '_temp.mp3')
        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        tts.save(temp_path)

        if abs(speed - 1.0) > 0.05:
            atempo = max(0.5, min(2.0, speed))
            result = subprocess.run([
                'ffmpeg', '-y', '-i', temp_path,
                '-filter:a', f'atempo={atempo}', output_path
            ], capture_output=True, check=False)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if result.returncode != 0 and not os.path.exists(output_path):
                raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:200]}")
        else:
            os.rename(temp_path, output_path)

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None
