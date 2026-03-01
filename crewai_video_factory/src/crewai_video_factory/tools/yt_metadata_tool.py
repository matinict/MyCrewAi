import os
import csv
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
# Kept top 20 by actual viewer data (YouTube 20-language limit)
# Disabled (low views): 'cs','et','gu','mr','sr','te','ur','zh-cn'→replaced by 'zh-Hans'
LANGUAGES = [
    'ar', 'es', 'pt', 'id', 'tr', 'vi', 'fr', 'ru',
    'ko', 'hi', 'bn', 'it', 'fa', 'th', 'ja', 'pl',
    'uk', 'de', 'ta', 'zh-cn'
]
LANG_NAMES = {
    'ar':'Arabic',
    'es':'Spanish',
    'pt':'Portuguese',
    'id':'Indonesian',
    'tr':'Turkish',
    'vi':'Vietnamese',
    'fr':'French',
    'ru':'Russian',
    'ko':'Korean',
    'hi':'Hindi',
    'bn':'Bengali',
    'it':'Italian',
    'fa':'Persian',
    'th':'Thai',
    'ja':'Japanese',
    'pl':'Polish',
    'uk':'Ukrainian',
    'de':'German',
    'ta':'Tamil',
    'zh-cn':'Chinese',
}


def _google_translate(text: str, dest: str, retries: int = 3) -> str:
    """Translate text using Google Translate free endpoint. No API key needed."""
    if not text or not text.strip():
        return text

    # Chunk long text (Google free endpoint limit ~4000 chars)
    if len(text) > 4000:
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
                    result = " ".join(part[0] for part in data[0] if part[0])
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
    # ── NEW: Thumbnail generation ────────────────────────────────────────
    generate_thumbnail: bool = Field(default=True, description="Whether to generate thumbnail images")
    channel: str = Field(default="PlayOwnAi", description="YouTube channel name without @ prefix")
    channel_lower: str = Field(default="playownai", description="Lowercase channel name for LinkedIn/URLs")
    website: str = Field(default="youtube.com/@PlayOwnAi", description="Website URL for description")
    video_formats: list = Field(default=[], description="Video formats used (HD, Shorts, etc.) — for cleanup")
    fps: float = Field(default=4.9, description="Seconds per period (Shorts speed)")
    fps_hd_offset: float = Field(default=1.0, description="Multiplier for HD duration vs Shorts")
    n_periods: int = Field(default=0, description="Number of data rows/periods in CSV (0=auto-detect)")
    csv_path: str = Field(default="", description="Path to CSV file for thumbnail generation")


class YouTubeMetadataTool(BaseTool):
    name: str = "YouTube Metadata Generator"
    description: str = (
        "Generates narration text file (cc_en.txt), YouTube metadata (title, description, tags, chapters) "
        "with SEO optimization, AND thumbnail images (PNG/JPG 1920x1080). "
        "All values dynamic from data.json (channel, year range, website)."
    )
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
        generate_thumbnail: bool = True,  # NEW
        channel: str = "PlayOwnAi",
        channel_lower: str = "playownai",
        website: str = "youtube.com/@PlayOwnAi",
        video_formats: list = None,
        fps: float = 4.9,
        fps_hd_offset: float = 1.0,
        n_periods: int = 0,
        csv_path: str = "",
    ) -> str:
        import time as _time
        import re as _vre
        t0 = _time.time()

        print(f"[YTMetadata] 🔖 v2.0 — structured YT/{{fmt}}/MD|CC/ output + Thumbnails")

        # ── Normalize video_formats FIRST ────────────────────────────────
        if not video_formats:
            video_formats = ["HD"]
        elif isinstance(video_formats, str):
            video_formats = [v.strip() for v in _vre.findall(r"[A-Za-z0-9]+", video_formats)
                             if v not in ("true", "false", "null", "list")]
        _valid = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
        video_formats = [f for f in video_formats if f in _valid] or ["HD"]

        clean_filename = filename.strip().replace("/", " ").replace("\\", " ")

        print(f"[YTMetadata] ▶ Starting — topic='{topic}' filename='{clean_filename}' channel='{channel}'")
        print(f"[YTMetadata]   output_dir : {output_dir}")
        print(f"[YTMetadata]   years      : {start_year}–{end_year}  formats: {video_formats}")
        print(f"[YTMetadata]   narration  : {generate_narration} | metadata: {generate_youtube_metadata} | thumbnail: {generate_thumbnail}")

        os.makedirs(output_dir, exist_ok=True)
        results = []

        # ── Migrate old flat YT/ structure ───────────────────────────────
        self._migrate_old_yt_structure(output_dir, video_formats)

        # ── PART 1: Generate Narration ───────────────────────────────────
        if generate_narration:
            print(f"[YTMetadata] 📝 Step 1/3 — Generating narration text …")
            t1 = _time.time()
            narration_result = self._generate_narration_file(
                topic, start_year, end_year, output_dir, clean_filename, channel=channel)
            print(f"[YTMetadata] ✅ Narration done in {_time.time()-t1:.1f}s → {narration_result}")
            results.append(narration_result)

        # ── PART 2: Generate YouTube Metadata ────────────────────────────
        if generate_youtube_metadata:
            print(f"[YTMetadata] 🎬 Step 2/3 — Generating YouTube metadata per format …")
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

            fmts = video_formats
            title = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
            tags = self._generate_youtube_tags(topic, channel=channel)
            print(f"[YTMetadata]   • Title: {title}")
            print(f"[YTMetadata]   • Tags: {len(tags)} tags")

            fmt_results = []
            for fmt in fmts:
                fmt = fmt.strip()
                existing = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
                if os.path.exists(existing):
                    print(f"[YTMetadata]   • [{fmt}] ⏭️  Skipping — YT/{fmt}/MD/en.json already exists")
                    fmt_results.append(f"⏭️  [{fmt}] Skipped (already exists)")
                    continue
                is_portrait = fmt in ("Shorts", "ShortsHD", "Shorts4K")
                fmt_spp = fps if is_portrait else fps * fps_hd_offset
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

        # ── PART 3: Generate Thumbnail (NEW - INTEGRATED) ────────────────
        if generate_thumbnail:
            print(f"[YTMetadata] 🖼️  Step 3/3 — Generating thumbnail images …")
            t3 = _time.time()

            # Auto-detect CSV path
            if not csv_path:
                csv_path = f"output/{clean_filename}.csv"

            thumb_result = self._generate_thumbnail(
                topic, clean_filename, output_dir, channel,
                csv_path, start_year, end_year)
            print(f"[YTMetadata] ✅ Thumbnail done in {_time.time()-t3:.1f}s → {thumb_result}")
            results.append(thumb_result)
        else:
            results.append("⏭️  Thumbnail generation skipped")

        # ── Translate CC narration files ─────────────────────────────────
        print(f"[YTMetadata] 📝 Step CC — Translating CC narration files …")
        cc_result = self._translate_cc_files(output_dir, video_formats)
        results.append(cc_result)

        # ── Final cleanup + rename ───────────────────────────────────────
        self._cleanup_and_rename(output_dir, video_formats, channel, topic)

        print(f"[YTMetadata] 🏁 All steps done in {_time.time()-t0:.1f}s")
        return "\n\n".join(results) if results else "✅ Cleanup and rename completed."

    # ──────────────────────────────────────────────────────────────────────
    # NARRATION GENERATION
    # ──────────────────────────────────────────────────────────────────────
    def _generate_narration_file(self, topic: str, start_year: int, end_year: int,
                                  output_dir: str, clean_filename: str, channel: str = "PlayOwnAi") -> str:
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

                narration_text = "  ".join(narration_parts)

            except Exception as e:
                print(f"[WARN] CSV reading failed: {e}")
                narration_text = self._get_fallback_narration(topic, start_year, end_year, channel=channel)
        else:
            narration_text = self._get_fallback_narration(topic, start_year, end_year, channel=channel)

        narration_file_path = f"{output_dir}/cc_en.txt"
        with open(narration_file_path, 'w', encoding='utf-8') as f:
            f.write(narration_text)

        return f"📝 Narration text saved to: cc_en.txt"

    # ──────────────────────────────────────────────────────────────────────
    # THUMBNAIL GENERATION (INTEGRATED)
    # ──────────────────────────────────────────────────────────────────────
    def _generate_thumbnail(self, topic, filename, output_dir, channel,
                           csv_path, start_year, end_year):
        """Generate PNG & JPG thumbnail images (1920x1080 Full HD)."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "⚠️  PIL not installed. Install: pip install Pillow"

        # Check if CSV exists
        if not os.path.exists(csv_path):
            return f"❌ CSV file not found at {csv_path}"

        os.makedirs(output_dir, exist_ok=True)

        # Full HD: 1920x1080
        width, height = 1920, 1080
        png_path = os.path.join(output_dir, f"{filename}.png")
        jpg_path = os.path.join(output_dir, f"{filename}.jpg")

        # Smart skip: both files already exist
        if os.path.exists(png_path) and os.path.exists(jpg_path):
            png_kb = os.path.getsize(png_path) // 1024
            jpg_kb = os.path.getsize(jpg_path) // 1024
            print(f"[YTMetadata] ⏭️  Thumbnail smart skip — both files already exist")
            return (
                f"⏭️  Thumbnails already exist (skipped):\n"
                f"   PNG: {png_path} ({png_kb} KB)\n"
                f"   JPG: {jpg_path} ({jpg_kb} KB)"
            )

        try:
            # Read CSV data
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if not rows:
                return f"❌ CSV file is empty: {csv_path}"

            # Get column names (skip first column which is time period)
            columns = list(rows[0].keys())
            time_col = columns[0]
            data_cols = columns[1:6]  # Use first 5 data columns

            # Get latest values for visualization
            latest_row = rows[-1]
            latest_values = []
            for col in data_cols:
                try:
                    val = float(latest_row.get(col, 0))
                    latest_values.append(val)
                except (ValueError, TypeError):
                    latest_values.append(0)

            # Create image
            img = Image.new('RGB', (width, height), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)

            # Load fonts
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56)
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
            except OSError:
                title_font = ImageFont.load_default()
                subtitle_font = ImageFont.load_default()
                small_font = ImageFont.load_default()

            # Colors
            primary_color = (255, 107, 107)
            secondary_color = (74, 144, 226)
            text_color = (255, 255, 255)
            bar_colors = [
                (255, 107, 107), (74, 144, 226), (76, 175, 80),
                (255, 193, 7), (156, 39, 176),
            ]

            # Draw background gradient
            for y in range(height):
                ratio = y / height
                r = int(15 + (25 - 15) * ratio)
                g = int(23 + (45 - 23) * ratio)
                b = int(42 + (70 - 42) * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            # Draw channel name (top)
            channel_text = f"@{channel}"
            bbox = draw.textbbox((0, 0), channel_text, font=subtitle_font)
            ch_width = bbox[2] - bbox[0]
            draw.text(((width - ch_width) // 2, 50), channel_text, fill=secondary_color, font=subtitle_font)

            # Draw topic title (center-top)
            title_lines = []
            words = topic.split()
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=title_font)
                if bbox[2] - bbox[0] > width - 120:
                    if current_line:
                        title_lines.append(' '.join(current_line))
                        current_line = [word]
                    else:
                        current_line = [word]
                else:
                    current_line.append(word)
            if current_line:
                title_lines.append(' '.join(current_line))

            title_y = 180
            for line in title_lines:
                bbox = draw.textbbox((0, 0), line, font=title_font)
                line_width = bbox[2] - bbox[0]
                draw.text(((width - line_width) // 2, title_y), line, fill=text_color, font=title_font)
                title_y += 120

            # Draw bar chart (bottom section)
            chart_y = 620
            bar_height = 60
            bar_spacing = 20
            max_val = max(latest_values) if latest_values else 100
            if max_val == 0:
                max_val = 100

            chart_x_start = 150
            chart_width = width - 300

            for idx, (col, val) in enumerate(zip(data_cols, latest_values)):
                bar_width = (val / max_val) * chart_width if max_val > 0 else 0
                bar_color = bar_colors[idx % len(bar_colors)]
                bar_y = chart_y + idx * (bar_height + bar_spacing)
                draw.rectangle(
                    [(chart_x_start, bar_y), (chart_x_start + bar_width, bar_y + bar_height)],
                    fill=bar_color
                )
                label_text = f"{col}: {int(val)}"
                draw.text((chart_x_start + 15, bar_y + 10), label_text, fill=text_color, font=small_font)

            # ── DYNAMIC FOOTER TEXT (from data.json) ──
            footer_text = f"Bar Race {start_year}–{end_year}"
            bbox = draw.textbbox((0, 0), footer_text, font=small_font)
            footer_width = bbox[2] - bbox[0]
            draw.text(((width - footer_width) // 2, height - 60), footer_text, fill=primary_color, font=small_font)

            # Save PNG
            img.save(png_path, 'PNG')
            png_size_kb = os.path.getsize(png_path) // 1024

            # Save JPG
            img.save(jpg_path, 'JPEG', quality=95)
            jpg_size_kb = os.path.getsize(jpg_path) // 1024

            return (
                f"✅ Thumbnails Generated\n"
                f"   Resolution: {width}x{height}px (Full HD)\n"
                f"   PNG: {png_path} ({png_size_kb} KB)\n"
                f"   JPG: {jpg_path} ({jpg_size_kb} KB)\n"
                f"   Year Range: {start_year}–{end_year}\n"
                f"   Channel: @{channel}"
            )

        except Exception as e:
            return f"❌ Thumbnail generation failed: {e}"

    # ──────────────────────────────────────────────────────────────────────
    # YOUTUBE METADATA GENERATION
    # ──────────────────────────────────────────────────────────────────────
    def _generate_youtube_metadata(self, topic: str, start_year: int, end_year: int,
                                    video_duration: float, output_dir: str, clean_filename: str,
                                    channel: str = "PlayOwnAi", channel_lower: str = "playownai",
                                    website: str = "youtube.com/@PlayOwnAi") -> str:
        """Generate YouTube metadata with SEO optimization (legacy path)."""
        title = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
        description = self._generate_youtube_description(topic, start_year, end_year, video_duration,
                                                          channel=channel, channel_lower=channel_lower,
                                                          website=website)
        tags = self._generate_youtube_tags(topic, channel=channel)
        chapters = self._generate_youtube_chapters(start_year, end_year, video_duration)
        return self._write_metadata_files(topic, title, description, tags, chapters, output_dir)

    def _write_metadata_files(self, topic: str, title: str, description: str, tags: list,
                              chapters: str, output_dir: str, fmt: str = "") -> str:
        """Write metadata files into structured YT/{fmt}/MD/ subfolder."""
        fmt_label = fmt if fmt else "Video"
        md_dir = os.path.join(output_dir, "YT", fmt_label, "MD")
        os.makedirs(md_dir, exist_ok=True)

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
        en_json_path = os.path.join(md_dir, "en.json")
        if not os.path.exists(en_json_path):
            with open(en_json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"[YTMetadata]   📄 Saved: YT/{fmt_label}/MD/en.json")
        else:
            print(f"[YTMetadata]   ⏭️  Exists: YT/{fmt_label}/MD/en.json")

        # ── English TXT ──
        en_txt_path = os.path.join(md_dir, "en.txt")
        if not os.path.exists(en_txt_path):
            with open(en_txt_path, 'w', encoding='utf-8') as f:
                f.write(f"TITLE:\n{title}\n\n")
                f.write(f"DESCRIPTION:\n{description}\n\n")
                f.write(f"TAGS:\n{', '.join(tags)}\n\n")
                f.write(f"CHAPTERS:\n{chapters}\n")
            print(f"[YTMetadata]   📄 Saved: YT/{fmt_label}/MD/en.txt")
        else:
            print(f"[YTMetadata]   ⏭️  Exists: YT/{fmt_label}/MD/en.txt")

        # ── Translated TXT files ──
        print(f"[YTMetadata]   🌍 Translating MD to {len(LANGUAGES)} languages …")
        ok_count = 0
        for lang_code in LANGUAGES:
            txt_path = os.path.join(md_dir, f"{lang_code}.txt")
            if os.path.exists(txt_path):
                print(f"[YTMetadata]     ⏭️  YT/{fmt_label}/MD/{lang_code}.txt exists")
                ok_count += 1
                continue
            try:
                t_title = _google_translate(title, lang_code)
                t_description = _google_translate(description, lang_code)
                t_tags_str = _google_translate(", ".join(tags), lang_code)
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"TITLE:\n{t_title}\n\n")
                    f.write(f"DESCRIPTION:\n{t_description}\n\n")
                    f.write(f"TAGS:\n{t_tags_str}\n\n")
                    f.write(f"CHAPTERS:\n{chapters}\n")
                print(f"[YTMetadata]     ✅ YT/{fmt_label}/MD/{lang_code}.txt ({LANG_NAMES.get(lang_code, lang_code)})")
                ok_count += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"[YTMetadata]     ❌ {lang_code}: {e}")

        total = len(LANGUAGES) + 2
        return f"🎬 [{fmt_label}] {ok_count+2}/{total} files in YT/{fmt_label}/MD/"

    def _generate_youtube_title(self, topic: str, start_year: int, end_year: int,
                                 channel: str = "PlayOwnAi") -> str:
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

    def _generate_youtube_description(self, topic: str, start_year: int, end_year: int,
                                       video_duration: float, channel: str = "PlayOwnAi",
                                       channel_lower: str = "playownai",
                                       website: str = "youtube.com/@PlayOwnAi") -> str:
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

    def _get_fallback_narration(self, topic: str, start_year: int, end_year: int,
                                 channel: str = "PlayOwnAi") -> str:
        """Fallback narration if CSV reading fails"""
        return (
            f"Welcome to @{channel}. Today, we're exploring {topic} Race from {start_year} to {end_year}.  "
            "Only for basic idea about trending. Let's see how the landscape evolved over time.  "
            f"The evolution of technology and trends continues. Subscribe to @{channel} for more insights."
        )

    # ──────────────────────────────────────────────────────────────────────
    # MIGRATION & CLEANUP (unchanged from original)
    # ──────────────────────────────────────────────────────────────────────
    def _migrate_old_yt_structure(self, output_dir: str, video_formats: list):
        """One-time migration: move old flat YT/ files into new nested structure."""
        import glob as _glob, re as _re
        yt_dir = os.path.join(output_dir, "YT")
        if not os.path.exists(yt_dir):
            return
        moved = 0
        for old_path in _glob.glob(os.path.join(yt_dir, "Metadata_*.json")) + \
                        _glob.glob(os.path.join(yt_dir, "Metadata_*.txt")):
            name = os.path.basename(old_path)
            m = _re.match(r"Metadata_([^_]+(?:HD|4K|8K|2K)?)_([A-Za-z-]+)\.(json|txt)$", name)
            if not m:
                m = _re.match(r"Metadata_([A-Za-z0-9]+)_([A-Za-z-]+)\.(json|txt)$", name)
            if not m:
                continue
            fmt_part, lang_part, ext = m.group(1), m.group(2), m.group(3)
            lang_norm = lang_part.lower()
            if lang_norm == "en" and ext == "json":
                new_name = "en.json"
            else:
                new_name = f"{lang_norm}.txt"
            md_dir = os.path.join(yt_dir, fmt_part, "MD")
            os.makedirs(md_dir, exist_ok=True)
            new_path = os.path.join(md_dir, new_name)
            if not os.path.exists(new_path):
                os.rename(old_path, new_path)
                print(f"[YTMetadata] 🔄 Migrated: YT/{name} → YT/{fmt_part}/MD/{new_name}")
                moved += 1
            else:
                os.remove(old_path)
                print(f"[YTMetadata] 🗑️  Removed old (new exists): {name}")

        for old_path in _glob.glob(os.path.join(yt_dir, "cc_*.txt")):
            name = os.path.basename(old_path)
            m = _re.match(r"cc_([A-Za-z0-9]+)_([A-Za-z-]+)\.txt$", name)
            if not m:
                continue
            part1, lang = m.group(1), m.group(2)
            known = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
            fmt_part = part1 if part1 in known else "standard"
            cc_dir = os.path.join(yt_dir, fmt_part, "CC")
            os.makedirs(cc_dir, exist_ok=True)
            new_name = f"{lang}.txt"
            new_path = os.path.join(cc_dir, new_name)
            if not os.path.exists(new_path):
                os.rename(old_path, new_path)
                print(f"[YTMetadata] 🔄 Migrated: YT/{name} → YT/{fmt_part}/CC/{new_name}")
                moved += 1
            else:
                os.remove(old_path)
                print(f"[YTMetadata] 🗑️  Removed old (new exists): {name}")

        if moved:
            print(f"[YTMetadata] ✅ Migration complete: {moved} files moved to new structure")

    def _translate_cc_files(self, output_dir: str, video_formats: list) -> str:
        """Translate CC narration files to 31 languages."""
        translated_total = 0
        skipped_total = 0
        report = []
        import glob as _glob

        cc_sources = []
        for fmt in video_formats:
            merged_matches = [
                p for p in _glob.glob(os.path.join(output_dir, f"*_{fmt}_cc_en.txt"))
                if not os.path.basename(p).startswith("bar_race_")
                and not os.path.basename(p).startswith("intro_")
                and not os.path.basename(p).startswith("definition_video_")
            ]
            if merged_matches:
                cc_sources.append((merged_matches[0], fmt))
                print(f"[YTMetadata] 📝 Found merged CC: {os.path.basename(merged_matches[0])}")
                continue
            bar_race_cc = os.path.join(output_dir, f"bar_race_{fmt}_cc_en.txt")
            if os.path.exists(bar_race_cc):
                cc_sources.append((bar_race_cc, fmt))
                print(f"[YTMetadata] 📝 Found bar race CC: bar_race_{fmt}_cc_en.txt")
                continue
            print(f"[YTMetadata] ⚠️  No CC file found for fmt={fmt}")

        if not cc_sources:
            print(f"[YTMetadata] ⚠️  No CC files found in {output_dir}")
            return "⚠️  No CC source files found to translate"

        for src_path, fmt in cc_sources:
            with open(src_path, "r", encoding="utf-8") as f:
                en_text = f.read().strip()
            if not en_text:
                print(f"[YTMetadata]   ⚠️  {os.path.basename(src_path)} is empty — skipping")
                continue

            cc_dir = os.path.join(output_dir, "YT", fmt, "CC")
            os.makedirs(cc_dir, exist_ok=True)

            en_out = os.path.join(cc_dir, "en.txt")
            if not os.path.exists(en_out):
                with open(en_out, "w", encoding="utf-8") as f:
                    f.write(en_text)
                print(f"[YTMetadata]   📄 Saved: YT/{fmt}/CC/en.txt")
            else:
                print(f"[YTMetadata]   ⏭️  Exists: YT/{fmt}/CC/en.txt")

            print(f"[YTMetadata]   🌍 Translating YT/{fmt}/CC/ to {len(LANGUAGES)} languages …")
            ok = 1
            for lang_code in LANGUAGES:
                out_path = os.path.join(cc_dir, f"{lang_code}.txt")
                if os.path.exists(out_path):
                    print(f"[YTMetadata]     ⏭️  YT/{fmt}/CC/{lang_code}.txt exists")
                    skipped_total += 1
                    ok += 1
                    continue
                try:
                    translated = _google_translate(en_text, lang_code)
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(translated)
                    print(f"[YTMetadata]     ✅ YT/{fmt}/CC/{lang_code}.txt ({LANG_NAMES.get(lang_code, lang_code)})")
                    ok += 1
                    translated_total += 1
                    import time as _t; _t.sleep(0.2)
                except Exception as e:
                    print(f"[YTMetadata]     ❌ {fmt}/CC/{lang_code}: {e}")

            total = len(LANGUAGES) + 1
            report.append(f"✅ [{fmt}] {ok}/{total} CC files in YT/{fmt}/CC/")

        summary = (
            f"📝 CC translations: {translated_total} new, {skipped_total} skipped\n"
            + "\n".join(report)
        )
        print(f"[YTMetadata] {summary}")
        return summary

    def _cleanup_and_rename(self, output_dir: str, video_formats: list, channel: str, topic: str):
        """Always runs after crew completes. Rename Final_*.mp4 → {channel}_{topic_slug}_{fmt}.mp4"""
        import re, glob as _glob

        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"
        print(f"[YTMetadata] 🧹 Cleanup starting — formats={video_formats} topic_slug={topic_slug}")

        import glob as _rglob
        glob_fmts = set()
        for pat in [f"Final_*.mp4", f"Merge_bar_race_*.mp4"]:
            for p in _rglob.glob(os.path.join(output_dir, pat)):
                name = os.path.basename(p)
                m = re.search(r"(?:Final_|Merge_bar_race_)(.+)\.mp4$", name)
                if m:
                    glob_fmts.add(m.group(1))
        all_fmts = list(dict.fromkeys(video_formats + sorted(glob_fmts)))
        print(f"[YTMetadata]   Rename targets: {all_fmts} (inputs={video_formats} glob={sorted(glob_fmts)})")

        for fmt in all_fmts:
            fmt = fmt.strip()
            dst = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
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

        _temp_prefixes = ["intro_", "bar_race_", "definition_video_", "Merge_bar_race_", "Final_"]
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

        _segment_cc_prefixes = ["intro_", "bar_race_", "definition_video_"]
        for f in os.listdir(output_dir):
            fpath = os.path.join(output_dir, f)
            if not os.path.isfile(fpath):
                continue
            if f == "cc_en.txt":
                os.remove(fpath)
                print(f"[YTMetadata] 🗑️  Deleted old narration: {f}")
                continue
            if f.endswith("_cc_en.txt") and any(f.startswith(pfx) for pfx in _segment_cc_prefixes):
                os.remove(fpath)
                print(f"[YTMetadata] 🗑️  Deleted segment CC: {f}")

        temp_patterns = ["_temp_*.mp4", "_norm_*.mp4", "_stage*.mp4", "_concat_*.txt"]
        for pat in temp_patterns:
            for path in _glob.glob(os.path.join(output_dir, pat)):
                os.remove(path)
                print(f"[YTMetadata] 🗑️  Glob deleted: {os.path.basename(path)}")

        print(f"[YTMetadata] 🧹 Cleanup done")
