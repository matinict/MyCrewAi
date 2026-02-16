import os
import shutil
import traceback # Import traceback for detailed error logging
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
        print(f"[DEBUG] Audio Tool started with topic: {topic[:30]}..., filename: {filename}") # Debug log

        # IMMEDIATE SKIP - zero overhead when disabled
        if not audio_enabled:
            print("[INFO] Audio generation skipped (disabled in inputs)") # Info log
            return "🔇 Audio generation skipped (disabled in inputs)"

        # Check dependencies
        try:
            from gtts import gTTS
        except ImportError as e:
            error_msg = f"❌ gTTS not installed. Run: pip install gTTS. Error: {e}"
            print(error_msg) # Log error
            return error_msg

        if not self._ffmpeg_available():
            error_msg = "❌ ffmpeg not found. Install: sudo apt install ffmpeg (Linux) or brew install ffmpeg (macOS)"
            print(error_msg) # Log error
            return error_msg

        # 🔑 CRITICAL FIX: CLEAN UP CORRUPTED INPUTS FROM CREWAI
        import re
        # Extract clean filename (first 3 words of topic) - More robust fallback
        clean_words = re.findall(r'\w+', topic)[:3]
        clean_filename_from_topic = ''.join(clean_words)
        # Use the filename from input, but fall back to the one derived from topic if it seems invalid
        clean_filename = clean_filename_from_topic if not re.match(r'^[\w]+$', filename) else filename
        print(f"[DEBUG] Derived clean filename: {clean_filename} (from topic: {clean_filename_from_topic}, original: {filename})") # Debug log

        # Generate narration
        csv_path = f"output/{clean_filename}.csv"
        print(f"[DEBUG] Attempting to read CSV: {csv_path}") # Debug log
        narration = self._generate_narration(topic, csv_path)

        # CREATE NARRATION TEXT FILE
        text_file_path = f"output/{clean_filename}_Race_Narration_Full.txt"
        print(f"[DEBUG] Writing narration text to: {text_file_path}") # Debug log
        try:
            with open(text_file_path, 'w', encoding='utf-8') as f:
                f.write(narration)
            print(f"[INFO] Narration text saved to: {text_file_path}") # Info log
        except IOError as e:
            error_msg = f"❌ Failed to write narration text file {text_file_path}: {e}"
            print(error_msg) # Log error
            return error_msg

        results = []
        processed = 0

        # 🔑 CRITICAL FIX: SCAN DIRECTORY FOR ACTUAL VIDEO FILES (BYPASSES CORRUPTED INPUTS)
        output_dir = "output"
        if not os.path.exists(output_dir):
            error_msg = f"❌ Output directory '{output_dir}' not found"
            print(error_msg) # Log error
            return error_msg

        # Look for video files that match the actual naming pattern
        import glob
        # Find all video files matching the actual filename pattern
        video_pattern = f"output/{clean_filename}_*.mp4"
        print(f"[DEBUG] Scanning for video files with pattern: {video_pattern}") # Debug log
        actual_video_files = glob.glob(video_pattern)

        # Filter out audio and already processed files
        video_files = [
            f for f in actual_video_files
            if "_with_audio" not in f and "_audio" not in f
        ]
        print(f"[DEBUG] Found {len(video_files)} video files to process: {video_files}") # Debug log

        if not video_files:
            existing_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            warning_msg = f"⚠️ No videos found to generate audio for\n🔍 Existing videos matching pattern '{video_pattern}': {', '.join(existing_files) if existing_files else 'None'}"
            print(warning_msg) # Log warning
            return warning_msg

        # Process all found video files - ONLY generate audio
        for video_path in video_files:
            try:
                print(f"[DEBUG] Processing video: {video_path}") # Debug log
                # Generate audio file
                audio_path = video_path.replace('.mp4', '_audio.mp3')
                print(f"[DEBUG] Generating audio file: {audio_path}") # Debug log
                self._generate_audio(narration, audio_path, audio_speed)

                # Verify if audio file was created successfully
                if os.path.exists(audio_path):
                    print(f"[INFO] Successfully created audio file: {audio_path}") # Info log
                    # Add generated audio file path to results
                    results.append(os.path.basename(audio_path))
                    processed += 1
                else:
                    error_msg = f"❌ Failed to create audio file: {audio_path} (file not found after generation)"
                    print(error_msg) # Log error
                    results.append(error_msg)
            except Exception as e:
                error_msg = f"❌ Error processing video {video_path}: {e}\nTraceback: {traceback.format_exc()}"
                print(error_msg) # Log detailed error
                results.append(error_msg)

        if processed == 0:
            error_msg = "⚠️ No videos found to generate audio for or all attempts failed"
            print(error_msg) # Log error
            return error_msg

        success_msg = "🎵 Audio narration files created:\n" + "\n".join([f"   • {r}" for r in results]) + \
               f"\n\n📋 Narration saved to: {os.path.basename(text_file_path)}\n" + \
               f"\nNarration preview: \"{narration[:70]}...\""
        print(f"[INFO] Audio Tool completed successfully. Processed {processed} files.") # Info log
        return success_msg


    def _generate_narration(self, topic: str, csv_path: str) -> str:
        """Generate professional narration following the specified format with dynamic CSV reading"""
        print(f"[DEBUG] Attempting to read CSV for narration: {csv_path}") # Debug log
        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                print(f"[DEBUG] CSV read successfully. Shape: {df.shape}") # Debug log

                # Get time column (first column) and data columns
                time_col = df.columns[0]
                data_cols = df.columns[1:]

                # Extract years and find top performers
                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])
                print(f"[DEBUG] CSV time range: {start_year} to {end_year}") # Debug log

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

                narration_text = " ".join(narration_parts)
                print(f"[DEBUG] Narration generated, length: {len(narration_text)} chars") # Debug log
                return narration_text

            except Exception as e:
                error_msg = f"⚠️ CSV reading failed: {e}\nTraceback: {traceback.format_exc()}" # Include traceback
                print(error_msg) # Log error

        # Generic fallback if CSV processing fails
        fallback_text = (
            "Welcome to @PlayOwnAi. Today, we're exploring programming language trends. "
            "Let's see how the landscape evolved over time. "
            "The evolution of technology and trends continues. "
            "Subscribe to @PlayOwnAi for more insights."
        )
        print("[DEBUG] Using fallback narration") # Debug log
        return fallback_text

    def _generate_audio(self, text: str, output_path: str, speed: float):
        print(f"[DEBUG] Starting audio generation for file: {output_path}, speed: {speed}") # Debug log
        from gtts import gTTS
        import subprocess

        tts = gTTS(text=text, lang='en', slow=(speed <= 0.85))
        temp_path = output_path.replace('.mp3', '_temp.mp3')
        print(f"[DEBUG] Saving initial TTS to temp file: {temp_path}") # Debug log
        tts.save(temp_path)
        print(f"[DEBUG] Initial TTS saved, size: {os.path.getsize(temp_path)} bytes") # Debug log

        # Apply speed control using ffmpeg
        if abs(speed - 1.0) > 0.05:
            print(f"[DEBUG] Applying speed adjustment using ffmpeg, target speed: {speed}") # Debug log
            atempo = max(0.5, min(2.0, speed))
            try:
                result = subprocess.run([
                    'ffmpeg', '-y', '-i', temp_path,
                    '-filter:a', f'atempo={atempo}', output_path
                ], capture_output=True, check=True)
                print(f"[DEBUG] FFmpeg speed adjustment completed. Stdout: {result.stdout.decode()[:100]}") # Log first 100 chars
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] FFmpeg speed adjustment failed. Stderr: {e.stderr.decode()}") # Log error details
                raise # Re-raise to be caught by caller
            except Exception as e:
                print(f"[ERROR] Unexpected error during FFmpeg speed adjustment: {e}") # Log error
                raise # Re-raise to be caught by caller
        else:
            print(f"[DEBUG] Speed is 1.0x, renaming temp file directly to output: {output_path}") # Debug log
            os.rename(temp_path, output_path)

        # Cleanup temp file if it still exists (e.g., if speed was 1.0x)
        if os.path.exists(temp_path):
            print(f"[DEBUG] Removing temporary file: {temp_path}") # Debug log
            os.remove(temp_path)

        print(f"[DEBUG] Audio generation completed for: {output_path}") # Debug log

    def _ffmpeg_available(self) -> bool:
        available = shutil.which('ffmpeg') is not None
        print(f"[DEBUG] FFmpeg available check: {available}") # Debug log
        return available
