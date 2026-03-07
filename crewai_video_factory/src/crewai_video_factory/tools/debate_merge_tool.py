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
    topic: str = Field(default="", description="Topic name used to build output filename slug")
    topic_slug: str = Field(default="", description="Pre-computed topic slug (e.g. AI_Replace_Entry_Level). Falls back to auto-slug from topic.")
    lang_suffix: str = Field(default="En", description="Language suffix for output filename. 'En' for English, 'Bn' for Bengali, etc.")


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
        topic_slug: str = "",
        lang_suffix: str = "En",
    ) -> str:
        if video_formats is None:
            video_formats = ["Shorts"]

        if not debate_merge_enabled:
            return "🔇 Debate merge skipped (debate_merge_enabled=false)"

        # ── Build topic slug for output filename ──────────────────────────
        import re as _re
        if not topic_slug or topic_slug.strip() in ('', 'topic_slug'):
            topic_slug = "_".join(_re.findall(r"\w+", topic)[:4])
        print(f"[DebateMerge] 📛 topic_slug: {topic_slug}")

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

            # ✅ OUTPUT FILES — dynamic name: {channel}_{topic_slug}_{fmt}_{lang}.mp4
            _lang = lang_suffix if lang_suffix else "En"
            # ✅ SEGMENT DEFINITIONS
            _lang = lang_suffix if lang_suffix else "En"
            final_video = os.path.join(output_dir, f"{channel}_Debate_{topic_slug}_{fmt}_{_lang}.mp4")
            final_cc    = os.path.join(output_dir, f"{channel}_Debate_{topic_slug}_{fmt}_{_lang}_cc.txt")

            # ✅ SMART SKIP: Check if FINAL merged video already exists
            if os.path.exists(final_video):
                size_mb = os.path.getsize(final_video) / (1024 * 1024)
                results.append(f"✅ {fmt}: {os.path.basename(final_video)} ({size_mb:.1f} MB) — already exists, skipped")
                print(f"[DebateMerge] ⏭️ {fmt}: Final video exists — skipping")
                cleanup_count += self._cleanup_intermediate_files(output_dir, fmt, _lang)
                continue
            segments = [
                ("intro",          f"intro_{fmt}_{_lang}_with_audio.mp4",              f"intro_{fmt}_{_lang}_cc.txt"),
                ("debate_video",   f"debate_video_{fmt}_{_lang}_with_audio.mp4",       f"debate_video_{fmt}_{_lang}_cc.txt"),
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

            # ── STEP 3: PROBE SEGMENTS (video + audio) ──────────────────────
            print(f"[DebateMerge] 🔍 {fmt}: Probing compatibility...")
            audio_signatures = set()   # full: codec,sample_rate,channels
            for vp in video_paths:
                v_probe = subprocess.run([
                    'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_name,width,height,r_frame_rate,pix_fmt',
                    '-of', 'csv=p=0', vp
                ], capture_output=True, text=True)
                a_probe = subprocess.run([
                    'ffprobe', '-v', 'error', '-select_streams', 'a:0',
                    '-show_entries', 'stream=codec_name,sample_rate,channels',
                    '-of', 'csv=p=0', vp
                ], capture_output=True, text=True)
                v_info = v_probe.stdout.strip() or 'no-video'
                a_info = a_probe.stdout.strip() or 'NO-AUDIO'
                print(f"[DebateMerge]   {os.path.basename(vp)}: V={v_info}  A={a_info}")
                # Track FULL signature — codec+sample_rate+channels must ALL match
                audio_signatures.add(a_probe.stdout.strip() if a_probe.stdout.strip() else 'missing')
            # Always re-encode: mismatched sample rate (e.g. 24000 vs 44100) breaks stream-copy
            _reencode_audio = len(audio_signatures) != 1 or 'missing' in audio_signatures
            if _reencode_audio:
                print(f"[DebateMerge]   ⚠️  Audio mismatch {audio_signatures} — re-encoding to aac/44100/stereo")
            else:
                print(f"[DebateMerge]   ✅ Audio identical ({audio_signatures}) — stream-copy safe")

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

            # ── STEP 5: FFMPEG CONCAT MERGE ───────────────────────────────────
            try:
                if _reencode_audio:
                    # Re-encode audio to aac 44100Hz stereo — fixes codec/rate mismatches
                    cmd = [
                        'ffmpeg', '-y',
                        '-f', 'concat', '-safe', '0',
                        '-i', concat_list,
                        '-c:v', 'copy',
                        '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-b:a', '128k',
                        '-reset_timestamps', '1',
                        final_video
                    ]
                else:
                    cmd = [
                        'ffmpeg', '-y',
                        '-f', 'concat', '-safe', '0',
                        '-fflags', '+genpts',
                        '-i', concat_list,
                        '-c', 'copy',
                        '-reset_timestamps', '1',
                        final_video
                    ]
                print(f"[DebateMerge]   🎬 {'re-encode audio' if _reencode_audio else 'stream-copy'} merge...")
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)

                if result.returncode == 0 and os.path.exists(final_video):
                    size_mb = os.path.getsize(final_video) / (1024 * 1024)
                    results.append(f"✅ {fmt}: {os.path.basename(final_video)} ({size_mb:.1f} MB)")
                    print(f"[DebateMerge] ✅ {fmt}: Final video created ({size_mb:.1f} MB)")

                    # ── STEP 6: CLEANUP ALL INTERMEDIATE + ORIGINAL FILES ──────
                    cleanup_count += self._cleanup_intermediate_files(output_dir, fmt, _lang)

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

    def _cleanup_intermediate_files(self, output_dir: str, fmt: str, lang: str = "En") -> int:
        """
        Delete ALL intro/debate intermediate files using wildcards.
        Returns count of deleted files.

        DELETES (via glob wildcards — catches all lang variants, legacy names, etc.):
          - intro_{fmt}*.mp4  (silent + with_audio, all lang suffixes)
          - intro_{fmt}*.mp3  (audio, all variants)
          - intro_{fmt}*.txt  (CC files)
          - debate_video_{fmt}*.mp4  (silent + with_audio, all variants)
          - debate_video_{fmt}*.mp3  (presub_raw, sub, legacy, any)
          - debate_video_{fmt}*.txt  (CC files)
          - debate_*.mp3             (stray pro/con/mod clips)
          - debate_video_*.mp3       (any legacy audio without fmt suffix)

        PRESERVES (safety guard — never deleted):
          - Files starting with channel name (final merged outputs)
          - *.md files (propose, oppose, decide)
        """
        import glob as _glob
        deleted = 0

        wildcards = [
            f"intro_{fmt}*.mp4",       # intro silent + with_audio (all lang variants)
            f"intro_{fmt}*.mp3",       # intro audio (all variants)
            f"intro_{fmt}*.txt",       # intro CC
            f"debate_video_{fmt}*.mp4", # debate silent + with_audio (all variants)
            f"debate_video_{fmt}*.mp3", # debate audio (presub_raw, sub, legacy, any)
            f"debate_video_{fmt}*.txt", # debate CC
            f"debate_video_*.mp3",     # legacy audio without fmt (e.g. debate_video_Shorts_audio.mp3)
            f"debate_*.mp3",           # stray pro/con/mod clips (debate_pro.mp3 etc.)
        ]

        for wc in wildcards:
            for filepath in sorted(_glob.glob(os.path.join(output_dir, wc))):
                fname = os.path.basename(filepath)
                # Safety: never delete final merged outputs or source .md files
                if fname.endswith(".md"):
                    continue
                # Never delete if it looks like a final output (contains channel name pattern)
                # Final outputs are named like: PlayOwnAi_Debate_...mp4
                if "_Debate_" in fname or "_debate_concat_" in fname:
                    continue
                try:
                    os.remove(filepath)
                    print(f"[DebateMerge]   🗑️ {fname}")
                    deleted += 1
                except Exception as e:
                    print(f"[DebateMerge]   ⚠️ Failed to delete {fname}: {e}")

        return deleted
