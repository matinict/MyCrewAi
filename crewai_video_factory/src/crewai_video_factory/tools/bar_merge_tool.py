import os
import glob
import subprocess
import tempfile
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class BarMergeToolInput(BaseModel):
    """Input schema for BarMergeTool."""
    output_dir: str = Field(..., description="Output directory containing bar race videos, intro clips, and audio files")
    video_formats: list = Field(..., description="List of video formats to process (e.g. ['Shorts', 'HD'])")
    bar_merge_enabled: bool = Field(default=False, description="Whether to run bar merge (intro + bar race + audio)")


class BarMergeTool(BaseTool):
    """
    Merges intro clip + bar race video + bar race audio into one final MP4.

    Pipeline per format:
      1. intro_[format].mp4
           +
         bar_race_[format].mp4
           ↓  ffmpeg concat
         [temp] combined_[format].mp4
           +
         bar_race_[format]_audio.mp3
           ↓  ffmpeg merge
         Merge_bar_race_[format].mp4   ← final output

    All files are read from / written to output_dir.
    Triggered by bar_merge_enabled=true in data.json.
    """
    name: str = "Bar Merge Tool"
    description: str = (
        "Concatenates intro clip and bar race video, then merges with bar race audio "
        "to produce a single final MP4 per video format. "
        "Triggered by bar_merge_enabled=true."
    )
    args_schema: Type[BaseModel] = BarMergeToolInput

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _run(
        self,
        output_dir: str,
        video_formats: list,
        bar_merge_enabled: bool = False,
    ) -> str:

        # --- IMMEDIATE SKIP ---
        if not bar_merge_enabled:
            return "⏭️  Bar merge skipped (bar_merge_enabled=false)"

        # --- DEPENDENCY CHECK ---
        if not self._ffmpeg_available():
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        # --- VALIDATE OUTPUT DIR ---
        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        print(f"\n🔍 DEBUG: BarMergeTool Starting")
        print(f"   output_dir : {output_dir}")
        print(f"   video_formats: {video_formats}")
        print(f"   Files present: {os.listdir(output_dir)}")

        results = []
        errors = []
        processed = 0

        for fmt in video_formats:
            print(f"\n--- Processing format: {fmt} ---")

            intro_path    = os.path.join(output_dir, f"intro_{fmt}.mp4")
            bar_vid_path  = os.path.join(output_dir, f"bar_race_{fmt}.mp4")
            audio_path    = os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3")
            final_path    = os.path.join(output_dir, f"Merge_bar_race_{fmt}.mp4")

            # --- FILE EXISTENCE CHECKS ---
            missing = []
            if not os.path.exists(intro_path):
                missing.append(f"intro_{fmt}.mp4")
            if not os.path.exists(bar_vid_path):
                missing.append(f"bar_race_{fmt}.mp4")
            if not os.path.exists(audio_path):
                missing.append(f"bar_race_{fmt}_audio.mp3")

            if missing:
                msg = f"⚠️  [{fmt}] Missing files: {', '.join(missing)} — skipping"
                print(f"   {msg}")
                errors.append(msg)
                continue

            print(f"   ✅ intro     : {os.path.basename(intro_path)}")
            print(f"   ✅ bar video : {os.path.basename(bar_vid_path)}")
            print(f"   ✅ audio     : {os.path.basename(audio_path)}")

            # --- STEP 1: CONCAT intro + bar race video ---
            with tempfile.NamedTemporaryFile(
                suffix=f"_combined_{fmt}.mp4", delete=False, dir=output_dir
            ) as tmp:
                combined_path = tmp.name

            print(f"   ⏳ Step 1 — Concatenating intro + bar race video …")
            ok, err = self._concat_videos(intro_path, bar_vid_path, combined_path)
            if not ok:
                msg = f"❌ [{fmt}] Concat failed: {err}"
                print(f"   {msg}")
                errors.append(msg)
                self._cleanup(combined_path)
                continue

            size_mb = os.path.getsize(combined_path) / (1024 * 1024)
            print(f"   ✅ Combined video: {size_mb:.1f} MB")

            # --- STEP 2: MERGE combined video + audio ---
            print(f"   ⏳ Step 2 — Merging audio into combined video …")
            ok, err = self._merge_audio_video(combined_path, audio_path, final_path)
            self._cleanup(combined_path)

            if not ok:
                msg = f"❌ [{fmt}] Audio merge failed: {err}"
                print(f"   {msg}")
                errors.append(msg)
                continue

            size_mb = os.path.getsize(final_path) / (1024 * 1024)
            msg = f"✅ Merge_bar_race_{fmt}.mp4 ({size_mb:.1f} MB)"
            print(f"   {msg}")
            results.append(msg)
            processed += 1

        # --- SUMMARY ---
        if processed == 0:
            summary = "❌ Bar merge failed for all formats.\n"
            if errors:
                summary += "Errors:\n" + "\n".join(f"  • {e}" for e in errors)
            return summary

        summary = (
            f"🎬 Bar merge completed ({processed}/{len(video_formats)} formats).\n"
            + "\n".join(f"   • {r}" for r in results)
        )
        if errors:
            summary += "\n\n⚠️  Some formats had errors:\n" + "\n".join(f"  • {e}" for e in errors)
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _concat_videos(self, intro_path: str, bar_path: str, output_path: str):
        """
        Concatenate two MP4 files using ffmpeg concat demuxer.
        Both clips are re-encoded to a common stream so mismatched
        resolutions / pixel formats are handled gracefully.
        Returns (success: bool, error_msg: str).
        """
        # Write a temporary concat list file
        list_path = output_path + "_concat_list.txt"
        try:
            with open(list_path, "w") as f:
                f.write(f"file '{os.path.abspath(intro_path)}'\n")
                f.write(f"file '{os.path.abspath(bar_path)}'\n")

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_path,
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    output_path,
                ],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0 or not os.path.exists(output_path):
                return False, result.stderr[-300:]
            return True, ""
        except Exception as e:
            return False, str(e)
        finally:
            self._cleanup(list_path)

    def _merge_audio_video(self, video_path: str, audio_path: str, output_path: str):
        """
        Merge a video file with an external audio track.
        Video stream is copied; audio is re-encoded to AAC.
        Audio is truncated / padded to match video duration automatically.
        Returns (success: bool, error_msg: str).
        """
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-map", "0:v:0",       # video from first input
                    "-map", "1:a:0",       # audio from second input
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",           # trim to shortest stream
                    "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart",
                    output_path,
                ],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0 or not os.path.exists(output_path):
                return False, result.stderr[-300:]
            return True, ""
        except Exception as e:
            return False, str(e)

    def _ffmpeg_available(self) -> bool:
        import shutil
        return shutil.which("ffmpeg") is not None

    def _cleanup(self, path: str):
        """Silently remove a temporary file if it exists."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
