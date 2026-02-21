import os
import json
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from datetime import datetime

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
        t0 = _time.time()

        print(f"[YTMetadata] ▶ Starting — topic='{topic}' channel='{channel}'")
        print(f"[YTMetadata]   output_dir : {output_dir}")
        print(f"[YTMetadata]   years      : {start_year}–{end_year}")
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

            fmts = video_formats if video_formats else ["Shorts"]
            title = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
            tags  = self._generate_youtube_tags(topic, channel=channel)
            print(f"[YTMetadata]   • Title: {title}")
            print(f"[YTMetadata]   • Tags: {len(tags)} tags")

            fmt_results = []
            for fmt in fmts:
                fmt = fmt.strip()
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

        # --- Final cleanup: delete temp files, rename merged videos ---
        self._cleanup_and_rename(output_dir, video_formats or [], channel, topic)

        return "\n\n".join(results)

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
        """Write JSON + TXT metadata files to output_dir, with optional per-format suffix."""
        metadata = {
            "title": title,
            "description": description,
            "tags": tags,
            "chapters": chapters,
            "category": "Science & Technology",
            "language": "en",
            "created_at": datetime.now().isoformat()
        }
        suffix = f"_{fmt}" if fmt else ""
        metadata_json_path = f"{output_dir}/YT_Metadata{suffix}.json"
        with open(metadata_json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        metadata_txt_path = f"{output_dir}/YT_Metadata{suffix}.txt"
        with open(metadata_txt_path, 'w', encoding='utf-8') as f:
            f.write(f"TITLE:\n{title}\n\n")
            f.write(f"DESCRIPTION:\n{description}\n\n")
            f.write(f"TAGS:\n{', '.join(tags)}\n\n")
            f.write(f"CHAPTERS:\n{chapters}\n")
        return f"🎬 [{fmt or'all'}] YT_Metadata{suffix}.json + YT_Metadata{suffix}.txt"
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
        After all tasks complete:
        1. Delete temp files: intro_*, bar_race_* videos & audio
        2. Rename Merge_bar_race_[fmt].mp4 → {channel}_{topic_slug}_{fmt}.mp4
        """
        import re
        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"

        print(f"[YTMetadata] 🧹 Cleanup starting — formats={video_formats} topic_slug={topic_slug}")

        # Files to delete per format
        for fmt in video_formats:
            fmt = fmt.strip()
            to_delete = [
                os.path.join(output_dir, f"intro_{fmt}.mp4"),
                os.path.join(output_dir, f"bar_race_{fmt}.mp4"),
                os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3"),
            ]
            for path in to_delete:
                if os.path.exists(path):
                    os.remove(path)
                    print(f"[YTMetadata] 🗑️  Deleted: {os.path.basename(path)}")
                else:
                    print(f"[YTMetadata]    Skip (not found): {os.path.basename(path)}")

        # Rename Merge_bar_race_[fmt].mp4 → {channel}_{topic_slug}_{fmt}.mp4
        for fmt in video_formats:
            fmt = fmt.strip()
            src = os.path.join(output_dir, f"Merge_bar_race_{fmt}.mp4")
            dst = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
            if os.path.exists(src):
                os.rename(src, dst)
                size_mb = os.path.getsize(dst) / (1024 * 1024)
                print(f"[YTMetadata] ✅ Renamed: Merge_bar_race_{fmt}.mp4 → {os.path.basename(dst)} ({size_mb:.1f} MB)")
            else:
                print(f"[YTMetadata]    Skip rename (not found): Merge_bar_race_{fmt}.mp4")

        print(f"[YTMetadata] 🧹 Cleanup done")
