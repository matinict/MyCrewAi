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
    description: str = "Generates professional audio narration and merges with existing videos"
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
        # IMMEDIATE SKIP - zero overhead when disabled
        if not audio_enabled:
            return "🔇 Audio skipped (disabled in inputs)"
        
        # Check dependencies
        try:
            from gtts import gTTS
        except ImportError:
            return "⚠️ gTTS not installed. Run: pip install gTTS"
        
        if not self._ffmpeg_available():
            return "⚠️ ffmpeg not found. Install: sudo apt install ffmpeg"
        
        # 🔑 CRITICAL FIX: CLEAN UP CORRUPTED INPUTS FROM CREWAI
        import re
        # Extract clean filename (first 3 words of topic)
        clean_words = re.findall(r'\w+', topic)[:3]
        clean_filename = ''.join(clean_words)
        
        # Generate narration
        csv_path = f"output/{clean_filename}.csv"
        narration = self._generate_narration(topic, csv_path)
        
        # CREATE NARRATION TEXT FILE
        text_file_path = f"output/{clean_filename}_Race_Narration_Full.txt"
        with open(text_file_path, 'w', encoding='utf-8') as f:
            f.write(narration)
        
        results = []
        processed = 0
        
        # 🔑 CRITICAL FIX: SCAN DIRECTORY FOR ACTUAL VIDEO FILES (BYPASSES CORRUPTED INPUTS)
        output_dir = "output"
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"
        
        # Look for video files that match the actual naming pattern
        import glob
        # Find all video files matching the actual filename pattern
        actual_video_files = glob.glob(f"output/{clean_filename}_*.mp4")
        
        # Filter out audio and already processed files
        video_files = [
            f for f in actual_video_files 
            if "_with_audio" not in f and "_audio" not in f
        ]
        
        if not video_files:
            existing_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return f"⚠️ No videos found to add audio to\n🔍 Existing videos: {', '.join(existing_files) if existing_files else 'None'}"
        
        # Process all found video files
        for video_path in video_files:
            # Generate audio file
            audio_path = video_path.replace('.mp4', '_audio.mp3')
            self._generate_audio(narration, audio_path, audio_speed)
            
            # Merge with video
            final_path = video_path.replace('.mp4', '_with_audio.mp4')
            if self._merge_audio_video(video_path, audio_path, final_path):
                results.append(os.path.basename(final_path))
                processed += 1
        
        if processed == 0:
            return "⚠️ No videos found to add audio to"
        
        return "🎙️ Audio narration added:\n" + "\n".join([f"   • {r}" for r in results]) + \
               f"\n\n📋 Narration saved to: {os.path.basename(text_file_path)}\n" + \
               f"\nNarration preview: \"{narration[:70]}...\""

    def _generate_narration(self, topic: str, csv_path: str) -> str:
        """Generate professional narration following the specified format with dynamic CSV reading"""
        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                
                # Get time column (first column) and data columns
                time_col = df.columns[0]
                data_cols = df.columns[1:]
                
                # Extract years and find top performers
                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])
                
                # Find the leader for each year
                yearly_leaders = []
                for idx, row in df.iterrows():
                    leader = row[data_cols].idxmax()
                    value = row[leader]
                    year = int(row[time_col])
                    yearly_leaders.append((year, leader, value))
                
                # Build narration following your exact format
                narration_parts = [
                    "Welcome to @PlayOwnAi.",
                    f"Today, we're exploring {topic} Race from {start_year} to {end_year}.",
                    "Only for basic idea about trending",
                    "Let's see how the landscape evolved over time."
                ]
                
                # Add yearly updates showing who leads each year
                for year, leader, value in yearly_leaders:
                    if value <= 20:
                        narration_parts.append(f"{year}. The market is forming.")
                    elif value <= 40:
                        narration_parts.append(f"{year}. {leader} gains traction.")
                    elif value <= 70:
                        narration_parts.append(f"{year}. {leader} shows strength.")
                    else:
                        narration_parts.append(f"{year}. {leader} leads the market.")
                
                # Add final conclusion based on last year's leader
                final_year, final_leader, final_value = yearly_leaders[-1]
                narration_parts.append(f"And in {final_year}, {final_leader} continues to lead.")
                
                narration_parts.append("The evolution of technology and trends continues.")
                narration_parts.append("Subscribe to @PlayOwnAi for more insights.")
                
                return " ".join(narration_parts)
                
            except Exception as e:
                # Fallback generic narration if CSV processing fails
                pass
        
        # Generic fallback if CSV processing fails
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
        
        # Apply speed control
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

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        import subprocess
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac', '-shortest', output_path
            ], capture_output=True, check=True)
            return os.path.exists(output_path)
        except:
            return False