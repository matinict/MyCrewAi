import os
import shutil
import subprocess
from crewai.tools import BaseTool
from typing import Type, List
from pydantic import BaseModel, Field
import re

class BarMergeToolInput(BaseModel):
    """Input schema for BarMergeTool."""
    output_dir: str = Field(..., description="Output directory containing segment videos and CC files")
    video_formats: List[str] = Field(..., description="List of video formats (HD, Shorts, etc.)")
    bar_merge_enabled: bool = Field(default=False, description="Whether to run bar merge")
    channel: str = Field(default="PlayOwnAi", description="Channel name for final filename")
    topic: str = Field(default=" ", description="Topic name for final filename")

class BarMergeTool(BaseTool):
    """
    Concatenates 3 pre-rendered videos WITH AUDIO using pure stream-copy (no re-encoding):
      intro_{fmt}_with_audio.mp4 +
      bar_race_{fmt}_with_audio.mp4 +
      definition_video_{fmt}_with_audio.mp4
    → {channel}_{topic_slug}_{fmt}.mp4

    Also merges CC text files:
      intro_{fmt}_cc_en.txt +
      bar_race_{fmt}_cc_en.txt +
      definition_video_{fmt}_cc_en.txt
    → {channel}_{topic_slug}_{fmt}_cc_en.txt

    Uses ffmpeg concat demuxer with -reset_timestamps 1 for timestamp continuity.
    ZERO re-encoding — preserves original quality and sync.
    """
    name: str = "Bar Merge Tool"
    description: str = (
        "Concatenates 3 pre-rendered videos WITH AUDIO using pure stream-copy (no re-encoding). "
        "Output: {channel}_{topic_slug}_{fmt}.mp4 + {channel}_{topic_slug}_{fmt}_cc_en.txt per format. "
        "Uses -reset_timestamps 1 for perfect timestamp continuity. "
        "Triggered by bar_merge_enabled=true."
    )
    args_schema: Type[BaseModel] = BarMergeToolInput

    def _run(
        self,
        output_dir: str,
        video_formats: List[str],
        bar_merge_enabled: bool = False,
        channel: str = "PlayOwnAi",
        topic: str = " ",
    ) -> str:
        if not bar_merge_enabled:
            return "🔇 Bar merge skipped (bar_merge_enabled=false)"

        if not shutil.which('ffmpeg'):
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        # Build clean topic slug for FINAL filename (matches YouTube metadata tool)
        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"
        print(f"[BarMergeTool] Starting pure stream-copy merge for formats: {video_formats}")
        print(f"[BarMergeTool] Final filename pattern: {channel}_{topic_slug}_{{fmt}}.mp4")

        results = []
        errors = []

        for fmt in video_formats:
            fmt = fmt.strip()

            # ✅ OUTPUT FILES WITH FINAL YOUTUBE-READY NAMES (no rename needed later)
            final_video = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
            final_cc    = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}_cc_en.txt")

            # ✅ SMART SKIP: Check if FINAL merged video already exists
            if os.path.exists(final_video):
                results.append(f"⏭️ {fmt}: Skipped ({os.path.basename(final_video)} exists)")
                print(f"[BarMergeTool] ⏭️ {fmt}: Final video exists — skipping")
                continue

            # ✅ SEGMENT DEFINITIONS (STRICT ORDER - PRE-RENDERED WITH AUDIO)
            segments = [
                ("intro", f"intro_{fmt}_with_audio.mp4", f"intro_{fmt}_cc_en.txt"),
                ("bar_race", f"bar_race_{fmt}_with_audio.mp4", f"bar_race_{fmt}_cc_en.txt"),
                ("definition_video", f"definition_video_{fmt}_with_audio.mp4", f"definition_video_{fmt}_cc_en.txt")
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
                    print(f"[BarMergeTool]   ✓ Found video: {vid_file}")

                    # Load CC content if exists
                    if os.path.exists(cc_path):
                        try:
                            with open(cc_path, 'r', encoding='utf-8') as f:
                                content = f.read().strip()
                                if content:
                                    cc_contents.append(content)
                                    print(f"[BarMergeTool]     ✓ Added CC: {cc_file}")
                        except Exception as e:
                            print(f"[BarMergeTool]     ⚠️ CC read error ({cc_file}): {e}")
                    else:
                        print(f"[BarMergeTool]     ℹ️ CC not found: {cc_file}")

            if missing_files:
                errors.append(f"❌ {fmt}: Missing segments: {', '.join(missing_files)}")
                print(f"[BarMergeTool] ❌ {fmt}: SKIPPED due to missing files")
                continue

            # ── STEP 2: SAVE MERGED CC FILE WITH FINAL NAME ──────────────────
            if cc_contents:
                full_cc = "\n\n".join(cc_contents)  # Clear separation between segments
                try:
                    with open(final_cc, 'w', encoding='utf-8') as f:
                        f.write(full_cc)
                    cc_size_kb = os.path.getsize(final_cc) // 1024
                    print(f"[BarMergeTool] ✅ {fmt}: Merged CC saved → {os.path.basename(final_cc)} ({cc_size_kb} KB)")
                except Exception as e:
                    print(f"[BarMergeTool] ⚠️ {fmt}: Failed to save merged CC: {e}")
            else:
                print(f"[BarMergeTool] ⚠️ {fmt}: No CC content to merge")

            # ── STEP 2.5: PROBE EACH SEGMENT FOR COMPATIBILITY ───────────────
            print(f"[BarMergeTool] 🔍 {fmt}: Probing segment compatibility...")
            for vp in video_paths:
                probe_cmd = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_name,width,height,r_frame_rate,pix_fmt,time_base',
                    '-of', 'csv=p=0', vp
                ]
                probe = subprocess.run(probe_cmd, capture_output=True, text=True)
                print(f"[BarMergeTool]   PROBE {os.path.basename(vp)}: {probe.stdout.strip()}")

            # ── STEP 3: CREATE CONCAT LIST ───────────────────────────────────
            concat_list = os.path.join(output_dir, f"_concat_{fmt}.txt")
            try:
                with open(concat_list, 'w') as f:
                    for vp in video_paths:
                        f.write(f"file '{os.path.abspath(vp)}'\n")
                print(f"[BarMergeTool]   📋 Concat list created ({len(video_paths)} segments)")
            except Exception as e:
                errors.append(f"❌ {fmt}: Failed to create concat list: {e}")
                continue

            # ── STEP 4: PURE STREAM-COPY CONCATENATION (NO RE-ENCODING) ──────
            try:
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-fflags', '+genpts',       # 🔑 Regenerate timestamps — fixes A/V sync
                    '-i', concat_list,
                    '-c', 'copy',               # 🔑 CRITICAL: NO RE-ENCODING
                    '-reset_timestamps', '1',   # 🔑 Reset timestamps at each segment boundary
                    final_video
                ]
                result = subprocess.run(cmd, capture_output=True, check=False)

                # Cleanup concat list immediately
                if os.path.exists(concat_list):
                    os.remove(concat_list)

                if result.returncode != 0:
                    stderr_msg = result.stderr.decode()[:300] if result.stderr else "Unknown error"
                    raise RuntimeError(f"ffmpeg concat failed: {stderr_msg}")

                if not os.path.exists(final_video):
                    raise RuntimeError("Output file not created despite ffmpeg success")

                size_mb = os.path.getsize(final_video) / (1024 * 1024)
                results.append(f"{os.path.basename(final_video)} ({size_mb:.1f} MB) + CC")
                print(f"[BarMergeTool] ✅ {fmt}: SUCCESS → {os.path.basename(final_video)} ({size_mb:.1f} MB)")
                print(f"[BarMergeTool]    ℹ️  Pure stream-copy (no re-encoding) - timestamps fixed with -fflags +genpts")

            except Exception as e:
                errors.append(f"❌ {fmt}: {str(e)}")
                # Cleanup on failure
                for tmp in [concat_list, final_video]:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                print(f"[BarMergeTool] ERROR for {fmt}: {e}")

        # ── FINAL SUMMARY ──────────────────────────────────────────────────
        if not results and not errors:
            return "ℹ️ No formats processed (all skipped or missing segments)"

        summary_lines = []
        if results:
            summary_lines.append(f"✅ SUCCESS ({len(results)}/{len(video_formats)} formats):")
            summary_lines.extend([f"   • {r}" for r in results])
        if errors:
            summary_lines.append(f"\n⚠️ ERRORS ({len(errors)}):")
            summary_lines.extend([f"   • {e}" for e in errors])

        return "\n".join(summary_lines)
