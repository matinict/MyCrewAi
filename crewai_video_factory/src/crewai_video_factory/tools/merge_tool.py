import os
import subprocess
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class MergeAudioVideoToolInput(BaseModel):
    """Input schema for MergeAudioVideoTool."""
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
    output_dir: str = Field(..., description="Output directory for merged files")
    audio_speed: float = Field(default=0.9, ge=0.7, le=1.3, description="Speech speed used for audio generation (info only)")

class MergeAudioVideoTool(BaseTool):
    name: str = "Merge Audio Video Tool"
    description: str = "Merges existing MP4 video files with corresponding MP3 audio files to create final MP4 files."
    args_schema: Type[BaseModel] = MergeAudioVideoToolInput

    def _run(
        self,
        filename: str,
        output_dir: str,
        audio_speed: float = 0.9
    ) -> str:
        # 🔑 KEY: Use parameters passed directly
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        # 🔍 DEBUG: List files in directory
        print(f"\n🔍 DEBUG: Merge Tool Starting")
        print(f"   Output dir: {output_dir}")
        if os.path.exists(output_dir):
            all_files = os.listdir(output_dir)
            print(f"   Files in directory: {all_files}")
        
        import glob
        
        # 🔑 KEY: Search all .mp4 files in subdirectory (style-based naming: bar_Shorts_bar_Shorts.mp4)
        all_videos = glob.glob(f"{output_dir}/*.mp4")
        
        # Filter: only base videos (exclude merged & audio files)
        video_files = [
            f for f in all_videos 
            if "_with_audio" not in f and "_audio" not in f
        ]

        print(f"   Found {len(video_files)} videos to process")

        results = []
        processed = 0

        for video_path in video_files:
            # Extract video filename and create matching audio filename
            # Example: bar_Shorts_bar_Shorts.mp4 → bar_Shorts_bar_Shorts_audio.mp3
            video_basename = os.path.basename(video_path)
            audio_basename = video_basename.replace('.mp4', '_audio.mp3')
            audio_path = os.path.join(output_dir, audio_basename)

            print(f"\n   Processing: {video_basename}")
            print(f"   Looking for audio: {audio_basename}")

            if not os.path.exists(audio_path):
                results.append(f"⚠️ Missing audio: {audio_basename}")
                print(f"   ❌ Audio file not found!")
                continue

            # Create merged output: bar_Shorts_bar_Shorts_with_audio.mp4
            merged_basename = video_basename.replace('.mp4', '_with_audio.mp4')
            final_path = os.path.join(output_dir, merged_basename)

            print(f"   Creating: {merged_basename}")

            if self._merge_audio_video(video_path, audio_path, final_path):
                results.append(f"✅ Merged: {merged_basename}")
                processed += 1
            else:
                results.append(f"❌ Failed merge: {merged_basename}")

        if processed == 0:
            return "⚠️ No successful merges performed.\n" + "\n".join(results)

        return f"📹 Audio-video merging completed ({processed} successful).\n" + "\n".join(results)

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Merges video and audio using ffmpeg."""
        try:
            result = subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                output_path
            ], capture_output=True, text=True, check=True)
            
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"      ✅ Merged successfully ({file_size} bytes)")
                return True
            else:
                print(f"      ❌ Output file not created")
                return False
                
        except subprocess.CalledProcessError as e:
            print(f"      ❌ FFmpeg merge failed:")
            print(f"         Error: {e.stderr[:100]}")
            return False
        except Exception as e:
            print(f"      ❌ Unexpected error: {e}")
            return False