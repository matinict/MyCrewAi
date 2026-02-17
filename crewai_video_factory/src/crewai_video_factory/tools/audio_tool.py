import os
import shutil
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

# NEW
class AudioGenerationToolInput(BaseModel):
    """Input schema for AudioGenerationTool."""
    topic: str = Field(..., description="Topic/title for narration")
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
    output_dir: str = Field(..., description="Output directory for audio files")
    animation_styles: list = Field(..., description="List of animation styles used")
    video_formats: list = Field(..., description="List of video formats used")
    audio_enabled: bool = Field(default=False, description="Whether to generate audio")
    audio_speed: float = Field(default=0.9, ge=0.7, le=1.3, description="Speech speed (0.7-1.3)")

class AudioGenerationTool(BaseTool):
    name: str = "Audio Narration Generator"
    description: str = "Generates professional audio narration files based on CSV data and topic."
    args_schema: Type[BaseModel] = AudioGenerationToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        animation_styles: list,
        video_formats: list,
        audio_enabled: bool = False,
        audio_speed: float = 0.9
    ) -> str:
        # IMMEDIATE SKIP - zero overhead when disabled
        if not audio_enabled:
            return "🔇 Audio generation skipped (disabled in inputs)"

        # Check dependencies
        try:
            from gtts import gTTS
        except ImportError:
            return "⚠️ gTTS not installed. Run: pip install gTTS"

        if not self._ffmpeg_available():
            return "⚠️ ffmpeg not found. Install: sudo apt install ffmpeg"

            # 🔑 KEY: Get output_dir from inputs (passed from main.py)
        if not os.path.exists(output_dir):
            return f"âŒ Output directory '{output_dir}' not found"

        # 🔑 KEY: Get clean_filename from inputs (consistent across all tools)
        #clean_filename = getattr(self, '_inputs', {}).get('filename', 'ProgrammingLanguage')
        clean_filename = filename

        # Generate narration - CSV stays in flat output directory
        # Generate narration - CSV stays in flat output directory
        csv_path = f"output/{filename}.csv"
        narration = self._generate_narration(topic, csv_path)

        # 🔑 KEY: Save main narration as cc_en.txt (no prefix)
        main_text_path = f"{output_dir}/cc_en.txt"
        with open(main_text_path, 'w', encoding='utf-8') as f:
            f.write(narration)

        results = []
        processed = 0

        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        import glob
        # 🔑 KEY: Search all .mp4 files in subdirectory (style-based naming)
        actual_video_files = glob.glob(f"{output_dir}/*_*.mp4")
        # Filter out merged videos and audio files
        video_files = [f for f in actual_video_files if "_with_audio" not in f and "_audio" not in f]

        if not video_files:
            existing_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return f"⚠️ No videos found to generate audio for\n🔍 Existing videos: {', '.join(existing_files) if existing_files else 'None'}"

        styles = set()
        for vf in video_files:
            # Extract style from pattern like "bar_Shorts_bar_Shorts.mp4"
            parts = os.path.basename(vf).replace('.mp4', '').split('_')
            if len(parts) >= 2:
                style = parts[0]
                styles.add(style)

        # Save per-style narration files
        for style in styles:
            style_text_path = f"{output_dir}/{style}_cc_en.txt"
            with open(style_text_path, 'w', encoding='utf-8') as f:
                f.write(narration)

        for video_path in video_files:
            audio_path = video_path.replace('.mp4', '_audio.mp3')
            self._generate_audio(narration, audio_path, audio_speed)

            if os.path.exists(audio_path):
                results.append(os.path.basename(audio_path))
                processed += 1

        if processed == 0:
            return "⚠️ No videos found to generate audio for"

        return "🎵 Audio narration files created:\n" + "\n".join([f"   • {r}" for r in results]) + \
               f"\n\n📝 Main narration: cc_en.txt\n" + \
               f"   Per-style narration: {', '.join([f'{s}_cc_en.txt' for s in sorted(styles)])}\n" + \
               f"\nNarration preview: \"{narration[:70]}...\""

    def _generate_narration(self, topic: str, csv_path: str) -> str:
        """Generate professional narration following the specified format with dynamic CSV reading"""
        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)

                time_col = df.columns[0]
                data_cols = df.columns[1:]

                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])

                yearly_leaders = []
                for idx, row in df.iterrows():
                    leader = row[data_cols].idxmax()
                    value = row[leader]
                    year = int(row[time_col])
                    yearly_leaders.append((year, leader, value))

                narration_parts = [
                    "Welcome to @PlayOwnAi.",
                    f"Today, we're exploring {topic} Race from {start_year} to {end_year}.",
                    "Only for basic idea about trending",
                    "Let's see how the landscape evolved over time."
                ]

                for year, leader, value in yearly_leaders:
                    if value <= 20:
                        narration_parts.append(f"{year}. The market is forming.")
                    elif value <= 40:
                        narration_parts.append(f"{year}. {leader} gains traction.")
                    elif value <= 70:
                        narration_parts.append(f"{year}. {leader} shows strength.")
                    else:
                        narration_parts.append(f"{year}. {leader} leads the market.")

                final_year, final_leader, _ = yearly_leaders[-1]
                narration_parts.append(f"And in {final_year}, {final_leader} continues to lead.")
                narration_parts.append("The evolution of technology and trends continues.")
                narration_parts.append("Subscribe to @PlayOwnAi for more insights.")

                return " ".join(narration_parts)

            except Exception as e:
                print(f"⚠️ CSV reading failed: {e}")

        return (
            "Welcome to @PlayOwnAi. Today, we're exploring programming language trends. "
            "Let's see how the landscape evolved over time. "
            "The evolution of technology and trends continues. "
            "Subscribe to @PlayOwnAi for more insights."
        )

    def _generate_audio(self, text: str, output_path: str, speed: float):
        from gtts import gTTS
        import subprocess

        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        temp_path = output_path.replace('.mp3', '_temp.mp3')
        tts.save(temp_path)

        if abs(speed - 1.0) > 0.05:
            atempo = max(0.5, min(2.0, speed))
            subprocess.run([
                'ffmpeg', '-y', '-i', temp_path,
                '-filter:a', f'atempo={atempo}', output_path
            ], capture_output=True, check=False)
            if os.path.exists(temp_path):
                os.remove(temp_path)
        else:
            os.rename(temp_path, output_path)

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None
