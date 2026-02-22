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


class BarMergeTool(BaseTool):
    """
    Concatenates intro_[fmt].mp4 + bar_race_[fmt].mp4, then merges with
    bar_race_[fmt]_audio.mp3 into a single Merge_bar_race_[fmt].mp4.
    Triggered by bar_merge_enabled=true in data.json.
    """
    name: str = "Bar Merge Tool"
    description: str = (
        "Concatenates intro + bar_race + audio into Merge_bar_race_[fmt].mp4 (Stage 1), "
        "then appends definition_video_with_audio as the last segment into Final_[fmt].mp4 (Stage 2). "
        "Returns 'Bar merge completed' with Final_[fmt].mp4 listed when done. "
        "Triggered by bar_merge_enabled=true."
    )
    args_schema: Type[BaseModel] = BarMergeToolInput

    def _run(
        self,
        output_dir: str,
        video_formats: List[str],
        bar_merge_enabled: bool = False,
    ) -> str:

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
            defvid_path  = os.path.join(output_dir, f"definition_video_{fmt}_with_audio.mp4")
            defvid_silent= os.path.join(output_dir, f"definition_video_{fmt}.mp4")
            intro_path   = os.path.join(output_dir, f"intro_{fmt}.mp4")
            race_path    = os.path.join(output_dir, f"bar_race_{fmt}.mp4")
            audio_path   = os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3")
            merge_race   = os.path.join(output_dir, f"Merge_bar_race_{fmt}.mp4")   # intro+race+audio
            output_path  = os.path.join(output_dir, f"Final_{fmt}.mp4")            # defvid + merge_race
            temp_concat  = os.path.join(output_dir, f"_temp_concat_{fmt}.mp4")
            concat_list  = os.path.join(output_dir, f"_concat_list_{fmt}.txt")

            print(f"[BarMergeTool] {fmt}: checking files...")

            # definition_video: prefer version with audio baked in
            has_defvid = os.path.exists(defvid_path) or os.path.exists(defvid_silent)
            def_path   = defvid_path if os.path.exists(defvid_path) else (
                         defvid_silent if os.path.exists(defvid_silent) else None)
            has_intro  = os.path.exists(intro_path)
            has_race   = os.path.exists(race_path)
            has_audio  = os.path.exists(audio_path)

            if not has_race:
                errors.append(f"❌ {fmt}: bar_race_{fmt}.mp4 not found — skipping")
                continue

            print(f"[BarMergeTool] {fmt}: defvid={has_defvid} intro={has_intro} race={has_race} audio={has_audio}")

            try:
                def get_duration(path):
                    r = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                         "-of", "csv=p=0", path],
                        capture_output=True, text=True
                    )
                    try:
                        return float(r.stdout.strip())
                    except Exception:
                        return 0.0

                def normalize(src, dst, keep_audio=False):
                    """Re-encode to 30fps. keep_audio=True for definition_video (has baked audio)."""
                    extra = [] if keep_audio else ["-an"]
                    r = subprocess.run([
                        "ffmpeg", "-y", "-i", src,
                        "-vf", "fps=30,setpts=PTS-STARTPTS",
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                        "-pix_fmt", "yuv420p",
                    ] + extra + [dst], capture_output=True, check=False)
                    if r.returncode != 0:
                        raise RuntimeError(f"normalize {os.path.basename(src)} failed: {r.stderr.decode()[:200]}")

                # ── STAGE 1: intro + bar_race → concat → merge with bar_race audio ──
                stage1_segments = []
                if has_intro:
                    n = os.path.join(output_dir, f"_norm_intro_{fmt}.mp4")
                    normalize(intro_path, n, keep_audio=False)
                    stage1_segments.append(n)
                n = os.path.join(output_dir, f"_norm_race_{fmt}.mp4")
                normalize(race_path, n, keep_audio=False)
                stage1_segments.append(n)

                temp_stage1 = os.path.join(output_dir, f"_stage1_{fmt}.mp4")
                with open(concat_list, "w") as f:
                    for p in stage1_segments:
                        f.write(f"file '{os.path.abspath(p)}'\n")
                r = subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", concat_list, "-c", "copy", temp_stage1
                ], capture_output=True, check=False)
                if os.path.exists(concat_list): os.remove(concat_list)
                for p in stage1_segments:
                    if os.path.exists(p): os.remove(p)
                if r.returncode != 0:
                    raise RuntimeError(f"stage1 concat failed: {r.stderr.decode()[:200]}")

                s1_dur = get_duration(temp_stage1)
                print(f"[BarMergeTool] {fmt}: stage1 (intro+race) = {s1_dur:.1f}s")

                # Merge bar_race audio into stage1 → Merge_bar_race_[fmt].mp4
                if has_audio:
                    audio_dur = get_duration(audio_path)
                    print(f"[BarMergeTool] {fmt}: merging bar_race audio {audio_dur:.1f}s into {s1_dur:.1f}s video")
                    r = subprocess.run([
                        "ffmpeg", "-y",
                        "-i", temp_stage1, "-i", audio_path,
                        "-c:v", "copy", "-c:a", "aac",
                        "-filter_complex", f"[1:a]apad,atrim=duration={s1_dur:.3f}[aout]",
                        "-map", "0:v", "-map", "[aout]",
                        merge_race
                    ], capture_output=True, check=False)
                    if r.returncode != 0:
                        raise RuntimeError(f"audio merge failed: {r.stderr.decode()[:300]}")
                else:
                    shutil.copy2(temp_stage1, merge_race)
                if os.path.exists(temp_stage1): os.remove(temp_stage1)

                mr_dur = get_duration(merge_race)
                print(f"[BarMergeTool] {fmt}: Merge_bar_race = {mr_dur:.1f}s ✅")

                # ── STAGE 2: Merge_bar_race + definition_video_with_audio → Final ──
                # Order: intro+race FIRST, definition LAST
                if has_defvid and def_path:
                    nd = os.path.join(output_dir, f"_norm_defvid_{fmt}.mp4")
                    nm = os.path.join(output_dir, f"_norm_merge_{fmt}.mp4")
                    normalize(merge_race, nm, keep_audio=True)
                    normalize(def_path,  nd, keep_audio=True)

                    with open(concat_list, "w") as f:
                        f.write(f"file '{os.path.abspath(nm)}'\n")  # race first
                        f.write(f"file '{os.path.abspath(nd)}'\n")  # definition last
                    r = subprocess.run([
                        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", concat_list, "-c", "copy", output_path
                    ], capture_output=True, check=False)
                    if os.path.exists(concat_list): os.remove(concat_list)
                    for p in [nd, nm]:
                        if os.path.exists(p): os.remove(p)
                    if r.returncode != 0:
                        raise RuntimeError(f"stage2 concat failed: {r.stderr.decode()[:200]}")

                    final_dur = get_duration(output_path)
                    print(f"[BarMergeTool] {fmt}: Final (defvid+race) = {final_dur:.1f}s ✅")
                else:
                    # No definition video — Final = Merge_bar_race only
                    shutil.copy2(merge_race, output_path)
                    print(f"[BarMergeTool] {fmt}: no definition video — Final = Merge_bar_race")

                video_for_merge = output_path  # already final, skip old step 2

                # Cleanup temp_concat if leftover
                if os.path.exists(temp_concat):
                    os.remove(temp_concat)

                if os.path.exists(output_path):
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    mr_mb   = os.path.getsize(merge_race) / (1024*1024) if os.path.exists(merge_race) else 0
                    results.append(f"Final_{fmt}.mp4 ({size_mb:.1f} MB)  |  Merge_bar_race_{fmt}.mp4 ({mr_mb:.1f} MB)")
                    print(f"[BarMergeTool] ✅ {fmt}: Final_{fmt}.mp4 ({size_mb:.1f} MB)")
                else:
                    errors.append(f"❌ {fmt}: Final_{fmt}.mp4 not created")

            except Exception as e:
                errors.append(f"❌ {fmt}: {e}")
                for tmp in [temp_concat, concat_list]:
                    if os.path.exists(tmp):
                        os.remove(tmp)

        if not results:
            return "❌ Bar merge failed for all formats.\nErrors:\n" + "\n".join(errors)

        summary = (
            f"🎬 Bar merge completed ({len(results)}/{len(video_formats)} formats).\n"
            + "\n".join([f"   • {r}" for r in results])
        )
        if errors:
            summary += "\n\n⚠️ Some errors:\n" + "\n".join(errors)
        return summary
