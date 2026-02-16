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

        import re
        # Derive the base filename pattern from the input 'filename'
        # Input is "ProgrammingLanguage_bar_Shorts", we need "ProgrammingLanguage"
        base_filename_parts = filename.split('_')
        if base_filename_parts:
             base_filename_pattern = base_filename_parts[0] # Gets "ProgrammingLanguage"
        else:
             return f"❌ Could not derive base filename from input: {filename}"

        import glob
        # Find all video files matching the base filename pattern
        video_pattern = f"output/{base_filename_pattern}_*.mp4"
        print(f"[DEBUG] Merge Tool: Searching for videos with pattern: {video_pattern}")
        video_files = [f for f in glob.glob(video_pattern) if "_with_audio" not in f and "_audio" not in f]

        if not video_files:
             existing_videos = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
             warning_msg = f"⚠️ No video files found matching pattern '{video_pattern}'.\n🔍 Existing videos: {', '.join(existing_videos) if existing_videos else 'None'}"
             print(warning_msg)
             return warning_msg

        # Path to the image to append
        image_path = "data/Trends1024px.jpg"
        if not os.path.exists(image_path):
             print(f"⚠️ Image file not found: {image_path}, skipping image append")
             image_path = None  # Continue without image

        results = []
        processed = 0

        for video_path in video_files:
            # Construct corresponding audio path
            audio_path = video_path.replace('.mp4', '_audio.mp3')

            # Check if corresponding audio file exists
            if not os.path.exists(audio_path):
                warning_msg = f"⚠️ Missing audio: {os.path.basename(audio_path)} for {os.path.basename(video_path)}"
                print(warning_msg)
                results.append(warning_msg)
                continue

            # Construct output path for merged file
            final_path = video_path.replace('.mp4', '_with_audio.mp4')

            # Attempt merge (with or without image)
            if image_path:
                if self._merge_audio_video_and_append_image(video_path, audio_path, image_path, final_path):
                    success_msg = f"✅ Merged with image: {os.path.basename(final_path)}"
                    print(success_msg)
                    results.append(success_msg)
                    processed += 1
                else:
                    error_msg = f"❌ Failed merge with image: {os.path.basename(final_path)}"
                    print(error_msg)
                    results.append(error_msg)
            else:
                # Merge without image
                if self._merge_audio_video(video_path, audio_path, final_path):
                    success_msg = f"✅ Merged: {os.path.basename(final_path)}"
                    print(success_msg)
                    results.append(success_msg)
                    processed += 1
                else:
                    error_msg = f"❌ Failed merge: {os.path.basename(final_path)}"
                    print(error_msg)
                    results.append(error_msg)

        if processed == 0:
            error_msg = "⚠️ No successful merges performed.\n" + "\n".join(results)
            print(error_msg)
            return error_msg

        success_msg = f"🔄 Audio-video merging completed ({processed} successful).\n" + "\n".join(results)
        print(success_msg)
        return success_msg

    def _merge_audio_video_and_append_image(self, video_path: str, audio_path: str, image_path: str, output_path: str) -> bool:
        """Merges video and audio using ffmpeg, then appends an image."""
        try:
            # Step 1: Create a short video clip from the static image
            temp_image_video = output_path.replace('.mp4', '_temp_image_part.mp4')
            image_duration = 2.0  # Duration to show the image in seconds
            fps_from_original_video = self._get_fps(video_path) or 2.0

            # Create a video clip from the image lasting image_duration seconds
            subprocess.run([
                'ffmpeg', '-y', '-loop', '1', '-i', image_path,
                '-c:v', 'libx264', '-t', str(image_duration), '-pix_fmt', 'yuv420p',
                '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                '-r', str(fps_from_original_video),
                temp_image_video
            ], capture_output=True, check=True)

            # Step 2: First merge video + audio
            temp_video_with_audio = output_path.replace('.mp4', '_temp_with_audio.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                temp_video_with_audio
            ], capture_output=True, check=True)

            # Step 3: Concatenate the video+audio with the image video
            # 🔑 CRITICAL FIX: Use ABSOLUTE paths to avoid double path issues
            temp_concat_file = output_path.replace('.mp4', '_temp_concat_list.txt')
            abs_video_with_audio = os.path.abspath(temp_video_with_audio)
            abs_temp_image_video = os.path.abspath(temp_image_video)
            
            with open(temp_concat_file, 'w') as f:
                 f.write(f"file '{abs_video_with_audio}'\n")
                 f.write(f"file '{abs_temp_image_video}'\n")

            # Use ffmpeg concat demuxer to join them
            subprocess.run([
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0', '-i', temp_concat_file,
                '-c', 'copy',
                output_path
            ], capture_output=True, check=True)

            # Step 4: Cleanup temporary files
            for temp_file in [temp_image_video, temp_video_with_audio, temp_concat_file]:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

            return os.path.exists(output_path)
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg failed to merge video/audio and append image: {e.stderr.decode()}")
            # Cleanup on failure
            for temp_file in [output_path.replace('.mp4', '_temp_image_part.mp4'), 
                             output_path.replace('.mp4', '_temp_with_audio.mp4'),
                             output_path.replace('.mp4', '_temp_concat_list.txt')]:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            return False
        except Exception as e:
            print(f"❌ Unexpected error during merge/append: {e}")
            return False

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Simple merge without image append."""
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                output_path
            ], capture_output=True, check=True)
            return os.path.exists(output_path)
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg merge failed: {e.stderr.decode()}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error during merge: {e}")
            return False

    def _get_fps(self, video_path: str) -> float:
        """Helper to get FPS of a video file using ffprobe."""
        import subprocess
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', video_path
            ], capture_output=True, text=True, check=True)
            fps_str = result.stdout.strip()
            if '/' in fps_str:
                num, den = map(int, fps_str.split('/'))
                return float(num) / den if den != 0 else 2.0
            else:
                return float(fps_str) if fps_str else 2.0
        except subprocess.CalledProcessError:
            print(f"⚠️ Could not get FPS for {video_path}, using default.")
            return None