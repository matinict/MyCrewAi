"""
Debate Merge Tool (FINAL - v2.3)
Concatenates intro + debate video segments WITH AUDIO using pure stream-copy (no re-encoding):
  intro_{fmt}_with_audio.mp4 +
  debate_video_{fmt}_with_audio.mp4
    → PlayOwnAi_Debate_AI_Replace_Entry_Level_{fmt}.mp4

Also merges CC text files and auto-cleans up intermediates.
Uses ffmpeg concat demuxer with -reset_timestamps 1 for timestamp continuity.
CLEANUP: Deletes ALL intro/debate files including originals (keeps only .md files)
"""
import os
import shutil
import subprocess
from crewai.tools import BaseTool
from typing import Type, List, Optional
from pydantic import BaseModel, Field
import glob


class DebateMergeToolInput(BaseModel):
    """Input schema for DebateMergeTool."""
    output_dir: Optional[str] = Field(default=None, description="Output directory containing segment videos and CC files")
    video_formats: List[str] = Field(..., description="List of video formats (HD, Shorts, etc.)")
    debate_merge_enabled: bool = Field(default=False, description="Whether to run debate merge")
    channel: str = Field(default="PlayOwnAi", description="Channel name for final filename")
    topic: str = Field(default="", description="Topic name (for reference only)")


class DebateMergeTool(BaseTool):
    """
    Concatenates intro + debate video WITH AUDIO using pure stream-copy (no re-encoding):
      intro_{fmt}_with_audio.mp4 + debate_video_{fmt}_with_audio.mp4
        → PlayOwnAi_Debate_AI_Replace_Entry_Level_{fmt}.mp4

    AUTO-DETECTS output directory from existing segment files if not provided.
    CLEANUP: Deletes ALL intro/debate files (originals + intermediates), keeps only .md files
    """
    name: str = "Debate Merge Tool"
    description: str = (
        "Concatenates intro + debate video WITH AUDIO using pure stream-copy (no re-encoding).  "
        "Output: PlayOwnAi_Debate_AI_Replace_Entry_Level_{fmt}.mp4 + CC file per format.  "
        "Auto-detects output_dir from existing segment files.  "
        "CLEANUP: Deletes ALL intro/debate files (originals + intermediates), preserves .md files only.  "
        "Triggered by debate_merge_enabled=true. "
    )
    args_schema: Type[BaseModel] = DebateMergeToolInput

    def _find_output_dir(self) -> Optional[str]:
        """
        Auto-detect output directory by searching for intro_*.mp4 files.
        Searches in common locations.
        """
        search_paths = [
            "output",
            "output/AIReplaceEntry",
            "./output",
            "../output",
            ".",
        ]

        for search_path in search_paths:
            if os.path.exists(search_path):
                for item in os.listdir(search_path):
                    item_path = os.path.join(search_path, item)
                    if os.path.isdir(item_path):
                        # Check if this directory has intro_*.mp4 files
                        intro_files = glob.glob(os.path.join(item_path, "intro_*.mp4"))
                        if intro_files:
                            print(f"[DebateMerge] 🔍 Auto-detected output dir: {item_path}")
                            return item_path

        # Try direct paths
        for path in search_paths:
            intro_files = glob.glob(os.path.join(path, "intro_*.mp4"))
            if intro_files:
                print(f"[DebateMerge] 🔍 Auto-detected output dir: {path}")
                return path

        return None

    def _run(
        self,
        output_dir: Optional[str] = None,
        video_formats: List[str] = None,
        debate_merge_enabled: bool = False,
        channel: str = "PlayOwnAi",
        topic: str = "",
    ) -> str:
        if video_formats is None:
            video_formats = ["Shorts"]

        if not debate_merge_enabled:
            return "🔇 Debate merge skipped (debate_merge_enabled=false)"

        # AUTO-DETECT output_dir if empty
        if not output_dir or output_dir == "" or output_dir == "output_directory":
            print("[DebateMerge] ⚠️  output_dir is empty or placeholder — attempting auto-detection...")
            output_dir = self._find_output_dir()
            if not output_dir:
                return "❌ Output directory not found. Ensure segment files exist in output/ subdirectory"

        if not shutil.which('ffmpeg'):
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        print(f"[DebateMerge] Starting pure stream-copy merge")
        print(f"[DebateMerge] Output dir: {output_dir}")
        print(f"[DebateMerge] Formats: {video_formats}")

        results = []
        errors = []
        cleanup_count = 0

        for fmt in video_formats:
            fmt = fmt.strip()

            # ✅ OUTPUT FILES WITH FINAL YOUTUBE-READY NAMES
            final_video = os.path.join(output_dir, f"PlayOwnAi_Debate_AI_Replace_Entry_Level_{fmt}.mp4")
            final_cc    = os.path.join(output_dir, f"PlayOwnAi_Debate_AI_Replace_Entry_Level_{fmt}_cc_en.txt")

            # ✅ SMART SKIP: Check if FINAL merged video already exists
            if os.path.exists(final_video):
                results.append(f"⏭️ {fmt}: Skipped (final video exists)")
                print(f"[DebateMerge] ⏭️ {fmt}: Final video exists — skipping")
                continue

            # ✅ SEGMENT DEFINITIONS
            segments = [
                ("intro",          f"intro_{fmt}_with_audio.mp4",         f"intro_{fmt}_cc_en.txt"),
                ("debate_video",   f"debate_video_{fmt}_with_audio.mp4",  f"debate_video_{fmt}_cc_en.txt"),
            ]

            # ── STEP 1: VERIFY ALL SEGMENT FILES EXIST ───────────────────────
            video_paths = []
            cc_contents = []
            missing_files = []

            for seg_name, vid_file, cc_file in segments:
                vid_path = os.path.join(output_dir, vid_file)
                cc_path  = os.path.join(output_dir, cc_file)

                if not os.path.exists(vid_path):
                    missing_files.append(vid_file)
                else:
                    video_paths.append(vid_path)

                if os.path.exists(cc_path):
                    with open(cc_path, 'r', encoding='utf-8', errors='ignore') as f:
                        cc_contents.append(f.read())

            if missing_files:
                errors.append(f"❌ {fmt}: Missing {', '.join(missing_files)}")
                continue

            if len(video_paths) < 2:
                errors.append(f"❌ {fmt}: Need 2 videos, got {len(video_paths)}")
                continue

            # ── STEP 2: MERGE CC FILES ───────────────────────────────────────
            if cc_contents:
                try:
                    merged_cc = "\n".join(cc_contents).strip()
                    with open(final_cc, 'w', encoding='utf-8') as f:
                        f.write(merged_cc)
                    print(f"[DebateMerge] ✅ {fmt}: CC file merged")
                except Exception as e:
                    print(f"[DebateMerge] ⚠️  {fmt}: CC merge failed: {e}")

            # ── STEP 3: PROBE SEGMENTS ───────────────────────────────────────
            print(f"[DebateMerge] 🔍 {fmt}: Probing compatibility...")
            for vp in video_paths:
                probe_cmd = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_name,width,height,r_frame_rate,pix_fmt',
                    '-of', 'csv=p=0', vp
                ]
                probe = subprocess.run(probe_cmd, capture_output=True, text=True)
                if probe.stdout:
                    print(f"[DebateMerge]   {os.path.basename(vp)}: {probe.stdout.strip()}")

            # ── STEP 4: CREATE CONCAT LIST ───────────────────────────────────
            concat_list = os.path.join(output_dir, f"_debate_concat_{fmt}.txt")
            try:
                with open(concat_list, 'w') as f:
                    for vp in video_paths:
                        f.write(f"file '{os.path.abspath(vp)}'\n")
                print(f"[DebateMerge]   📋 Concat list: {len(video_paths)} segments")
            except Exception as e:
                errors.append(f"❌ {fmt}: Concat list failed: {e}")
                continue

            # ── STEP 5: FFMPEG STREAM-COPY MERGE ──────────────────────────────
            try:
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-fflags', '+genpts',
                    '-i', concat_list,
                    '-c', 'copy',
                    '-reset_timestamps', '1',
                    final_video
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)

                if result.returncode == 0 and os.path.exists(final_video):
                    size_mb = os.path.getsize(final_video) / (1024 * 1024)
                    results.append(f"✅ {fmt}: {os.path.basename(final_video)} ({size_mb:.1f} MB)")
                    print(f"[DebateMerge] ✅ {fmt}: Final video created ({size_mb:.1f} MB)")

                    # ── STEP 6: CLEANUP ALL INTERMEDIATE + ORIGINAL FILES ──────
                    cleanup_count += self._cleanup_intermediate_files(output_dir, fmt)

                else:
                    stderr_msg = result.stderr.decode('utf-8', errors='ignore')[:150] if result.stderr else "Unknown"
                    errors.append(f"❌ {fmt}: FFmpeg failed: {stderr_msg}")
                    print(f"[DebateMerge] ❌ {fmt}: {stderr_msg}")

            except Exception as e:
                errors.append(f"❌ {fmt}: Exception: {e}")
                print(f"[DebateMerge] ❌ {fmt}: {e}")

            finally:
                if os.path.exists(concat_list):
                    try:
                        os.remove(concat_list)
                    except:
                        pass

        # ── FINAL SUMMARY ─────────────────────────────────────────────────────
        summary = "\n".join(results) if results else "No formats processed"
        if cleanup_count > 0:
            summary += f"\n🗑️ Cleanup: Deleted {cleanup_count} files"
        if errors:
            summary += f"\n⚠️ Errors: " + " | ".join(errors)

        if len(results) == len(video_formats) and len(results) > 0:
            summary = f"✅ COMPLETE: {len(results)}/{len(video_formats)} formats merged\n\n{summary}"
        elif len(results) > 0:
            summary = f"⚠️ PARTIAL: {len(results)}/{len(video_formats)} formats\n\n{summary}"

        print("[DebateMerge] " + "=" * 60)
        print(summary)
        return summary

    def _cleanup_intermediate_files(self, output_dir: str, fmt: str) -> int:
        """
        Delete ALL intro/debate files for format (intermediates + originals).
        Returns count of deleted files.

        DELETES:
          - intro_{fmt}.mp4 (original video)
          - intro_{fmt}_with_audio.mp4 (with audio)
          - intro_{fmt}_audio.mp3 (audio file)
          - intro_{fmt}_cc_en.txt (CC file)
          - debate_video_{fmt}.mp4 (original video)
          - debate_video_{fmt}_with_audio.mp4 (with audio)
          - debate_video_{fmt}_audio.mp3 (audio file)
          - debate_video_{fmt}_cc_en.txt (CC file)

        PRESERVES:
          - *.md files (propose.md, oppose.md, decide.md)
        """
        deleted = 0
        patterns = [
            # All intro files (original + intermediates)
            f"intro_{fmt}.mp4",           # original video
            f"intro_{fmt}_with_audio.mp4",
            f"intro_{fmt}_audio.mp3",
            f"intro_{fmt}_cc_en.txt",
            # All debate files (original + intermediates)
            f"debate_video_{fmt}.mp4",     # original video
            f"debate_video_{fmt}_with_audio.mp4",
            f"debate_video_{fmt}_audio.mp3",
            f"debate_video_{fmt}_cc_en.txt",
        ]

        for pattern in patterns:
            filepath = os.path.join(output_dir, pattern)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    print(f"[DebateMerge]   🗑️ {os.path.basename(filepath)}")
                    deleted += 1
                except Exception as e:
                    print(f"[DebateMerge]   ⚠️ Failed to delete {os.path.basename(filepath)}")

        return deleted
