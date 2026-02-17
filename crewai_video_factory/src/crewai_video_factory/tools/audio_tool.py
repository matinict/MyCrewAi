import os
import shutil
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class AudioGenerationToolInput(BaseModel):
    """Input schema for AudioGenerationTool."""
    topic: str = Field(..., description="Topic/title for narration")
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
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
        animation_styles: list,
        video_formats: list,
        audio_enabled: bool = False,
        audio_speed: float = 0.9
    ) -> str:
        if not audio_enabled:
            return "🔇 Audio generation skipped (disabled in inputs)"

        try:
            from gtts import gTTS
        except ImportError:
            return "⚠️ gTTS not installed. Run: pip install gTTS"

        if not self._ffmpeg_available():
            return "⚠️ ffmpeg not found. Install: sudo apt install ffmpeg"

        # 🔑 FIX: Derive clean filename from topic (first 3 words, no spaces)
        import re
        clean_words = re.findall(r'\w+', topic)[:3]
        clean_filename = ''.join(clean_words)
        
        print(f"[DEBUG] Clean filename: {clean_filename} (from topic: {topic})")

        # 🔑 FIX: Scan output directory for ANY matching CSV, not just exact name
        output_dir = "output"
        csv_files = [f for f in os.listdir(output_dir) if f.endswith('.csv')]
        csv_path = None
        for cf in csv_files:
            if clean_filename.lower() in cf.lower():
                csv_path = os.path.join(output_dir, cf)
                break
        
        if not csv_path:
            # Fallback: use the most recent CSV
            csv_files = [os.path.join(output_dir, f) for f in csv_files]
            if csv_files:
                csv_path = max(csv_files, key=os.path.getctime)
        
        print(f"[DEBUG] Using CSV: {csv_path}")
        narration = self._generate_narration(topic, csv_path)

        # Save narration text file
        text_file_path = f"{output_dir}/{clean_filename}_Race_Narration_Full.txt"
        with open(text_file_path, 'w', encoding='utf-8') as f:
            f.write(narration)

        results = []
        processed = 0

        # 🔑 FIX: Scan for ANY video files matching the base filename pattern
        import glob
        video_pattern = f"{output_dir}/{clean_filename}_*.mp4"
        actual_video_files = glob.glob(video_pattern)
        
        # Filter out processed files
        video_files = [
            f for f in actual_video_files 
            if "_with_audio" not in f and "_audio" not in f
        ]
        
        print(f"[DEBUG] Found {len(video_files)} videos: {[os.path.basename(v) for v in video_files]}")

        if not video_files:
            # Fallback: list all mp4 files for debugging
            all_mp4 = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return f"⚠️ No videos found matching '{clean_filename}_*.mp4'\n🔍 Existing: {', '.join(all_mp4) if all_mp4 else 'None'}"

        for video_path in video_files:
            try:
                audio_path = video_path.replace('.mp4', '_audio.mp3')
                print(f"[DEBUG] Generating audio: {os.path.basename(audio_path)}")
                self._generate_audio(narration, audio_path, audio_speed)

                if os.path.exists(audio_path):
                    results.append(os.path.basename(audio_path))
                    processed += 1
                else:
                    results.append(f"❌ Failed: {os.path.basename(audio_path)}")
            except Exception as e:
                results.append(f"❌ Error: {e}")

        if processed == 0:
            return "⚠️ No audio files generated successfully"

        return "🎵 Audio files created:\n" + "\n".join([f"   • {r}" for r in results]) + \
               f"\n\n📋 Narration: {os.path.basename(text_file_path)}\n" + \
               f"Preview: \"{narration[:70]}...\""

    def _generate_narration(self, topic: str, csv_path: str) -> str:
        if csv_path and os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                time_col = df.columns[0]
                data_cols = df.columns[1:]
                years = df[time_col].tolist()
                start_year, end_year = int(years[0]), int(years[-1])
                
                yearly_leaders = []
                for _, row in df.iterrows():
                    leader = row[data_cols].idxmax()
                    value = row[leader]
                    year = int(row[time_col])
                    yearly_leaders.append((year, leader, value))
                
                parts = [
                    "Welcome to @PlayOwnAi.",
                    f"Today, we're exploring {topic} Race from {start_year} to {end_year}.",
                    "Only for basic idea about trending",
                    "Let's see how the landscape evolved over time."
                ]
                
                for year, leader, value in yearly_leaders:
                    if value <= 20:
                        parts.append(f"{year}. The market is forming.")
                    elif value <= 40:
                        parts.append(f"{year}. {leader} gains traction.")
                    elif value <= 70:
                        parts.append(f"{year}. {leader} shows strength.")
                    else:
                        parts.append(f"{year}. {leader} leads the market.")
                
                final_year, final_leader, _ = yearly_leaders[-1]
                parts.append(f"And in {final_year}, {final_leader} continues to lead.")
                parts.append("The evolution of technology and trends continues.")
                parts.append("Subscribe to @PlayOwnAi for more insights.")
                
                return " ".join(parts)
            except Exception as e:
                print(f"⚠️ CSV error: {e}")
        
        return f"Welcome to @PlayOwnAi. Today, we're exploring {topic}. The evolution of technology and trends continues. Subscribe to @PlayOwnAi for more insights."

    def _generate_audio(self, text: str, output_path: str, speed: float):
        from gtts import gTTS
        import subprocess
        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        temp_path = output_path.replace('.mp3', '_temp.mp3')
        tts.save(temp_path)
        
        if abs(speed - 1.0) > 0.05:
            atempo = max(0.5, min(2.0, speed))
            subprocess.run(['ffmpeg', '-y', '-i', temp_path, '-filter:a', f'atempo={atempo}', output_path], capture_output=True)
            if os.path.exists(temp_path):
                os.remove(temp_path)
        else:
            os.rename(temp_path, output_path)

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None