import os
import subprocess
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class MergeAudioVideoToolInput(BaseModel):
    """Input schema for MergeAudioVideoTool."""
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
    audio_speed: float = Field(default=0.9, ge=0.7, le=1.3, description="Speech speed used for audio generation (info only)")

class MergeAudioVideoTool(BaseTool):
    name: str = "Merge Audio Video Tool"
    description: str = "Merges existing MP4 video files with corresponding MP3 audio files to create final MP4 files."
    args_schema: Type[BaseModel] = MergeAudioVideoToolInput

    def _run(
        self,
        filename: str,
        audio_speed: float = 0.9
    ) -> str:
        output_dir = "output"
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        # 🔑 FIX: Extract base filename (first part before first underscore)
        import re
        base_name = filename.split('_')[0] if '_' in filename else filename

        import glob
        video_pattern = f"output/{base_name}_*.mp4"
        video_files = [f for f in glob.glob(video_pattern) if "_with_audio" not in f and "_audio" not in f]

        results = []
        processed = 0

        for video_path in video_files:
            audio_path = video_path.replace('.mp4', '_audio.mp3')

            if not os.path.exists(audio_path):
                results.append(f"⚠️ Missing audio: {os.path.basename(audio_path)} for {os.path.basename(video_path)}")
                continue

            final_path = video_path.replace('.mp4', '_with_audio.mp4')

            if self._merge_audio_video(video_path, audio_path, final_path):
                results.append(f"✅ Merged: {os.path.basename(final_path)}")
                processed += 1
            else:
                results.append(f"❌ Failed merge: {os.path.basename(final_path)}")

        if processed == 0:
            return "⚠️ No successful merges performed.\n" + "\n".join(results)

        return f"🔄 Audio-video merging completed ({processed} successful).\n" + "\n".join(results)

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Merges video and audio using ffmpeg."""
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                output_path
            ], capture_output=True, check=True)
            return os.path.exists(output_path)
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg merge failed for {video_path} and {audio_path}: {e.stderr.decode()}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error during merge for {video_path} and {audio_path}: {e}")
            return False