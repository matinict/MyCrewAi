import os
import shutil
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class AudioGenerationToolInput(BaseModel):
    """Input schema - ONLY needs these 3 parameters (ignores corrupted inputs)"""
    topic: str = Field(..., description="Original topic for narration context")
    audio_enabled: bool = Field(default=False, description="Enable/disable audio")
    audio_speed: float = Field(default=0.9, ge=0.7, le=1.3, description="Speech speed")

class AudioGenerationTool(BaseTool):
    name: str = "Audio Narration Generator"
    description: str = "Scans output/ directory and adds audio to ALL unprocessed videos"
    args_schema: Type[BaseModel] = AudioGenerationToolInput

    def _run(
        self,
        topic: str,
        audio_enabled: bool = False,
        audio_speed: float = 0.9
    ) -> str:
        # IMMEDIATE SKIP
        if not audio_enabled:
            return "🔇 Audio skipped (disabled in inputs)"
        
        # DEPENDENCY CHECKS
        try:
            from gtts import gTTS
        except ImportError:
            return "⚠️ gTTS not installed. Run: pip install gTTS"
        
        if not self._ffmpeg_available():
            return "⚠️ ffmpeg not found. Install: sudo apt install ffmpeg"
        
        output_dir = "output"
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"
        
        # 🔑 CRITICAL FIX: SCAN DIRECTORY INSTEAD OF TRUSTING CORRUPTED INPUTS
        video_files = [
            f for f in os.listdir(output_dir) 
            if f.endswith('.mp4') 
            and '_with_audio' not in f  # Skip already processed
            and '_audio' not in f       # Skip audio files
        ]
        
        if not video_files:
            existing = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            return (
                "⚠️ No UNPROCESSED videos found in output/\n"
                f"📁 All videos: {', '.join(existing) if existing else 'NONE'}\n"
                "💡 Tip: Videos must NOT contain '_with_audio' in filename"
            )
        
        # GET NARRATION (use FIRST CSV found for context)
        csv_files = [f for f in os.listdir(output_dir) if f.endswith('.csv')]
        csv_path = os.path.join(output_dir, csv_files[0]) if csv_files else None
        narration = self._generate_narration(topic, csv_path)
        
        # PROCESS ALL UNPROCESSED VIDEOS
        results = []
        for video_file in video_files:
            video_path = os.path.join(output_dir, video_file)
            base = os.path.splitext(video_file)[0]
            audio_path = os.path.join(output_dir, f"{base}_audio.mp3")
            final_path = os.path.join(output_dir, f"{base}_with_audio.mp4")
            
            try:
                self._generate_audio(narration, audio_path, audio_speed)
                if self._merge_audio_video(video_path, audio_path, final_path):
                    results.append(f"✅ {os.path.basename(final_path)}")
                else:
                    results.append(f"⚠️ {video_file}: merge failed")
            except Exception as e:
                results.append(f"❌ {video_file}: {str(e)}")
        
        success = [r for r in results if r.startswith('✅')]
        return (
            f"🎙️ Audio processing complete ({len(success)}/{len(video_files)} successful):\n" +
            "\n".join(results) +
            f"\n\nNarration: \"{narration[:60]}...\""
        )

    def _generate_narration(self, topic: str, csv_path: str) -> str:
        """Generate narration using CSV if available, else fallback"""
        if csv_path and os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                time_col = df.columns[0]
                data_cols = df.columns[1:6]
                start = df[time_col].iloc[0]
                end = df[time_col].iloc[-1]
                top = df.iloc[-1][data_cols].idxmax()
                return f"Tracking {topic} from {start} to {end}. {top} emerges as the leader. Watch the evolution."
            except:
                pass
        return f"Data visualization of {topic}. This animated chart reveals key trends and insights through dynamic storytelling."

    def _generate_audio(self, text: str, output_path: str, speed: float):
        from gtts import gTTS
        import subprocess
        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        temp = output_path.replace('.mp3', '_temp.mp3')
        tts.save(temp)
        if abs(speed - 1.0) > 0.05:
            atempo = max(0.5, min(2.0, speed))
            subprocess.run(['ffmpeg', '-y', '-i', temp, '-filter:a', f'atempo={atempo}', output_path], 
                         capture_output=True, check=False)
            if os.path.exists(temp): os.remove(temp)
        else:
            os.rename(temp, output_path)

    def _ffmpeg_available(self) -> bool:
        return shutil.which('ffmpeg') is not None

    def _merge_audio_video(self, video: str, audio: str, output: str) -> bool:
        import subprocess
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video, '-i', audio,
                '-c:v', 'copy', '-c:a', 'aac', '-shortest', output
            ], capture_output=True, check=True)
            return os.path.exists(output)
        except:
            return False