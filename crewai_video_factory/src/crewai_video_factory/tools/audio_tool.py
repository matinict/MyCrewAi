import os
import re
import shutil
import glob
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class AudioGenerationToolInput(BaseModel):
    """Input schema for AudioGenerationTool."""
    topic: str = Field(..., description="Topic/title for narration")
    filename: str = Field(..., description="Base filename slug (e.g. LLMPopularity)")
    output_dir: str = Field(..., description="Output directory containing standard videos")
    video_formats: list = Field(..., description="List of video formats used (HD, Shorts, etc.)")
    animation_styles: list = Field(default=["bar_race"], description="List of animation styles used (e.g. bar_race)")
    audio_enabled: bool = Field(default=False, description="Whether to generate audio")
    audio_speed: float = Field(default=1.0, ge=0.7, le=1.3, description="Speech speed for Shorts. HD uses audio_speed_hd if set.")
    audio_speed_hd: float = Field(default=0.0, ge=0.0, le=1.3, description="Speech speed for HD. If 0.0, falls back to audio_speed.")
    channel: str = Field(default="PlayOwnAi", description="Channel name for narration. No @ prefix needed.")


class AudioGenerationTool(BaseTool):
    """
    Generates audio narration for standard (non-bar-race) videos.
    Targets [style]_[format]_[style]_[format].mp4 files in output_dir.
    Triggered by audio_enabled=true in data.json.
    """
    name: str = "Audio Generation Tool"
    description: str = (
        "Generates audio narration MP3 files for standard visualization videos. "
        "Targets style_format_*.mp4 files in the output directory. "
        "Triggered by audio_enabled=true."
    )
    args_schema: Type[BaseModel] = AudioGenerationToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        video_formats: list,
        animation_styles: list = None,
        audio_enabled: bool = False,
        audio_speed: float = 1.0,
        audio_speed_hd: float = 0.0,
        channel: str = "PlayOwnAi",
    ) -> str:

        # --- IMMEDIATE SKIP ---
        if not audio_enabled:
            return "🔇 Audio generation skipped (audio_enabled=false)"

        # --- SANITIZE FILENAME ---
        filename_clean = ''.join(re.findall(r'\w+', filename)[:3])
        print(f"[AudioGenerationTool] filename sanitized: '{filename}' → '{filename_clean}'")

        if animation_styles is None:
            animation_styles = ["bar_race"]

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

        # --- FIND CSV ---
        parent_dir = os.path.dirname(os.path.abspath(output_dir))
        csv_candidates = [
            f"output/{filename_clean}.csv",
            f"output/{filename}.csv",
            os.path.join(parent_dir, f"{filename_clean}.csv"),
            os.path.join(parent_dir, f"{filename}.csv"),
            os.path.join(output_dir, f"{filename_clean}.csv"),
            os.path.join(output_dir, f"{filename}.csv"),
        ]
        csv_path = next((p for p in csv_candidates if os.path.exists(p)), None)

        if not csv_path:
            found = glob.glob(os.path.join(parent_dir, "*.csv"))
            if found:
                csv_path = found[0]
                print(f"[AudioGenerationTool] CSV found via glob fallback: {csv_path}")

        if csv_path:
            print(f"[AudioGenerationTool] CSV found: {csv_path}")
        else:
            print(f"[AudioGenerationTool] ⚠️  CSV not found — using fallback narration")

        # --- SPEED SETTINGS ---
        shorts_speed = audio_speed
        hd_speed = audio_speed_hd if audio_speed_hd > 0.0 else audio_speed
        print(f"[AudioGenerationTool] Speed — Shorts: {shorts_speed}, HD: {hd_speed}")

        # --- FIND TARGET VIDEOS ---
        # Standard naming: {style}_{fmt}_{style}_{fmt}.mp4  e.g. bar_race_Shorts_bar_race_Shorts.mp4
        all_mp4 = glob.glob(os.path.join(output_dir, "*.mp4"))
        video_files = [
            f for f in all_mp4
            if "_with_audio" not in f
            and "_audio" not in f
            and not os.path.basename(f).startswith("bar_race_")
            and not os.path.basename(f).startswith("intro_")
            and not os.path.basename(f).startswith("Merge_")
        ]

        print(f"[AudioGenerationTool] Target videos: {[os.path.basename(v) for v in video_files]}")

        if not video_files:
            existing = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return (
                f"❌ No standard video files found in {output_dir}\n"
                f"All mp4s present: {', '.join(existing) if existing else 'None'}"
            )

        # --- GENERATE NARRATION VARIANTS ---
        narration_short = self._generate_narration(topic, csv_path, with_points=False, channel=channel)
        narration_full  = self._generate_narration(topic, csv_path, with_points=True,  channel=channel)

        # Save narration text files
        cc_shorts_path = os.path.join(output_dir, f"{filename_clean}_Shorts_cc_en.txt")
        cc_hd_path     = os.path.join(output_dir, f"{filename_clean}_HD_cc_en.txt")
        with open(cc_shorts_path, 'w', encoding='utf-8') as f:
            f.write(narration_short)
        with open(cc_hd_path, 'w', encoding='utf-8') as f:
            f.write(narration_full)
        print(f"[AudioGenerationTool] Narration saved: {cc_shorts_path}, {cc_hd_path}")

        # --- GENERATE AUDIO PER VIDEO ---
        results = []
        errors = []

        for video_path in video_files:
            basename = os.path.basename(video_path)
            is_portrait = any(
                f"_{fmt}_" in basename and fmt in ["Shorts", "ShortsHD", "Shorts4K"]
                for fmt in ["Shorts", "ShortsHD", "Shorts4K"]
            )
            speed      = shorts_speed if is_portrait else hd_speed
            narration  = narration_short if is_portrait else narration_full
            audio_path = video_path.replace('.mp4', '_audio.mp3')

            print(f"[AudioGenerationTool] {'Shorts' if is_portrait else 'HD'} → {basename}  speed={speed}")
            try:
                self._generate_audio(narration, audio_path, speed)
                if os.path.exists(audio_path):
                    size_kb = os.path.getsize(audio_path) // 1024
                    results.append(f"{os.path.basename(audio_path)} ({size_kb}KB)")
                    print(f"[AudioGenerationTool] ✅ {audio_path} ({size_kb}KB)")
                else:
                    errors.append(f"❌ Not created: {audio_path}")
            except Exception as e:
                errors.append(f"❌ Error for {basename}: {e}")

        if not results:
            return "❌ Audio generation failed for all videos.\nErrors:\n" + "\n".join(errors)

        summary = (
            f"🎵 Audio narration files created:\n"
            + "\n".join([f"   • {r}" for r in results])
            + f"\n\n📝 Narration saved: {cc_shorts_path}"
        )
        if errors:
            summary += "\n\n⚠️ Some errors:\n" + "\n".join(errors)
        return summary

    # ------------------------------------------------------------------
    # Narration generator — same logic as BarRaceAudioTool
    # ------------------------------------------------------------------
    def _generate_narration(self, topic: str, csv_path, with_points: bool = False, channel: str = "PlayOwnAi") -> str:
        if csv_path and os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                time_col  = df.columns[0]
                data_cols = df.columns[1:]
                start_year = int(df[time_col].iloc[0])
                end_year   = int(df[time_col].iloc[-1])

                if not with_points:
                    parts = [
                        f"Welcome to {channel}.",
                        f"{topic} Race {start_year} to {end_year}.",
                        "Basic trending idea. Let's go year by year.",
                    ]
                else:
                    parts = [
                        f"Welcome to {channel}.",
                        f"Today, we're exploring the {topic} Race from {start_year} to {end_year}.",
                        "This is for a basic idea about trending.",
                        "Let's see how the landscape evolved, year by year.",
                    ]

                for _, row in df.iterrows():
                    year   = int(row[time_col])
                    leader = row[data_cols].idxmax()
                    value  = int(row[data_cols].max())

                    if value == 0:
                        parts.append(f"{year}. Race not yet begun." if not with_points else f"{year}. The race has not yet begun.")
                    elif value <= 20:
                        parts.append(f"{year}. {leader} leads. Market forming." if not with_points
                                     else f"{year}. {leader} leads with {value} points. The market is forming.")
                    elif value <= 40:
                        parts.append(f"{year}. {leader} leads. Gaining traction." if not with_points
                                     else f"{year}. {leader} leads with {value} points. Gaining traction.")
                    elif value <= 70:
                        parts.append(f"{year}. {leader} leads. Showing strength." if not with_points
                                     else f"{year}. {leader} leads with {value} points. Showing real strength.")
                    else:
                        parts.append(f"{year}. {leader} dominates." if not with_points
                                     else f"{year}. {leader} dominates with {value} points.")

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
                        "Evolution continues.",
                        f"Subscribe to {channel} for more insights.",
                    ])
                return " ".join(parts)

            except Exception as e:
                print(f"[AudioGenerationTool] CSV parse error: {e}")

        return (
            f"Welcome to {channel}. Today, we're exploring {topic} trends. "
            "Let's see how the landscape evolved over time. "
            f"Subscribe to {channel} for more insights."
        )

    # ------------------------------------------------------------------
    # Audio generation via gTTS + ffmpeg
    # ------------------------------------------------------------------
    def _generate_audio(self, text: str, output_path: str, speed: float):
        from gtts import gTTS
        import subprocess

        temp_path = output_path.replace('.mp3', '_temp.mp3')
        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        tts.save(temp_path)

        if abs(speed - 1.0) > 0.05:
            atempo = max(0.5, min(2.0, speed))
            result = subprocess.run(
                ['ffmpeg', '-y', '-i', temp_path, '-filter:a', f'atempo={atempo}', output_path],
                capture_output=True, check=False
            )
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if result.returncode != 0 and not os.path.exists(output_path):
                raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:200]}")
        else:
            os.rename(temp_path, output_path)

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None
