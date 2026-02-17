import os
import subprocess
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class MergeAudioVideoToolInput(BaseModel):
    filename: str = Field(..., description="Base filename")
    audio_speed: float = Field(default=0.9)

class MergeAudioVideoTool(BaseTool):
    name: str = "Merge Audio Video Tool"
    description: str = "Merges MP4 videos with MP3 audio files"
    args_schema: Type[BaseModel] = MergeAudioVideoToolInput

    def _run(self, filename: str, audio_speed: float = 0.9) -> str:
        output_dir = "output"
        if not os.path.exists(output_dir):
            return f"❌ Output directory not found"

        # 🔑 FIX: Extract base filename (first part before first underscore)
        import re
        base_name = filename.split('_')[0] if '_' in filename else filename
        print(f"[DEBUG] Merge: base_name={base_name}, input filename={filename}")

        import glob
        # Search for videos matching base pattern
        video_pattern = f"{output_dir}/{base_name}_*.mp4"
        video_files = [f for f in glob.glob(video_pattern) if "_with_audio" not in f and "_audio" not in f]
        
        print(f"[DEBUG] Found videos: {[os.path.basename(v) for v in video_files]}")

        results = []
        processed = 0

        for video_path in video_files:
            audio_path = video_path.replace('.mp4', '_audio.mp3')
            
            if not os.path.exists(audio_path):
                results.append(f"⚠️ Missing audio: {os.path.basename(audio_path)}")
                continue

            final_path = video_path.replace('.mp4', '_with_audio.mp4')
            
            if self._merge_audio_video(video_path, audio_path, final_path):
                results.append(f"✅ Merged: {os.path.basename(final_path)}")
                processed += 1
            else:
                results.append(f"❌ Failed: {os.path.basename(final_path)}")

        if processed == 0:
            return "⚠️ No successful merges\n" + "\n".join(results)

        return f"🔄 Merged {processed} file(s)\n" + "\n".join(results)

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                output_path
            ], capture_output=True, check=True)
            return os.path.exists(output_path)
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg error: {e.stderr.decode()}")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False