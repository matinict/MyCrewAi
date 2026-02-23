import os
import json
import re
import time
import urllib.request
import urllib.parse
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from datetime import datetime

# All target languages for metadata translation
LANGUAGES = [
    'ar', 'bn', 'bg', 'bs', 'my', 'zh-cn', 'cs', 'et', 'fr', 'de', 'el',
    'gu', 'hi', 'id', 'it', 'ja', 'ko', 'mr', 'fa', 'pl', 'pt',
    'ru', 'sr', 'es', 'ta', 'te', 'th', 'tr', 'uk', 'ur', 'vi'
]

LANG_NAMES = {
    'ar':'Arabic','bn':'Bengali','bg':'Bulgarian','bs':'Bosnian','my':'Burmese',
    'zh-cn':'Chinese','cs':'Czech','et':'Estonian','fr':'French','de':'German',
    'el':'Greek','gu':'Gujarati','hi':'Hindi','id':'Indonesian','it':'Italian',
    'ja':'Japanese','ko':'Korean','mr':'Marathi','fa':'Persian','pl':'Polish',
    'pt':'Portuguese','ru':'Russian','sr':'Serbian','es':'Spanish','ta':'Tamil',
    'te':'Telugu','th':'Thai','tr':'Turkish','uk':'Ukrainian','ur':'Urdu','vi':'Vietnamese'
}

def _google_translate(text: str, dest: str, retries: int = 3) -> str:
    """Translate text using Google Translate free endpoint. No API key needed."""
    if not text or not text.strip():
        return text
    # Chunk long text (Google free endpoint limit ~4000 chars)
    if len(text) > 4000:
        # Split on double-newline, translate each chunk
        chunks = text.split("\n\n")
        translated = []
        for chunk in chunks:
            translated.append(_google_translate(chunk, dest, retries))
            time.sleep(0.1)
        return "\n\n".join(translated)
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=en&tl={urllib.parse.quote(dest)}"
            f"&dt=t&q={urllib.parse.quote(text)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    result = "".join(part[0] for part in data[0] if part[0])
                    return result
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(1.5)
                else:
                    print(f"[YTMetadata] ⚠️  Translation failed ({dest}): {e}")
                    return text  # fallback: return original
    except Exception as e:
        print(f"[YTMetadata] ⚠️  Translation error ({dest}): {e}")
        return text

class YouTubeMetadataToolInput(BaseModel):
    """Input schema for YouTubeMetadataTool."""
    topic: str = Field(..., description="Topic/title for the video")
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
    output_dir: str = Field(..., description="Output directory for metadata files")
    start_year: int = Field(default=2015, description="Start year of data")
    end_year: int = Field(default=2026, description="End year of data")
    video_duration: float = Field(default=60.0, description="Video duration in seconds")
    generate_narration: bool = Field(default=True, description="Whether to generate narration text")
    generate_youtube_metadata: bool = Field(default=True, description="Whether to generate YouTube metadata")
    channel: str = Field(default="PlayOwnAi", description="YouTube channel name without @ prefix")
    channel_lower: str = Field(default="playownai", description="Lowercase channel name for LinkedIn/URLs")
    website: str = Field(default="youtube.com/@PlayOwnAi", description="Website URL for description")
    video_formats: list = Field(default=[], description="Video formats used (HD, Shorts, etc.) — for cleanup")
    fps: float = Field(default=4.9, description="Seconds per period (Shorts speed)")
    fps_hd_offset: float = Field(default=1.0, description="Multiplier for HD duration vs Shorts")
    n_periods: int = Field(default=0, description="Number of data rows/periods in CSV (0=auto-detect)")


class YouTubeMetadataTool(BaseTool):
    name: str = "YouTube Metadata Generator"
    description: str = "Generates narration text file (cc_en.txt) and YouTube metadata (title, description, tags, chapters) with SEO optimization"
    args_schema: Type[BaseModel] = YouTubeMetadataToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        start_year: int = 2015,
        end_year: int = 2026,
        video_duration: float = 60.0,
        generate_narration: bool = True,
        generate_youtube_metadata: bool = True,
        channel: str = "PlayOwnAi",
        channel_lower: str = "playownai",
        website: str = "youtube.com/@PlayOwnAi",
        video_formats: list = None,
        fps: float = 4.9,
        fps_hd_offset: float = 1.0,
        n_periods: int = 0,
    ) -> str:
        import time as _time
        import re as _vre
        t0 = _time.time()

        # ── Normalize video_formats FIRST — used for both metadata and cleanup ──
        # Agent may pass: None, [], ["HD"], "['HD']", "HD", etc.
        if not video_formats:
            # Try to infer from output_dir name or default to ["HD"]
            video_formats = ["HD"]
        elif isinstance(video_formats, str):
            # Parse string representations like "['HD', 'Shorts']" or "HD"
            video_formats = [v.strip() for v in _vre.findall(r"[A-Za-z0-9]+", video_formats)
                             if v not in ("true","false","null","list")]
        # Filter to known valid formats only
        _valid = {"HD","2K","4K","8K","Shorts","ShortsHD","Shorts4K"}
        video_formats = [f for f in video_formats if f in _valid] or ["HD"]

        # NEVER correct filename spelling — use exactly as passed from inputs
        clean_filename = filename.strip().replace("/","").replace("\\","")

        print(f"[YTMetadata] ▶ Starting — topic='{topic}' filename='{clean_filename}' channel='{channel}'")
        print(f"[YTMetadata]   output_dir : {output_dir}")
        print(f"[YTMetadata]   years      : {start_year}–{end_year}  formats: {video_formats}")
        print(f"[YTMetadata]   narration  : {generate_narration}  |  metadata: {generate_youtube_metadata}")

        os.makedirs(output_dir, exist_ok=True)
        clean_filename = filename
        results = []

        if generate_narration:
            print(f"[YTMetadata] 📝 Step 1/2 — Generating narration text …")
            t1 = _time.time()
            narration_result = self._generate_narration_file(
                topic, start_year, end_year, output_dir, clean_filename, channel=channel)
            print(f"[YTMetadata] ✅ Narration done in {_time.time()-t1:.1f}s → {narration_result}")
            results.append(narration_result)

        if generate_youtube_metadata:
            print(f"[YTMetadata] 🎬 Step 2/2 — Generating YouTube metadata per format …")
            t2 = _time.time()

            # Auto-detect n_periods from CSV if not provided
            actual_periods = n_periods
            if actual_periods <= 0:
                try:
                    import pandas as pd
                    _df = pd.read_csv(f"output/{clean_filename}.csv")
                    actual_periods = len(_df)
                    print(f"[YTMetadata]   Auto-detected n_periods={actual_periods} from CSV")
                except Exception:
                    actual_periods = end_year - start_year + 1
                    print(f"[YTMetadata]   Fallback n_periods={actual_periods} from year range")

            fmts = video_formats  # already normalized at top of _run
            title = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
            tags  = self._generate_youtube_tags(topic, channel=channel)
            print(f"[YTMetadata]   • Title: {title}")
            print(f"[YTMetadata]   • Tags: {len(tags)} tags")

            fmt_results = []
            for fmt in fmts:
                fmt = fmt.strip()
                # Skip if English metadata already exists for this format
                existing = os.path.join(output_dir, "YT", f"Metadata_{fmt}_En.json")
                if os.path.exists(existing):
                    print(f"[YTMetadata]   • [{fmt}] ⏭️  Skipping — YT/Metadata_{fmt}_En.json already exists")
                    fmt_results.append(f"⏭️  [{fmt}] Skipped (already exists)")
                    continue
                is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                fmt_spp = fps if is_portrait else fps * fps_hd_offset
                # Duration = periods * spp + hold (2 * spp)
                fmt_duration = actual_periods * fmt_spp + fmt_spp * 2
                print(f"[YTMetadata]   • [{fmt}] spp={fmt_spp:.2f}s × {actual_periods} periods + hold = {fmt_duration:.1f}s")

                description = self._generate_youtube_description(
                    topic, start_year, end_year, fmt_duration,
                    channel=channel, channel_lower=channel_lower, website=website)
                chapters = self._generate_youtube_chapters(start_year, end_year, fmt_duration)
                print(f"[YTMetadata]   • [{fmt}] Chapters: {chapters.count(chr(10))+1} entries")

                meta_result = self._write_metadata_files(
                    topic, title, description, tags, chapters, output_dir, fmt=fmt)
                fmt_results.append(meta_result)

            metadata_result = "\n".join(fmt_results)
            print(f"[YTMetadata] ✅ Metadata done in {_time.time()-t2:.1f}s")
            results.append(metadata_result)

        print(f"[YTMetadata] 🏁 Metadata done in {_time.time()-t0:.1f}s")

        # --- Final cleanup + rename always runs regardless of metadata flag ---
        self._cleanup_and_rename(output_dir, video_formats, channel, topic)  # already normalized

        return "\n\n".join(results) if results else "✅ Cleanup and rename completed."

    def _generate_narration_file(self, topic: str, start_year: int, end_year: int, output_dir: str, clean_filename: str, channel: str = "PlayOwnAi") -> str:
        """Generate professional narration text file from CSV data"""
        csv_path = f"output/{clean_filename}.csv"
        narration_text = ""

        print(f"[YTMetadata]   CSV path: {csv_path} (exists={os.path.exists(csv_path)})")
        if os.path.exists(csv_path):
            try:
                print(f"[YTMetadata]   Reading CSV …")
                import pandas as pd
                df = pd.read_csv(csv_path)
                print(f"[YTMetadata]   CSV loaded: {len(df)} rows × {len(df.columns)} cols")

                time_col = df.columns[0]
                data_cols = df.columns[1:]

                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])

                yearly_leaders = []
                for idx, row in df.iterrows():
                    leader = row[data_cols].idxmax()
                    value = row[leader]
                    year = int(row[time_col])
                    yearly_leaders.append((year, leader, value))

                narration_parts = [
                    f"Welcome to @{channel}.",
                    f"Today, we're exploring {topic} Race from {start_year} to {end_year}.",
                    "Only for basic idea about trending",
                    "Let's see how the landscape evolved over time."
                ]

                for year, leader, value in yearly_leaders:
                    if value <= 20:
                        narration_parts.append(f"{year}. The market is forming.")
                    elif value <= 40:
                        narration_parts.append(f"{year}. {leader} gains traction.")
                    elif value <= 70:
                        narration_parts.append(f"{year}. {leader} shows strength.")
                    else:
                        narration_parts.append(f"{year}. {leader} leads the market.")

                final_year, final_leader, _ = yearly_leaders[-1]
                narration_parts.append(f"And in {final_year}, {final_leader} continues to lead.")
                narration_parts.append("The evolution of technology and trends continues.")
                narration_parts.append(f"Subscribe to @{channel} for more insights.")

                narration_text = " ".join(narration_parts)

            except Exception as e:
                print(f"[WARN] CSV reading failed: {e}")
                narration_text = self._get_fallback_narration(topic, start_year, end_year, channel=channel)
        else:
            narration_text = self._get_fallback_narration(topic, start_year, end_year, channel=channel)

        # 🔑 KEY: Save in topic subdirectory as cc_en.txt
        narration_file_path = f"{output_dir}/cc_en.txt"
        with open(narration_file_path, 'w', encoding='utf-8') as f:
            f.write(narration_text)

        return f"📝 Narration text saved to: cc_en.txt"

    def _generate_youtube_metadata(self, topic: str, start_year: int, end_year: int, video_duration: float, output_dir: str, clean_filename: str, channel: str = "PlayOwnAi", channel_lower: str = "playownai", website: str = "youtube.com/@PlayOwnAi") -> str:
        """Generate YouTube metadata with SEO optimization (legacy path — called directly)."""
        title       = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
        description = self._generate_youtube_description(topic, start_year, end_year, video_duration, channel=channel, channel_lower=channel_lower, website=website)
        tags        = self._generate_youtube_tags(topic, channel=channel)
        chapters    = self._generate_youtube_chapters(start_year, end_year, video_duration)
        return self._write_metadata_files(topic, title, description, tags, chapters, output_dir)

    def _write_metadata_files(self, topic: str, title: str, description: str, tags: list, chapters: str, output_dir: str, fmt: str = "") -> str:
        """
        Write metadata files into YT/ subfolder.
        Structure:
          output/{topic}/YT/
            {fmt}_En.json   ← English JSON
            {fmt}_En.txt    ← English TXT
            {fmt}_{Lang}.txt  ← one TXT per language (31 languages)
        """
        yt_dir = os.path.join(output_dir, "YT")
        # Auto-migrate old YT/ folder → YT/ if it exists
        old_yt = os.path.join(output_dir, "YT")
        if os.path.exists(old_yt) and not os.path.exists(yt_dir):
            import shutil as _shutil
            _shutil.move(old_yt, yt_dir)
            print(f"[YTMetadata]   🔄 Migrated: YT/ → YT/")
        os.makedirs(yt_dir, exist_ok=True)

        prefix = fmt if fmt else "Video"
        file_prefix = f"Metadata_{prefix}"  # e.g. Metadata_HD, Metadata_Shorts

        # ── English JSON ──
        metadata = {
            "title": title,
            "description": description,
            "tags": tags,
            "chapters": chapters,
            "category": "Science & Technology",
            "language": "en",
            "created_at": datetime.now().isoformat()
        }
        en_json_path = os.path.join(yt_dir, f"{file_prefix}_En.json")
        # Skip if already exists
        if not os.path.exists(en_json_path):
            with open(en_json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"[YTMetadata]   📄 Saved: {file_prefix}_En.json")
        else:
            print(f"[YTMetadata]   ⏭️  Exists: {file_prefix}_En.json")

        # ── English TXT ──
        en_txt_path = os.path.join(yt_dir, f"{file_prefix}_En.txt")
        if not os.path.exists(en_txt_path):
            with open(en_txt_path, 'w', encoding='utf-8') as f:
                f.write(f"TITLE:\n{title}\n\n")
                f.write(f"DESCRIPTION:\n{description}\n\n")
                f.write(f"TAGS:\n{', '.join(tags)}\n\n")
                f.write(f"CHAPTERS:\n{chapters}\n")
            print(f"[YTMetadata]   📄 Saved: {file_prefix}_En.txt")
        else:
            print(f"[YTMetadata]   ⏭️  Exists: {file_prefix}_En.txt")

        # ── Translated TXT files — one per language ──
        print(f"[YTMetadata]   🌍 Translating to {len(LANGUAGES)} languages …")
        ok_count = 0
        for lang_code in LANGUAGES:
            lang_suffix = lang_code  # use code directly: bn, ar, zh-cn, fr...
            txt_path = os.path.join(yt_dir, f"{file_prefix}_{lang_suffix}.txt")

            if os.path.exists(txt_path):
                print(f"[YTMetadata]     ⏭️  {file_prefix}_{lang_suffix}.txt exists")
                ok_count += 1
                continue

            try:
                t_title       = _google_translate(title, lang_code)
                t_description = _google_translate(description, lang_code)
                t_tags_str    = _google_translate(", ".join(tags), lang_code)

                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"TITLE:\n{t_title}\n\n")
                    f.write(f"DESCRIPTION:\n{t_description}\n\n")
                    f.write(f"TAGS:\n{t_tags_str}\n\n")
                    f.write(f"CHAPTERS:\n{chapters}\n")  # chapters keep timestamps (numbers)
                print(f"[YTMetadata]     ✅ {file_prefix}_{lang_suffix}.txt  ({LANG_NAMES.get(lang_suffix, lang_suffix)})")
                ok_count += 1
                time.sleep(0.2)  # be polite to free API
            except Exception as e:
                print(f"[YTMetadata]     ❌ {lang_code}: {e}")

        total = len(LANGUAGES) + 2  # +2 for En.json + En.txt
        return f"🎬 [{file_prefix}] {ok_count+2}/{total} files in YT/"
    def _generate_youtube_title(self, topic: str, start_year: int, end_year: int, channel: str = "PlayOwnAi") -> str:
        """Generate SEO-optimized YouTube title"""

        title_templates = [
            f"{topic} Race {start_year}-{end_year}: Complete Evolution & Trends",
            f"The {topic} Evolution ({start_year}-{end_year}): Who Dominates?",
            f"{topic} Comparison {start_year}-{end_year}: Shocking Results!",
            f"How {topic} Changed Forever ({start_year}-{end_year}) | Data Visualization",
            f"{topic} Market Share {start_year}-{end_year}: The Full Story",
            f"Ultimate {topic} Race: {start_year} vs {end_year} (Data-Driven)",
            f"{topic} Trends Explained: {start_year}-{end_year} Analysis",
            f"Watch {topic} Dominate: {start_year}-{end_year} Timeline",
        ]

        if len(topic) > 20:
            return title_templates[3]
        elif len(topic) > 10:
            return title_templates[0]
        else:
            return title_templates[1]

    def _generate_youtube_description(self, topic: str, start_year: int, end_year: int, video_duration: float, channel: str = "PlayOwnAi", channel_lower: str = "playownai", website: str = "youtube.com/@PlayOwnAi") -> str:
        """Generate SEO-optimized YouTube description"""

        description = f"""🎬 {topic} Race {start_year}-{end_year}: Complete Data Visualization

📊 In this video, we explore the evolution of {topic} from {start_year} to {end_year}. Watch how the market leaders changed over time and discover which {topic.lower()} dominated each year!

🔔 Subscribe to @{channel} for more data-driven insights and visualizations!

⏱️ TIMESTAMPS:
See chapters below for year-by-year breakdown.

📈 DATA SOURCE:
This visualization is based on comprehensive market data tracking {topic.lower()} popularity, adoption rates, and market share from {start_year} to {end_year}.

🎯 KEY INSIGHTS:
• Market trends and shifts
• Year-by-year leader changes
• Growth patterns and adoption rates
• Competitive landscape evolution

💡 ABOUT THIS CHANNEL:
@{channel} creates professional data visualizations and insights on technology trends, market analysis, and industry evolution. Subscribe for weekly content!

📱 FOLLOW US:
• YouTube: @{channel}
• LinkedIn: {channel_lower} | www.linkedin.com/company/{channel_lower}/
• Website: {website}

#DataVisualization #{topic.replace(' ', '')} #MarketAnalysis #TechTrends #{start_year}To{end_year}

---
⚠️ Disclaimer: This video is for educational and informational purposes only. Data is compiled from various public sources and may vary from official statistics.
"""
        return description.strip()

    def _generate_youtube_tags(self, topic: str, channel: str = "PlayOwnAi") -> list:
        """Generate SEO-optimized YouTube tags"""

        base_tags = [
            "data visualization",
            "market analysis",
            "tech trends",
            "industry insights",
            "animated chart",
            "bar chart race",
            "data animation",
            channel,
        ]

        topic_tags = [
            topic.lower(),
            f"{topic.lower()} trends",
            f"{topic.lower()} comparison",
            f"{topic.lower()} evolution",
            f"{topic.lower()} market share",
            f"{topic.lower()} analysis",
            f"{topic.lower()} ranking",
            f"{topic.lower()} history",
        ]

        year_tags = [
            f"{datetime.now().year}",
            f"{datetime.now().year - 1}",
            "trend analysis",
            "market trends",
            "data driven",
            "visualization",
        ]

        all_tags = base_tags + topic_tags + year_tags
        return all_tags[:25]

    def _generate_youtube_chapters(self, start_year: int, end_year: int, video_duration: float) -> str:
        """Generate YouTube chapters/timestamps"""

        total_years = end_year - start_year + 1
        seconds_per_year = video_duration / total_years if total_years > 0 else 5

        chapters = []
        chapters.append("0:00 Introduction")

        for year in range(start_year, end_year + 1):
            timestamp_seconds = int((year - start_year) * seconds_per_year)
            minutes = timestamp_seconds // 60
            seconds = timestamp_seconds % 60
            chapters.append(f"{minutes:02d}:{seconds:02d} {year}")

        conclusion_seconds = int(video_duration)
        minutes = conclusion_seconds // 60
        seconds = conclusion_seconds % 60
        chapters.append(f"{minutes:02d}:{seconds:02d} Conclusion")

        return "\n".join(chapters)

    def _get_fallback_narration(self, topic: str, start_year: int, end_year: int, channel: str = "PlayOwnAi") -> str:
        """Fallback narration if CSV reading fails"""
        return (
            f"Welcome to @{channel}. Today, we're exploring {topic} Race from {start_year} to {end_year}. "
            "Only for basic idea about trending. Let's see how the landscape evolved over time. "
            f"The evolution of technology and trends continues. Subscribe to @{channel} for more insights."
        )

    def _cleanup_and_rename(self, output_dir: str, video_formats: list, channel: str, topic: str):
        """
        Always runs after crew completes (regardless of generate_youtube_metadata flag).
        1. Rename Final_[fmt].mp4 → {channel}_{topic_slug}_{fmt}.mp4
        2. Delete all known temp mp4/mp3 files per format
        3. Glob delete any remaining _temp_*, _norm_*, _stage_* files
        """
        import re, glob as _glob

        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"
        print(f"[YTMetadata] 🧹 Cleanup starting — formats={video_formats} topic_slug={topic_slug}")

        # ── Step 1: Rename Final → channel_topic_fmt FIRST (before deleting) ──
        # Build full list of formats to process:
        # - video_formats from inputs (may be incomplete if agent only passed one)
        # - PLUS any Final_*.mp4 / Merge_bar_race_*.mp4 found via glob (catches all)
        import glob as _rglob
        glob_fmts = set()
        for pat in [f"Final_*.mp4", f"Merge_bar_race_*.mp4"]:
            for p in _rglob.glob(os.path.join(output_dir, pat)):
                name = os.path.basename(p)
                # Extract format: Final_HD.mp4 → HD, Merge_bar_race_Shorts.mp4 → Shorts
                m = re.search(r"(?:Final_|Merge_bar_race_)(.+)\.mp4$", name)
                if m:
                    glob_fmts.add(m.group(1))
        all_fmts = list(dict.fromkeys(video_formats + sorted(glob_fmts)))  # preserve order, no dupes
        print(f"[YTMetadata]   Rename targets: {all_fmts} (inputs={video_formats} glob={sorted(glob_fmts)})")

        for fmt in all_fmts:
            fmt = fmt.strip()
            dst = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
            # Skip if final renamed file already exists
            if os.path.exists(dst):
                size_mb = os.path.getsize(dst) / (1024 * 1024)
                print(f"[YTMetadata] ⏭️  Skipping rename — {os.path.basename(dst)} already exists ({size_mb:.1f} MB)")
                continue
            candidates = [
                os.path.join(output_dir, f"Final_{fmt}.mp4"),
                os.path.join(output_dir, f"Merge_bar_race_{fmt}.mp4"),
            ]
            src = next((p for p in candidates if os.path.exists(p)), None)
            if src:
                os.rename(src, dst)
                size_mb = os.path.getsize(dst) / (1024 * 1024)
                print(f"[YTMetadata] ✅ Renamed: {os.path.basename(src)} → {os.path.basename(dst)} ({size_mb:.1f} MB)")
            else:
                print(f"[YTMetadata]    No source found for fmt={fmt}")

        # ── Step 2: Delete known temp files — scan ALL formats via glob ──
        _temp_prefixes = [
            "intro_", "bar_race_", "definition_video_", "Merge_bar_race_", "Final_"
        ]
        _temp_exts = (".mp4", ".mp3")
        for f in os.listdir(output_dir):
            fpath = os.path.join(output_dir, f)
            if not os.path.isfile(fpath):
                continue
            if not any(f.endswith(ext) for ext in _temp_exts):
                continue
            if any(f.startswith(pfx) for pfx in _temp_prefixes):
                os.remove(fpath)
                print(f"[YTMetadata] 🗑️  Deleted: {f}")

        # ── Step 3: Glob delete any remaining temp/norm/stage files ──
        temp_patterns = [
            "_temp_*.mp4", "_norm_*.mp4", "_stage*.mp4",
            "_concat_*.txt", "*_cc_en.txt",
        ]
        for pat in temp_patterns:
            for path in _glob.glob(os.path.join(output_dir, pat)):
                os.remove(path)
                print(f"[YTMetadata] 🗑️  Glob deleted: {os.path.basename(path)}")

        print(f"[YTMetadata] 🧹 Cleanup done")

        print(f"[YTMetadata] 🧹 Cleanup done")
