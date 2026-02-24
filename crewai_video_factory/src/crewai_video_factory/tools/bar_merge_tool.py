import os
import shutil
import glob
import subprocess
from crewai.tools import BaseTool
from typing import Type, List
from pydantic import BaseModel, Field


class BarMergeToolInput(BaseModel):
    """Input schema for BarMergeTool."""
    output_dir: str = Field(..., description="Output directory containing bar race videos and audio")
    video_formats: List[str] = Field(..., description="List of video formats (HD, Shorts, etc.)")
    bar_merge_enabled: bool = Field(default=False, description="Whether to run bar merge")
    channel: str = Field(default="PlayOwnAi", description="Channel name for final filename")
    topic: str = Field(default="", description="Topic for final filename (spaces→underscores)")


class BarMergeTool(BaseTool):
    """
    Concatenates intro_[fmt].mp4 + bar_race_[fmt].mp4, then merges with
    bar_race_[fmt]_audio.mp3 into a single Merge_bar_race_[fmt].mp4.
    Triggered by bar_merge_enabled=true in data.json.
    """
    name: str = "Bar Merge Tool"
    description: str = (
        "Concatenates intro clip + bar race video, then merges with audio "
        "into a final Merge_bar_race_[fmt].mp4 per format. "
        "Triggered by bar_merge_enabled=true."
    )
    args_schema: Type[BaseModel] = BarMergeToolInput

    def _run(
        self,
        output_dir: str,
        video_formats: List[str],
        bar_merge_enabled: bool = False,
        channel: str = "PlayOwnAi",
        topic: str = "",
    ) -> str:
        # Build clean topic slug: "LLM Tuning Methods" → "LLM_Tuning_Methods"
        import re
        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"

        if not bar_merge_enabled:
            return "🔇 Bar merge skipped (bar_merge_enabled=false)"

        if not shutil.which('ffmpeg'):
            return "❌ FATAL: ffmpeg not found. Install: sudo apt install ffmpeg"

        if not os.path.exists(output_dir):
            return f"❌ Output directory '{output_dir}' not found"

        results = []
        errors = []

        for fmt in video_formats:
            fmt = fmt.strip()
            intro_path  = os.path.join(output_dir, f"intro_{fmt}.mp4")
            race_path   = os.path.join(output_dir, f"bar_race_{fmt}.mp4")
            audio_path  = os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3")
            merge_tmp   = os.path.join(output_dir, f"_merge_tmp_{fmt}.mp4")
            final_name  = f"{channel}_{topic_slug}_{fmt}.mp4"
            output_path = os.path.join(output_dir, final_name)
            temp_concat = os.path.join(output_dir, f"_temp_concat_{fmt}.mp4")
            concat_list = os.path.join(output_dir, f"_concat_list_{fmt}.txt")

            print(f"[BarMergeTool] {fmt}: checking files...")

            # Determine which video files exist
            has_intro = os.path.exists(intro_path)
            has_race  = os.path.exists(race_path)
            has_audio = os.path.exists(audio_path)

            if not has_race:
                errors.append(f"❌ {fmt}: bar_race_{fmt}.mp4 not found — skipping")
                continue

            print(f"[BarMergeTool] {fmt}: intro={has_intro} race={has_race} audio={has_audio}")

            try:
                # --- Step 1: Concat intro + bar race (or just bar race if no intro) ---
                if has_intro:
                    with open(concat_list, 'w') as f:
                        f.write(f"file '{os.path.abspath(intro_path)}'\n")
                        f.write(f"file '{os.path.abspath(race_path)}'\n")
                    concat_result = subprocess.run([
                        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                        '-i', concat_list,
                        '-c', 'copy', temp_concat
                    ], capture_output=True, check=False)
                    if concat_list and os.path.exists(concat_list):
                        os.remove(concat_list)
                    if concat_result.returncode != 0:
                        raise RuntimeError(f"concat failed: {concat_result.stderr.decode()[:200]}")
                    video_for_merge = temp_concat
                    print(f"[BarMergeTool] {fmt}: intro + race concatenated")
                else:
                    video_for_merge = race_path
                    print(f"[BarMergeTool] {fmt}: no intro — using bar race only")

                # --- Step 2: Merge video + audio (or just copy if no audio) ---
                if has_audio:
                    merge_result = subprocess.run([
                        'ffmpeg', '-y',
                        '-i', video_for_merge,
                        '-i', audio_path,
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-shortest',
                        output_path
                    ], capture_output=True, check=False)
                    if merge_result.returncode != 0:
                        raise RuntimeError(f"merge failed: {merge_result.stderr.decode()[:200]}")
                    print(f"[BarMergeTool] {fmt}: video + audio merged")
                else:
                    # No audio — just copy the concatenated video
                    shutil.copy2(video_for_merge, output_path)
                    print(f"[BarMergeTool] {fmt}: no audio — video copied as final")

                # Cleanup temp concat file
                if os.path.exists(temp_concat):
                    os.remove(temp_concat)

                if os.path.exists(output_path):
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    results.append(f"{final_name} ({size_mb:.1f} MB)")
                    print(f"[BarMergeTool] ✅ {fmt}: {output_path} ({size_mb:.1f} MB)")
                else:
                    errors.append(f"❌ {fmt}: output not created")

            except Exception as e:
                errors.append(f"❌ {fmt}: {e}")
                for tmp in [temp_concat, concat_list]:
                    if os.path.exists(tmp):
                        os.remove(tmp)

        if not results:
            return "❌ Bar merge failed for all formats.\nErrors:\n" + "\n".join(errors)

        summary = (
            f"DONE. Bar merge completed ({len(results)}/{len(video_formats)} formats).\n"
            + "\n".join([f"   • {r}" for r in results])
        )
        if errors:
            summary += "\n\n⚠️ Some errors:\n" + "\n".join(errors)
        return summary