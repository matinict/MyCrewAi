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

# ── Language lists ────────────────────────────────────────────────────────────
# Priority-ordered by viewer analytics (35 non-English languages).
# Slice with LANGUAGES[:n] for both MD and CC.

# ── Language config — loaded from data/lang.json ─────────────────────────────
# Edit data/lang.json to change language priority, add/remove languages, or
# adjust which languages get CC subtitles vs metadata-only.

def _load_lang_config():
    """Load language list from data/lang.json, sorted by rank.
    Falls back to a minimal hardcoded list if the file is missing.
    """
    import pathlib
    # Resolve relative to this file so it works from any CWD
    _here    = pathlib.Path(__file__).parent
    _candidates = [
        _here / "data" / "lang.json",
        pathlib.Path("data/lang.json"),
    ]
    for _p in _candidates:
        if _p.exists():
            try:
                with open(_p, encoding="utf-8") as _f:
                    _cfg = json.load(_f)
                    _langs = sorted(_cfg["languages"], key=lambda x: x["rank"])
                    _codes     = [l["code"] for l in _langs]
                    _names     = {l["code"]: l["name"] for l in _langs}
                    _yt_map    = {l["code"]: l["yt_code"] for l in _langs}
                    # aliases: zh → zh-hans, etc.
                    for alias, target in _cfg.get("aliases", {}).items():
                        if alias not in _names:
                            _names[alias]  = _names.get(target, target)
                        if alias not in _yt_map:
                            _yt_map[alias] = _yt_map.get(target, target)
                    print(f"[LangConfig] Loaded {len(_codes)} languages from {_p}")
                    return _codes, _names, _yt_map
            except Exception as _e:
                print(f"[LangConfig] Failed to load {_p}: {_e} — using fallback")
                break
    # ── Minimal fallback (top 10 only) ───────────────────────────────────────
    print("[LangConfig] data/lang.json not found — using built-in fallback (top 10)")
    _codes = ['es', 'ar', 'pt', 'id', 'tr', 'vi', 'fr', 'ru', 'hi', 'ko']
    _names = {
        'es': 'Spanish', 'ar': 'Arabic',    'pt': 'Portuguese', 'id': 'Indonesian',
        'tr': 'Turkish', 'vi': 'Vietnamese', 'fr': 'French',     'ru': 'Russian',
        'hi': 'Hindi',   'ko': 'Korean',
    }
    _yt_map = {c: c for c in _codes}
    return _codes, _names, _yt_map

LANGUAGES, LANG_NAMES, _LANG_YT_MAP = _load_lang_config()

# ── Translation helper ────────────────────────────────────────────────────────

def _google_translate(text: str, dest: str, retries: int = 3) -> str:
    if not text or not text.strip():
        return text
    if len(text) > 4000:
        chunks = text.split("\n\n")
        return "\n\n".join(_google_translate(c, dest, retries) for c in chunks)
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
                    return " ".join(part[0] for part in data[0] if part[0])
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(1.5)
                else:
                    print(f"[YTMetadata] Translation failed ({dest}): {e}")
                    return text
    except Exception as e:
        print(f"[YTMetadata] Translation error ({dest}): {e}")
        return text

# ── Schema ────────────────────────────────────────────────────────────────────

class YouTubeMetadataToolInput(BaseModel):
    topic: str                      = Field(...,           description="Topic/title for the video")
    filename: str                   = Field(...,           description="Base filename slug")
    output_dir: str                 = Field(...,           description="Output directory")
    start_year: int                 = Field(default=2015)
    end_year: int                   = Field(default=2026)
    video_duration: float           = Field(default=60.0,  description="Legacy field")
    generate_narration: bool        = Field(default=True)
    generate_youtube_metadata: bool = Field(default=True)
    generate_thumbnail: bool        = Field(default=True)
    channel: str                    = Field(default="PlayOwnAi")
    channel_lower: str              = Field(default="playownai")
    website: str                    = Field(default="youtube.com/@PlayOwnAi")
    video_formats: list             = Field(default=[],    description="Pipeline tokens or real fmt names")
    fps: float                      = Field(default=4.9)
    fps_hd_offset: float            = Field(default=1.0)
    n_periods: int                  = Field(default=0)
    csv_path: str                   = Field(default="")
    yt_metadata_lang: int           = Field(default=35)
    yt_cc_lang: int                 = Field(default=20)
    animation_video_formats: list   = Field(
        default=[],
        description=(
            "Real format names (HD, Shorts, …) for the 'animation' branch  "
            "AND for per-fmt debate CC/Th splitting."
        ),
    )

# ── Tool ──────────────────────────────────────────────────────────────────────

class YouTubeMetadataTool(BaseTool):
    name: str = "YouTube Metadata Generator"
    description: str = (
        "Generates narration text (cc_en.txt), YouTube metadata (title/desc/tags/chapters), "
        "thumbnail images (PNG+JPG 1920x1080 in YT/{fmt}/Th/), and CC subtitle translations. "
        "Supports 'debate' (YT/debate/{fmt}/) and 'animation' pipeline tokens in video_formats."
    )
    args_schema: Type[BaseModel] = YouTubeMetadataToolInput

    # ─────────────────────────────────────────────────────────────────────────

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
        generate_thumbnail: bool = True,
        channel: str = "PlayOwnAi",
        channel_lower: str = "playownai",
        website: str = "youtube.com/@PlayOwnAi",
        video_formats: list = None,
        fps: float = 4.9,
        fps_hd_offset: float = 1.0,
        n_periods: int = 0,
        csv_path: str = "",
        yt_metadata_lang: int = 35,
        yt_cc_lang: int = 20,
        animation_video_formats: list = None,
    ) -> str:
        import time as _time
        import re as _vre
        t0 = _time.time()

        print(f"[YTMetadata] v2.0 — structured YT/{{fmt}}/MD|CC/ output + Thumbnails")

        # ── Format classification ─────────────────────────────────────────────
        _pipeline = {"debate", "animation"}
        _real     = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
        _valid    = _pipeline | _real

        if not video_formats:
            video_formats = ["HD"]
        elif isinstance(video_formats, str):
            video_formats = [v.strip() for v in _vre.findall(r"[A-Za-z0-9]+", video_formats)
                             if v not in ("true", "false", "null", "list")]
        video_formats = [f for f in video_formats if f in _valid] or ["HD"]

        # animation_video_formats = real formats used for animation branch AND debate per-fmt splits
        if not animation_video_formats:
            animation_video_formats = [f for f in video_formats if f in _real] or ["HD"]
        else:
            animation_video_formats = [f for f in animation_video_formats if f in _real] or ["HD"]

        active_md_langs = LANGUAGES[:min(int(yt_metadata_lang), len(LANGUAGES))]
        active_cc_langs = LANGUAGES[:min(int(yt_cc_lang), len(LANGUAGES))]

        clean = filename.strip().replace("/", " ").replace("\\", " ")

        print(f"[YTMetadata]   lang config : metadata={len(active_md_langs)} | CC={len(active_cc_langs)}")
        print(f"[YTMetadata] Starting — topic='{topic}' filename='{clean}' channel='{channel}'")
        print(f"[YTMetadata]   output_dir : {output_dir}")
        print(f"[YTMetadata]   years      : {start_year}–{end_year}  formats: {video_formats}")
        print(f"[YTMetadata]   narration  : {generate_narration} | metadata: {generate_youtube_metadata} | thumbnail: {generate_thumbnail}")

        os.makedirs(output_dir, exist_ok=True)

        # Create YT directory for upload_log.json
        yt_dir = os.path.join(output_dir, "YT")
        os.makedirs(yt_dir, exist_ok=True)

        results = []

        self._migrate_old_yt_structure(output_dir, video_formats)

        # ── Step 1: Narration ────────────────────────────────────────────────
        if generate_narration:
            print(f"[YTMetadata] Step 1/3 — Generating narration text …")
            t1 = _time.time()
            r = self._generate_narration_file(topic, start_year, end_year, output_dir, clean, channel=channel)
            print(f"[YTMetadata] Narration done in {_time.time()-t1:.1f}s → {r}")
            results.append(r)

        # ── Step 2: Metadata ──────────────────────────────────────────────────
        if generate_youtube_metadata:
            print(f"[YTMetadata] Step 2/3 — Generating YouTube metadata per format …")
            t2 = _time.time()

            has_debate    = "debate" in video_formats
            has_animation = "animation" in video_formats
            direct_fmts   = [f for f in video_formats if f not in _pipeline]
            fmt_results   = []

            # DEBATE → YT/debate/{real_fmt}/MD/  (separate content per format)
            if has_debate:
                print(f"[YTMetadata]   • [debate] real formats: {animation_video_formats}")
                for real_fmt in animation_video_formats:
                    lbl      = f"debate/{real_fmt}"
                    existing = os.path.join(output_dir, "YT", "debate", real_fmt, "MD", "en.json")
                    if os.path.exists(existing):
                        print(f"[YTMetadata]   • [{lbl}] YT/{lbl}/MD/en.json already exists")
                        fmt_results.append(f"[{lbl}] Skipped")
                        continue
                    meta = self._build_debate_metadata(
                        topic, output_dir, start_year, end_year,
                        fmt=real_fmt,
                        channel=channel, channel_lower=channel_lower, website=website)
                    fmt_results.append(self._write_metadata_files(
                        topic, meta["title"], meta["description"],
                        meta["tags"], meta["chapters"],
                        output_dir, fmt=lbl, lang_list=active_md_langs))

            # ANIMATION → YT/{real_fmt}/MD/ per real format
            if has_animation:
                periods = self._detect_periods(n_periods, clean, start_year, end_year)
                title   = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
                tags    = self._generate_youtube_tags(topic, channel=channel)
                print(f"[YTMetadata]   • [animation] real formats: {animation_video_formats}")
                for fmt in animation_video_formats:
                    existing = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
                    if os.path.exists(existing):
                        print(f"[YTMetadata]   • [{fmt}] YT/{fmt}/MD/en.json already exists")
                        fmt_results.append(f"[{fmt}] Skipped")
                        continue
                    dur  = self._calc_duration(fmt, periods, fps, fps_hd_offset)
                    desc = self._generate_youtube_description(
                        topic, start_year, end_year, dur,
                        channel=channel, channel_lower=channel_lower, website=website)
                    ch   = self._generate_youtube_chapters(start_year, end_year, dur)
                    print(f"[YTMetadata]   • [{fmt}] {periods} periods → {dur:.1f}s")
                    fmt_results.append(self._write_metadata_files(
                        topic, title, desc, tags, ch,
                        output_dir, fmt=fmt, lang_list=active_md_langs))

            # DIRECT real fmts → YT/{fmt}/MD/
            if direct_fmts:
                periods = self._detect_periods(n_periods, clean, start_year, end_year)
                title   = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
                tags    = self._generate_youtube_tags(topic, channel=channel)
                print(f"[YTMetadata]   • Direct formats: {direct_fmts}")
                for fmt in direct_fmts:
                    existing = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
                    if os.path.exists(existing):
                        print(f"[YTMetadata]   • [{fmt}] YT/{fmt}/MD/en.json already exists")
                        fmt_results.append(f"[{fmt}] Skipped")
                        continue
                    dur  = self._calc_duration(fmt, periods, fps, fps_hd_offset)
                    desc = self._generate_youtube_description(
                        topic, start_year, end_year, dur,
                        channel=channel, channel_lower=channel_lower, website=website)
                    ch   = self._generate_youtube_chapters(start_year, end_year, dur)
                    fmt_results.append(self._write_metadata_files(
                        topic, title, desc, tags, ch,
                        output_dir, fmt=fmt, lang_list=active_md_langs))

            print(f"[YTMetadata] Metadata done in {_time.time()-t2:.1f}s")
            results.append("\n".join(fmt_results))

        # ── Step 3: Thumbnails → YT/debate/{fmt}/Th/ or YT/{fmt}/Th/ ─────────
        if generate_thumbnail:
            print(f"[YTMetadata] Step 3/3 — Generating thumbnail images …")
            t3 = _time.time()
            r = self._generate_thumbnails(
                topic, start_year, end_year, output_dir, clean,
                video_formats=video_formats,
                animation_video_formats=animation_video_formats,
                csv_path=csv_path or f"output/{clean}.csv",
                channel=channel)
            print(f"[YTMetadata] Thumbnail done in {_time.time()-t3:.1f}s → {r}")
            results.append(r)

        # ── Step CC: Translate CC files ───────────────────────────────────────
        # debate  → YT/debate/{real_fmt}/CC/   (per format, separate content)
        # others  → YT/{fmt}/CC/
        print(f"[YTMetadata] Step CC — Translating CC narration files …")
        cc_result = self._translate_cc_files(
            output_dir, video_formats,
            lang_list=active_cc_langs,
            animation_video_formats=animation_video_formats)
        results.append(cc_result)

        self._cleanup_and_rename(output_dir, video_formats, channel, topic)

        # Save upload_log.json inside YT/ directory
        self._save_upload_log(yt_dir, topic, channel)

        print(f"[YTMetadata] All steps done in {_time.time()-t0:.1f}s")
        return "\n\n".join(r for r in results if r)

    def _save_upload_log(self, yt_dir: str, topic: str, channel: str):
        """Save upload log inside YT/ directory"""
        log_path = os.path.join(yt_dir, "upload_log.json")
        log_data = {
            "topic": topic,
            "channel": channel,
            "created_at": datetime.now().isoformat(),
            "status": "ready_for_upload"
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        print(f"[YTMetadata] Saved: YT/upload_log.json")

    # ── Small helpers ─────────────────────────────────────────────────────────

    def _detect_periods(self, n_periods: int, clean: str, start_year: int, end_year: int) -> int:
        if n_periods > 0:
            return n_periods
        try:
            import pandas as pd
            n = len(pd.read_csv(f"output/{clean}.csv"))
            print(f"[YTMetadata]   Auto-detected n_periods={n} from CSV")
            return n
        except Exception:
            n = end_year - start_year + 1
            print(f"[YTMetadata]   Fallback n_periods={n} from year range")
            return n

    def _calc_duration(self, fmt: str, periods: int, fps: float, fps_hd_offset: float) -> float:
        spp = fps if fmt in ("Shorts", "ShortsHD", "Shorts4K") else fps * fps_hd_offset
        return periods * spp + spp * 2

    # ── Narration ─────────────────────────────────────────────────────────────

    def _generate_narration_file(self, topic, start_year, end_year,
                                  output_dir, clean, channel="PlayOwnAi") -> str:
        csv_path = f"output/{clean}.csv"
        print(f"[YTMetadata]   CSV path: {csv_path} (exists={os.path.exists(csv_path)})")
        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                tc   = df.columns[0]; dc = df.columns[1:]
                yrs  = df[tc].tolist()
                s, e = int(yrs[0]), int(yrs[-1])
                parts = [
                    f"Welcome to @{channel}.",
                    f"Today, we're exploring {topic} from {s} to {e}.",
                    "Only for basic idea about trending.",
                    "Let's see how the landscape evolved.",
                ]
                for _, row in df.iterrows():
                    ldr = row[dc].idxmax(); val = row[ldr]; yr = int(row[tc])
                    if val <= 20:   parts.append(f"{yr}. The market is forming.")
                    elif val <= 40: parts.append(f"{yr}. {ldr} gains traction.")
                    elif val <= 70: parts.append(f"{yr}. {ldr} shows strength.")
                    else:           parts.append(f"{yr}. {ldr} leads the market.")
                parts.append(f"Subscribe to @{channel} for more insights.")
                narration = "  ".join(parts)
            except Exception as ex:
                print(f"[YTMetadata]   CSV read failed: {ex}")
                narration = self._fallback_narration(topic, start_year, end_year, channel)
        else:
            narration = self._fallback_narration(topic, start_year, end_year, channel)

        with open(os.path.join(output_dir, "cc_en.txt"), "w", encoding="utf-8") as f:
            f.write(narration)
        return "Narration text saved to: cc_en.txt"

    def _fallback_narration(self, topic, start_year, end_year, channel="PlayOwnAi") -> str:
        return (f"Welcome to @{channel}. Today, we're exploring {topic} from {start_year} to {end_year}.  "
                 "Only for basic idea about trending.  "
                f"Subscribe to @{channel} for more insights.")

    # ── Debate metadata builder ───────────────────────────────────────────────

    def _build_debate_metadata(self, topic, output_dir, start_year, end_year,
                                 fmt="HD",
                                channel="PlayOwnAi", channel_lower="playownai",
                                website="youtube.com/@PlayOwnAi") -> dict:
        is_short = fmt in ("Shorts", "ShortsHD", "Shorts4K")
        def _read(name):
            for p in [os.path.join(output_dir, f"{name}_En.md"),
                      os.path.join(output_dir, f"{name}.md")]:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f: return f.read()
            return ""

        def _sentences(text, n=2):
            text = re.sub(r"^#+\s.*$", "", text, flags=re.MULTILINE)
            text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
            text = re.sub(r"\*+", "", text)
            text = re.sub(r"\n{2,}", "  ", text).strip()
            sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]
            return "  ".join(sents[:n])

        pro_raw = _read("propose"); con_raw = _read("oppose"); dec_raw = _read("decide")
        print(f"[YTMetadata]   • [debate] MD files:  "
              f"propose={'Yes' if pro_raw else 'No'}  "
              f"oppose={'Yes' if con_raw else 'No'}  "
              f"decide={'Yes' if dec_raw else 'No'}")

        if not (pro_raw or con_raw or dec_raw):
            # Fallback to standard auto-generated metadata
            dur = 60.0 if is_short else 180.0
            return {
                "title":    self._generate_youtube_title(topic, start_year, end_year, channel=channel),
                "description": self._generate_youtube_description(
                    topic, start_year, end_year, dur,
                    channel=channel, channel_lower=channel_lower, website=website),
                "tags":     self._generate_youtube_tags(topic, channel=channel),
                "chapters": ("0:00 Introduction\n0:30 Key Argument\n0:55 Verdict"
                            if is_short else
                             "0:00 Introduction\n0:30 Pro Arguments\n2:00 Con Arguments\n3:30 Verdict"),
            }

        pro  = _sentences(pro_raw)  if pro_raw  else "Strong arguments support this position."
        con  = _sentences(con_raw)  if con_raw  else "Significant counterarguments exist."
        dec  = _sentences(dec_raw)  if dec_raw  else "The evidence suggests a nuanced conclusion."

        # ── Format-specific content ───────────────────────────────────────────
        if is_short:
            # Shorts: lead with the single strongest argument + verdict
            strongest_label = "PRO" if pro_raw else "CON"
            strongest_arg   = pro if pro_raw else con
            title       = f"{topic}: The Key Argument in 60s | @{channel} #Shorts"
            description = f"""{topic} — Quick Debate
{strongest_label}
{strongest_arg}
VERDICT
{dec}
Subscribe @{channel} for full debates!
#{topic.replace(' ', '')} #AIDebate #Shorts
AI-generated for educational purposes.
""".strip()
            chapters = "0:00 Introduction\n0:10 Key Argument\n0:50 Verdict"
        else:
            # HD / full format: include both sides
            title       = f"{topic}: AI Debate & Analysis | @{channel}"
            description = f"""{topic} — AI Debate & Analysis
THE QUESTION
Should {topic}? This debate explores both sides with evidence-based arguments.
PRO ARGUMENTS
{pro}
CON ARGUMENTS
{con}
VERDICT
{dec}
Subscribe to @{channel} for more AI debates and analysis!
FOLLOW US:
• YouTube: @{channel}
• LinkedIn: {channel_lower} | www.linkedin.com/company/{channel_lower}/
• Website: {website}
#{topic.replace(' ', '')} #AIDebate #ArtificialIntelligence #TechDebate #FutureOfWork #AIAnalysis
Disclaimer: Arguments generated by AI for educational purposes only.
""".strip()
            chapters = "0:00 Introduction\n0:30 Pro Arguments\n2:00 Con Arguments\n3:30 Verdict & Conclusion"
        print(f"[YTMetadata]   • [debate/{fmt}] Title: {title}")

        tags = [
            topic.lower(), f"{topic.lower()} debate", f"{topic.lower()} analysis",
            "AI debate", "artificial intelligence", "tech debate", "pro vs con",
            "AI analysis", "future of work", "technology debate",
            channel, f"@{channel}", "data driven", "tech trends",
        ][:25]

        return {
            "title":       title,
            "description": description,
            "tags":        tags,
            "chapters":    chapters,
        }

    # ── Metadata file writer ──────────────────────────────────────────────────

    def _write_metadata_files(self, topic, title, description, tags, chapters,
                                output_dir, fmt="", lang_list=None) -> str:
        if lang_list is None:
            lang_list = LANGUAGES[:35]
        lbl    = fmt if fmt else "Video"
        md_dir = os.path.join(output_dir, "YT", lbl, "MD")
        os.makedirs(md_dir, exist_ok=True)

        en_json = os.path.join(md_dir, "en.json")
        if not os.path.exists(en_json):
            with open(en_json, "w", encoding="utf-8") as f:
                json.dump({"title": title, "description": description, "tags": tags,
                            "chapters": chapters, "category": "Science & Technology",
                            "language": "en", "created_at": datetime.now().isoformat()},
                          f, indent=2, ensure_ascii=False)
            print(f"[YTMetadata]   Saved: YT/{lbl}/MD/en.json")
        else:
            print(f"[YTMetadata]   Exists: YT/{lbl}/MD/en.json")

        en_txt = os.path.join(md_dir, "en.txt")
        if not os.path.exists(en_txt):
            with open(en_txt, "w", encoding="utf-8") as f:
                f.write(f"TITLE:\n{title}\n\nDESCRIPTION:\n{description}\n\n"
                        f"TAGS:\n{', '.join(tags)}\n\nCHAPTERS:\n{chapters}\n")
            print(f"[YTMetadata]   Saved: YT/{lbl}/MD/en.txt")
        else:
            print(f"[YTMetadata]   Exists: YT/{lbl}/MD/en.txt")

        print(f"[YTMetadata]   Translating MD to {len(lang_list)} languages …")
        ok = 0
        for lang in lang_list:
            p = os.path.join(md_dir, f"{lang}.txt")
            if os.path.exists(p):
                print(f"[YTMetadata]     YT/{lbl}/MD/{lang}.txt exists")
                ok += 1; continue
            try:
                t_t  = _google_translate(title, lang)
                t_d  = _google_translate(description, lang)
                t_tg = _google_translate(", ".join(tags), lang)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(f"TITLE:\n{t_t}\n\nDESCRIPTION:\n{t_d}\n\n"
                            f"TAGS:\n{t_tg}\n\nCHAPTERS:\n{chapters}\n")
                print(f"[YTMetadata]     YT/{lbl}/MD/{lang}.txt ({LANG_NAMES.get(lang, lang)})")
                ok += 1; time.sleep(0.2)
            except Exception as e:
                print(f"[YTMetadata]     {lang}: {e}")

        return f"[{lbl}] {ok+2}/{len(lang_list)+2} files in YT/{lbl}/MD/"

    # ── Standard metadata generators ─────────────────────────────────────────

    def _generate_youtube_title(self, topic, start_year, end_year, channel="PlayOwnAi") -> str:
        t = [
            f"{topic} Race {start_year}-{end_year}: Complete Evolution & Trends",
            f"The {topic} Evolution ({start_year}-{end_year}): Who Dominates?",
            f"{topic} Comparison {start_year}-{end_year}: Shocking Results!",
            f"How {topic} Changed Forever ({start_year}-{end_year}) | Data Visualization",
        ]
        return t[3] if len(topic) > 20 else (t[0] if len(topic) > 10 else t[1])

    def _generate_youtube_description(self, topic, start_year, end_year, video_duration,
                                       channel="PlayOwnAi", channel_lower="playownai",
                                       website="youtube.com/@PlayOwnAi") -> str:
        return f"""{topic} Race {start_year}-{end_year}: Complete Data Visualization
We explore the evolution of {topic} from {start_year} to {end_year}. Watch how market leaders changed!
Subscribe to @{channel} for more data-driven insights!
DATA SOURCE: Comprehensive market data tracking {topic.lower()} popularity from {start_year} to {end_year}.
KEY INSIGHTS: Market trends • Year-by-year leader changes • Growth patterns • Competitive landscape
FOLLOW US:
• YouTube: @{channel}
• LinkedIn: {channel_lower} | www.linkedin.com/company/{channel_lower}/
• Website: {website}
#DataVisualization #{topic.replace(' ', '')} #MarketAnalysis #TechTrends
Disclaimer: Educational content. Data compiled from public sources.
""".strip()

    def _generate_youtube_tags(self, topic, channel="PlayOwnAi") -> list:
        return ([
            "data visualization", "market analysis", "tech trends",
            "bar chart race", "data animation", channel,
            topic.lower(), f"{topic.lower()} trends", f"{topic.lower()} comparison",
            f"{topic.lower()} evolution", f"{topic.lower()} analysis",
            str(datetime.now().year), "trend analysis", "visualization",
        ])[:25]

    def _generate_youtube_chapters(self, start_year, end_year, video_duration) -> str:
        total = end_year - start_year + 1
        secs  = video_duration / total if total > 0 else 5
        lines = ["0:00 Introduction"]
        for yr in range(start_year, end_year + 1):
            ts = int((yr - start_year) * secs)
            lines.append(f"{ts//60:02d}:{ts%60:02d} {yr}")
        ts = int(video_duration)
        lines.append(f"{ts//60:02d}:{ts%60:02d} Conclusion")
        return "\n".join(lines)

    # ── Thumbnail generator ───────────────────────────────────────────────────

    def _generate_thumbnails(self, topic, start_year, end_year, output_dir, clean,
                               video_formats, animation_video_formats,
                              csv_path="", channel="PlayOwnAi") -> str:
        """
        Save thumbnails to:
          debate    → YT/debate/{real_fmt}/Th/{clean}.png|jpg  (no CSV needed)
          animation → YT/{real_fmt}/Th/{clean}.png|jpg
          direct    → YT/{fmt}/Th/{clean}.png|jpg
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return "Pillow not installed — thumbnails skipped"

        # ── Build target lists ────────────────────────────────────────────────
        # debate_targets: rendered from MD files — no CSV required
        # bar_targets:    rendered from CSV data
        debate_targets = []   # (th_dir, real_fmt)
        bar_targets    = []   # th_dir

        for fmt in video_formats:
            if fmt == "debate":
                for rf in animation_video_formats:
                    debate_targets.append(
                        (os.path.join(output_dir, "YT", "debate", rf, "Th"), rf)
                    )
            elif fmt == "animation":
                for rf in animation_video_formats:
                    bar_targets.append(os.path.join(output_dir, "YT", rf, "Th"))
            else:
                bar_targets.append(os.path.join(output_dir, "YT", fmt, "Th"))

        if not debate_targets and not bar_targets:
            bar_targets = [os.path.join(output_dir, "YT", "Video", "Th")]

        saved = []

        def _save_img(img, th_dir):
            os.makedirs(th_dir, exist_ok=True)
            for fname, fmt_name, kw in [
                (f"{clean}.png", "PNG", {}),
                (f"{clean}.jpg", "JPEG", {"quality": 95}),
            ]:
                fpath = os.path.join(th_dir, fname)
                if not os.path.exists(fpath):
                    img.save(fpath, fmt_name, **kw)
                    kb  = os.path.getsize(fpath) // 1024
                    rel = os.path.relpath(fpath, output_dir)
                    print(f"[YTMetadata]   Saved: {rel} ({kb} KB)")
                else:
                    rel = os.path.relpath(fpath, output_dir)
                    print(f"[YTMetadata]   Exists: {rel}")
            saved.append(os.path.relpath(th_dir, output_dir))

        # ── Debate thumbnails (no CSV) ────────────────────────────────────────
        for th_dir, real_fmt in debate_targets:
            is_short = real_fmt in ("Shorts", "ShortsHD", "Shorts4K")
            img = self._render_debate_thumbnail(
                topic, output_dir, channel, is_short=is_short)
            _save_img(img, th_dir)
            print(f"[YTMetadata]   Debate thumbnail → {os.path.relpath(th_dir, output_dir)}")

        # ── Bar-race thumbnails (need CSV) ────────────────────────────────────
        if bar_targets:
            csv_data = None
            for cp in [csv_path, f"output/{clean}.csv"]:
                if cp and os.path.exists(cp):
                    try:
                        import pandas as pd
                        csv_data = pd.read_csv(cp)
                        break
                    except Exception:
                        pass
            if csv_data is None:
                msg = f"CSV not found — bar-race thumbnails skipped for: {bar_targets}"
                print(f"[YTMetadata]   {msg}")
            else:
                img = self._render_thumbnail(topic, start_year, end_year, csv_data, channel)
                for th_dir in bar_targets:
                    _save_img(img, th_dir)

        if not saved:
            return "No thumbnails generated"
        return f"Thumbnails saved to: {', '.join(saved)}"

    def _render_debate_thumbnail(self, topic, output_dir, channel,
                                  is_short=False) -> "Image":
        """
        Render a 1920×1080 debate thumbnail.
        Layout:
          ┌─────────────────────────────────────────┐
          │  [AI DEBATE]  badge        top-right fmt │
          │                                           │
          │    <TOPIC  (2 lines, large) >              │
          │                                          │
          │  ┌──────────┐  ┌──────────┐  ┌────────┐ │
          │  │ PRO   │  │ CON  │  │ VRD │ │
          │  │ snip pet  │  │ snippet  │  │ snippet│ │
          │  └──────────┘  └──────────┘  └────────┘ │
          │                                          │
          │         @channel              footer      │
          └─────────────────────────────────────────┘
        For Shorts (is_short=True) only the strongest argument panel is shown.
        """
        from PIL import Image, ImageDraw, ImageFont

        # ── Canvas: portrait for Shorts, landscape for HD ─────────────────────
        if is_short:
            W, H = 1080, 1920
        else:
            W, H = 1920, 1080

        BG     = (10, 12, 24)
        ACCENT = (60, 80, 200)
        WHITE  = (255, 255, 255)
        CYAN   = (80, 210, 255)
        GREEN  = (60, 220, 120)
        RED    = (255, 80, 80)
        GOLD   = (255, 200, 60)
        GREY   = (160, 165, 185)

        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        # ── subtle gradient overlay ───────────────────────────────────────────
        for y in range(H):
            alpha = int(30 * (1 - y / H))
            r = min(255, BG[0] + alpha)
            g = min(255, BG[1] + alpha + 5)
            b = min(255, BG[2] + alpha + 20)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        def _font(sz):
            for path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]:
                if os.path.exists(path):
                    try: return ImageFont.truetype(path, sz)
                    except Exception: pass
            return ImageFont.load_default()

        def _font_reg(sz):
            for path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]:
                if os.path.exists(path):
                    try: return ImageFont.truetype(path, sz)
                    except Exception: pass
            return ImageFont.load_default()

        def _center_text(text, y, font, color):
            bb = draw.textbbox((0, 0), text, font=font)
            x  = (W - (bb[2] - bb[0])) // 2
            draw.text((x, y), text, fill=color, font=font)
            return bb[3] - bb[1]

        def _wrap_text(text, font, max_w, max_lines=3):
            words = text.split()
            lines, cur = [], ""
            for w in words:
                test = (cur + " " + w).strip()
                bb   = draw.textbbox((0, 0), test, font=font)
                if bb[2] - bb[0] <= max_w:
                    cur = test
                else:
                    if cur: lines.append(cur)
                    cur = w
                    if len(lines) >= max_lines - 1: break
            if cur: lines.append(cur)
            return lines[:max_lines]

        # ── read debate MD snippets ───────────────────────────────────────────
        def _read_snippet(name, n_sent=2):
            for p in [os.path.join(output_dir, f"{name}_En.md"),
                      os.path.join(output_dir, f"{name}.md")]:
                if os.path.exists(p):
                    try:
                        with open(p, encoding="utf-8") as f: raw = f.read()
                        raw = re.sub(r"^#+\s.*$", "", raw, flags=re.MULTILINE)
                        raw = re.sub(r"^\s*[-*]\s+", "", raw, flags=re.MULTILINE)
                        raw = re.sub(r"\*+", "", raw)
                        # Strip ALL-CAPS section labels: "PROPOSITION: ", "VERDICT: ",
                        # "SUMMARY OF PROPOSITION: ", "OPENING STATEMENT: ", etc.
                        raw = re.sub(r"\b[A-Z][A-Z\s]{3,}:\s*", "", raw)
                        raw = re.sub(r"\n{2,}", "  ", raw).strip()
                        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw)
                                 if len(s.strip()) > 15]
                        return "  ".join(sents[:n_sent])
                    except Exception:
                        pass
            return ""

        pro_txt = _read_snippet("propose") or "AI automation increasingly handles routine coding tasks."
        con_txt = _read_snippet("oppose")  or "Human creativity and problem-solving remain irreplaceable."
        dec_txt = _read_snippet("decide")  or "A nuanced transition is underway — adapt or be left behind."

        # ── BADGE: top-left ───────────────────────────────────────────────────
        badge_f = _font(38)
        badge_label = "AI DEBATE"
        bb = draw.textbbox((0, 0), badge_label, font=badge_f)
        bw, bh = bb[2] - bb[0] + 40, bb[3] - bb[1] + 20
        draw.rounded_rectangle([(40, 38), (40 + bw, 38 + bh)],
                                 radius=14, fill=(40, 60, 160))
        draw.text((40 + 20, 38 + 10), badge_label, fill=WHITE, font=badge_f)

        # ── fmt badge: top-right ────────────────────────────────────────────
        fmt_label = "#SHORTS" if is_short else "HD"
        fmt_col   = GOLD if is_short else CYAN
        fmt_f     = _font(38)
        bb2 = draw.textbbox((0, 0), fmt_label, font=fmt_f)
        fw = bb2[2] - bb2[0] + 40
        fh = bb2[3] - bb2[1] + 20
        draw.rounded_rectangle([(W - 40 - fw, 38), (W - 40, 38 + fh)],
                                radius=14, fill=(30, 30, 60))
        draw.text((W - 40 - fw + 20, 38 + 10), fmt_label, fill=fmt_col, font=fmt_f)

        # ── TOPIC title (2 lines) ─────────────────────────────────────────────
        title_f = _font(88)
        words   = topic.split()
        mid     = len(words) // 2
        lines   = ["  ".join(words[:mid]), "  ".join(words[mid:])]
        ty      = 120
        for line in lines:
            if not line: continue
            h = _center_text(line, ty, title_f, WHITE)
            ty += h + 12
        ty += 18  # gap after title

        # ── horizontal rule ───────────────────────────────────────────────────
        draw.line([(80, ty), (W - 80, ty)], fill=(60, 65, 100), width=2)
        ty += 24

        # ── argument panels ───────────────────────────────────────────────────
        panel_y = ty

        if is_short:
            # Portrait layout: panels stacked vertically, full width
            panel_pad  = 36
            panel_r    = 22
            label_f    = _font(52)
            body_f     = _font_reg(40)
            panels = [
                ("PRO ARGUMENT", GREEN, (30, 55, 35), pro_txt),
                ("VERDICT",      GOLD,  (55, 45, 20), dec_txt),
            ]
            gap      = 28
            pw       = W - 160   # full width minus margins
            panel_h  = (H - panel_y - 160 - gap) // 2    # split remaining height
            px, py   = 80, panel_y

            for label, label_col, bg_col, body in panels:
                draw.rounded_rectangle(
                    [(px, py), (px + pw, py + panel_h)],
                    radius=panel_r, fill=bg_col)
                draw.text((px + panel_pad, py + panel_pad),
                          label, fill=label_col, font=label_f)
                body_lines = _wrap_text(body, body_f, pw - panel_pad * 2, max_lines=7)
                by = py + panel_pad + 66
                for bl in body_lines:
                    draw.text((px + panel_pad, by), bl, fill=WHITE, font=body_f)
                    by += 52
                py += panel_h + gap

            foot_y = py + 20
        else:
            # Landscape layout: panels side by side
            panel_h    = 420
            panel_pad  = 28
            panel_r    = 18
            label_f    = _font(44)
            body_f     = _font_reg(34)
            panels = [
                ("PRO",     GREEN, (30, 55, 35), pro_txt),
                ("CON",     RED,   (55, 25, 25), con_txt),
                ("VERDICT", GOLD,  (55, 45, 20), dec_txt),
            ]
            n_panels  = 3
            gap       = 30
            pw        = (W - 160 - gap * (n_panels - 1)) // n_panels
            px        = 80

            for label, label_col, bg_col, body in panels:
                draw.rounded_rectangle(
                    [(px, panel_y), (px + pw, panel_y + panel_h)],
                    radius=panel_r, fill=bg_col)
                draw.text((px + panel_pad, panel_y + panel_pad),
                          label, fill=label_col, font=label_f)
                body_lines = _wrap_text(body, body_f, pw - panel_pad * 2, max_lines=6)
                by = panel_y + panel_pad + 56
                for bl in body_lines:
                    draw.text((px + panel_pad, by), bl, fill=WHITE, font=body_f)
                    by += 42
                px += pw + gap

            foot_y = panel_y + panel_h + 28

        # ── footer ────────────────────────────────────────────────────────────
        chan_f  = _font(40)
        foot_f  = _font_reg(34)
        _center_text(f"@{channel}", foot_y, chan_f, CYAN)
        _center_text("Debate for AI Educational Purposes Only",
                     foot_y + 52, foot_f, GREY)

        return img

    def _render_thumbnail(self, topic, start_year, end_year, csv_data, channel) -> "Image":
        from PIL import Image, ImageDraw, ImageFont
        W, H     = 1920, 1080
        bg       = (15, 15, 25)
        colors   = [(255,82,82),(82,255,166),(82,166,255),(255,200,82),
                     (200,82,255),(82,255,255),(255,128,0),(128,255,0)]
        txt_col  = (255, 255, 255)
        pri_col  = (100, 200, 255)

        img  = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)

        def _font(sz):
            for path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]:
                if os.path.exists(path):
                    try: return ImageFont.truetype(path, sz)
                    except Exception: pass
            return ImageFont.load_default()

        lf, mf, sf = _font(80), _font(55), _font(36)
        ty = 60
        words = topic.split()
        for line in ["  ".join(words[:4]), "  ".join(words[4:])]:
            if not line: continue
            bb = draw.textbbox((0,0), line, font=lf)
            draw.text(((W-(bb[2]-bb[0]))//2, ty), line, fill=txt_col, font=lf)
            ty += 100

        yr_txt = f"{start_year} – {end_year}"
        bb = draw.textbbox((0,0), yr_txt, font=mf)
        draw.text(((W-(bb[2]-bb[0]))//2, ty+10), yr_txt, fill=pri_col, font=mf)

        latest   = csv_data.iloc[-1]
        dc       = csv_data.columns[1:]
        vals     = [float(latest.get(c, 0)) for c in dc]
        max_val  = max(vals) if vals else 100
        if max_val == 0: max_val = 100
        cx, cw   = 150, W-300
        cy, bh, bs = 620, 60, 20

        for i, (col, val) in enumerate(zip(dc, vals)):
            bw = (val / max_val) * cw
            by = cy + i * (bh + bs)
            draw.rectangle([(cx, by), (cx+bw, by+bh)], fill=colors[i % len(colors)])
            draw.text((cx+15, by+10), f"{col}: {int(val)}", fill=txt_col, font=sf)

        footer = f"Bar Race {start_year}–{end_year}"
        bb = draw.textbbox((0,0), footer, font=sf)
        draw.text(((W-(bb[2]-bb[0]))//2, H-60), footer, fill=pri_col, font=sf)
        return img

    # ── CC translator ─────────────────────────────────────────────────────────

    def _translate_cc_files(self, output_dir, video_formats,
                             lang_list=None, animation_video_formats=None) -> str:
        """
        Translate CC source files.
        debate  → YT/debate/{real_fmt}/CC/   (separate file per real format)
        animation/direct → YT/{fmt}/CC/
        """
        if lang_list is None:
            lang_list = LANGUAGES[:20]
        if not animation_video_formats:
            animation_video_formats = ["HD"]

        import glob as _glob
        _real = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}

        translated_total = 0
        skipped_total    = 0
        report           = []
        # cc_sources: (src_path, cc_dir_path, display_label)
        cc_sources       = []

        for fmt in video_formats:

            # ── DEBATE: per real format ───────────────────────────────────────
            if fmt == "debate":
                for real_fmt in animation_video_formats:
                    # File naming: PlayOwnAi_Debate_*_{real_fmt}_*_cc.txt
                    patterns = [
                        os.path.join(output_dir, f"*_{real_fmt}_*_cc.txt"),
                        os.path.join(output_dir, f"*_{real_fmt}_*cc_en.txt"),
                        os.path.join(output_dir, f"*_{real_fmt}_En_cc.txt"),
                        os.path.join(output_dir, f"*_{real_fmt}_cc.txt"),
                    ]
                    found = []; seen = set()
                    for pat in patterns:
                        for p in _glob.glob(pat):
                            if p not in seen: seen.add(p); found.append(p)
                    if found:
                        cc_dir  = os.path.join(output_dir, "YT", "debate", real_fmt, "CC")
                        display = f"debate/{real_fmt}"
                        cc_sources.append((found[0], cc_dir, display))
                        print(f"[YTMetadata] Found debate CC [{real_fmt}]: {os.path.basename(found[0])}")
                    else:
                        print(f"[YTMetadata] No CC file for debate/{real_fmt} (optional)")
                continue

            # ── ANIMATION: expand to real fmt names ───────────────────────────
            real_fmts = animation_video_formats if fmt == "animation" else [fmt]

            for real_fmt in real_fmts:
                merged = []; seen = set()
                for pat in [
                    os.path.join(output_dir, f"*_{real_fmt}_*cc*.txt"),
                    os.path.join(output_dir, f"*_{real_fmt}_cc_en.txt"),
                    os.path.join(output_dir, f"*_{real_fmt}_En_cc.txt"),
                ]:
                    for p in _glob.glob(pat):
                        bn = os.path.basename(p)
                        if p not in seen and not bn.startswith("intro_") \
                                and not bn.startswith("definition_video_"):
                            seen.add(p); merged.append(p)
                if not merged:
                    bar_cc = os.path.join(output_dir, f"bar_race_{real_fmt}_cc_en.txt")
                    if os.path.exists(bar_cc): merged.append(bar_cc)
                if merged:
                    cc_dir  = os.path.join(output_dir, "YT", real_fmt, "CC")
                    display = real_fmt
                    cc_sources.append((merged[0], cc_dir, display))
                    print(f"[YTMetadata] Found CC [{real_fmt}]: {os.path.basename(merged[0])}")
                else:
                    print(f"[YTMetadata] No CC file for fmt={real_fmt}")

        # Standard cc_en.txt fallback — only when non-debate formats are active.
        # debate-only pipeline already has per-fmt CC; cc_en.txt must not spill
        # into YT/HD/CC/ when video_formats = ['debate'] only.
        has_non_debate = any(f != "debate" for f in video_formats)
        std_cc = os.path.join(output_dir, "cc_en.txt")
        if has_non_debate and os.path.exists(std_cc):
            first_rf = animation_video_formats[0] if animation_video_formats else "standard"
            cc_dir   = os.path.join(output_dir, "YT", first_rf, "CC")
            display  = first_rf
            if not any(s[1] == cc_dir for s in cc_sources):
                cc_sources.append((std_cc, cc_dir, display))
                print(f"[YTMetadata] Found standard CC: cc_en.txt → {display}")
        elif not has_non_debate:
            print(f"[YTMetadata] Skipping cc_en.txt fallback — debate-only pipeline")

        if not cc_sources:
            msg = "No CC source files found (optional for debate)"
            print(f"[YTMetadata] {msg}")
            return msg

        for src_path, cc_dir, display in cc_sources:
            with open(src_path, "r", encoding="utf-8") as f:
                en_text = f.read().strip()
            if not en_text:
                print(f"[YTMetadata]   {os.path.basename(src_path)} empty — skipping")
                continue
            os.makedirs(cc_dir, exist_ok=True)

            en_out = os.path.join(cc_dir, "en.txt")
            if not os.path.exists(en_out):
                with open(en_out, "w", encoding="utf-8") as f: f.write(en_text)
                print(f"[YTMetadata]   Saved: YT/{display}/CC/en.txt")
            else:
                print(f"[YTMetadata]   Exists: YT/{display}/CC/en.txt")

            print(f"[YTMetadata]   Translating YT/{display}/CC/ → {len(lang_list)} languages …")
            ok = 1
            for lang in lang_list:
                out = os.path.join(cc_dir, f"{lang}.txt")
                if os.path.exists(out):
                    skipped_total += 1; ok += 1; continue
                try:
                    translated = _google_translate(en_text, lang)
                    with open(out, "w", encoding="utf-8") as f: f.write(translated)
                    print(f"[YTMetadata]     YT/{display}/CC/{lang}.txt ({LANG_NAMES.get(lang, lang)})")
                    ok += 1; translated_total += 1
                    import time as _t; _t.sleep(0.2)
                except Exception as e:
                    print(f"[YTMetadata]     {display}/CC/{lang}: {e}")

            total = len(lang_list) + 1
            report.append(f"[{display}] {ok}/{total} CC files in YT/{display}/CC/")

        summary = (f"CC translations: {translated_total} new, {skipped_total} skipped\n"
                   + "\n".join(report))
        print(f"[YTMetadata] {summary}")
        return summary

    # ── Legacy helper ─────────────────────────────────────────────────────────

    def _generate_youtube_metadata(self, topic, start_year, end_year, video_duration,
                                    output_dir, clean_filename,
                                    channel="PlayOwnAi", channel_lower="playownai",
                                    website="youtube.com/@PlayOwnAi") -> str:
        title = self._generate_youtube_title(topic, start_year, end_year, channel=channel)
        desc  = self._generate_youtube_description(
            topic, start_year, end_year, video_duration,
            channel=channel, channel_lower=channel_lower, website=website)
        tags  = self._generate_youtube_tags(topic, channel=channel)
        ch    = self._generate_youtube_chapters(start_year, end_year, video_duration)
        return self._write_metadata_files(topic, title, desc, tags, ch, output_dir)

    # ── Migration ─────────────────────────────────────────────────────────────

    def _migrate_old_yt_structure(self, output_dir, video_formats):
        import glob as _glob, re as _re
        yt_dir = os.path.join(output_dir, "YT")
        if not os.path.exists(yt_dir): return
        moved = 0

        for old in (_glob.glob(os.path.join(yt_dir, "Metadata_*.json")) +
                    _glob.glob(os.path.join(yt_dir, "Metadata_*.txt"))):
            name = os.path.basename(old)
            m = (_re.match(r"Metadata_([^_]+(?:HD|4K|8K|2K)?)_([A-Za-z-]+)\.(json|txt)$", name) or
                 _re.match(r"Metadata_([A-Za-z0-9]+)_([A-Za-z-]+)\.(json|txt)$", name))
            if not m: continue
            fp, lp, ext = m.group(1), m.group(2), m.group(3)
            nn   = "en.json" if lp.lower() == "en" and ext == "json" else f"{lp.lower()}.txt"
            ddir = os.path.join(yt_dir, fp, "MD"); os.makedirs(ddir, exist_ok=True)
            np   = os.path.join(ddir, nn)
            if not os.path.exists(np): os.rename(old, np); moved += 1
            else: os.remove(old)

        for old in _glob.glob(os.path.join(yt_dir, "cc_*.txt")):
            name = os.path.basename(old)
            m    = _re.match(r"cc_([A-Za-z0-9]+)_([A-Za-z-]+)\.txt$", name)
            if not m: continue
            p1, lang = m.group(1), m.group(2)
            known = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
            fp    = p1 if p1 in known else "standard"
            ddir  = os.path.join(yt_dir, fp, "CC"); os.makedirs(ddir, exist_ok=True)
            np    = os.path.join(ddir, f"{lang}.txt")
            if not os.path.exists(np): os.rename(old, np); moved += 1
            else: os.remove(old)

        if moved: print(f"[YTMetadata] Migration: {moved} files moved")

        # ── Rename stale YT/Debate/ → YT/debate/ (Linux case-sensitive fix) ──────
        import shutil as _sh
        old_cap = os.path.join(yt_dir, "Debate")
        new_low = os.path.join(yt_dir, "debate")
        if os.path.exists(old_cap):
            if not os.path.exists(new_low):
                _sh.copytree(old_cap, new_low)
                _sh.rmtree(old_cap)
                print(f"[YTMetadata] Renamed: YT/Debate/ → YT/debate/")
            else:
                # Both exist — merge missing files then remove old
                for root, dirs, files in os.walk(old_cap):
                    rel      = os.path.relpath(root, old_cap)
                    dst_root = os.path.join(new_low, rel)
                    os.makedirs(dst_root, exist_ok=True)
                    for fname in files:
                        dst_f = os.path.join(dst_root, fname)
                        if not os.path.exists(dst_f):
                            _sh.copy2(os.path.join(root, fname), dst_f)
                            moved += 1
                _sh.rmtree(old_cap)
                print(f"[YTMetadata] Merged YT/Debate/ into YT/debate/")

        # ── Rename stale TH/ → Th/ under YT/debate/{fmt}/ ───────────────────────
        if os.path.exists(new_low):
            for fmt_entry in os.scandir(new_low):
                if not fmt_entry.is_dir(): continue
                old_th = os.path.join(fmt_entry.path, "TH")
                new_th = os.path.join(fmt_entry.path, "Th")
                if os.path.exists(old_th) and not os.path.exists(new_th):
                    _sh.move(old_th, new_th)
                    print(f"[YTMetadata] Renamed: YT/debate/{fmt_entry.name}/TH → Th")

        # ── Migrate old flat YT/debate/MD/ → YT/debate/{fmt}/MD/ ────────────────
        old_debate_md = os.path.join(yt_dir, "debate", "MD")
        if os.path.exists(old_debate_md):
            real_fmts = [f for f in video_formats if f in {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}] or ["HD"]
            for fname in os.listdir(old_debate_md):
                src = os.path.join(old_debate_md, fname)
                if not os.path.isfile(src): continue
                for rf in real_fmts:
                    dst_dir = os.path.join(yt_dir, "debate", rf, "MD")
                    os.makedirs(dst_dir, exist_ok=True)
                    dst = os.path.join(dst_dir, fname)
                    if not os.path.exists(dst):
                        _sh.copy2(src, dst)
                        moved += 1
                        print(f"[YTMetadata] Debate MD migrated: debate/MD/{fname} → debate/{rf}/MD/{fname}")
            try:
                remaining = [f for f in os.listdir(old_debate_md)
                             if os.path.isfile(os.path.join(old_debate_md, f))]
                if not remaining:
                    _sh.rmtree(old_debate_md)
                    print(f"[YTMetadata] Removed old: YT/debate/MD/")
            except Exception: pass
        if moved: print(f"[YTMetadata] Migration total: {moved} files moved")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup_and_rename(self, output_dir, video_formats, channel, topic):
        import re, glob as _glob
        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"
        print(f"[YTMetadata] Cleanup starting — formats={video_formats} topic_slug={topic_slug}")

        glob_fmts = set()
        for pat in ["Final_*.mp4", "Merge_bar_race_*.mp4"]:
            for p in _glob.glob(os.path.join(output_dir, pat)):
                m = re.search(r"(?:Final_|Merge_bar_race_)(.+)\.mp4$", os.path.basename(p))
                if m: glob_fmts.add(m.group(1))

        _real  = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
        base   = [f for f in video_formats if f in _real]
        all_fmts = list(dict.fromkeys(base + sorted(glob_fmts)))
        print(f"[YTMetadata]   Rename targets: {all_fmts} (inputs={video_formats} glob={sorted(glob_fmts)})")

        for fmt in all_fmts:
            dst = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
            if os.path.exists(dst):
                print(f"[YTMetadata] Already exists: {os.path.basename(dst)}"); continue
            src = next((p for p in [
                os.path.join(output_dir, f"Final_{fmt}.mp4"),
                os.path.join(output_dir, f"Merge_bar_race_{fmt}.mp4"),
            ] if os.path.exists(p)), None)
            if src:
                os.rename(src, dst)
                print(f"[YTMetadata] Renamed: {os.path.basename(src)} → {os.path.basename(dst)}")
            else:
                print(f"[YTMetadata]    No source found for fmt={fmt}")

        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if not os.path.isfile(fpath): continue
            if not any(fname.endswith(e) for e in (".mp4", ".mp3")): continue
            if any(fname.startswith(p) for p in
                   ["intro_", "bar_race_", "definition_video_", "Merge_bar_race_", "Final_"]):
                os.remove(fpath)
                print(f"[YTMetadata] Deleted: {fname}")

        cc_en = os.path.join(output_dir, "cc_en.txt")
        if os.path.exists(cc_en):
            os.remove(cc_en)
            print(f"[YTMetadata] Deleted old narration: cc_en.txt")

        for pat in ["_temp_*.mp4", "_norm_*.mp4", "_stage*.mp4", "_concat_*.txt"]:
            for p in _glob.glob(os.path.join(output_dir, pat)):
                os.remove(p)
                print(f"[YTMetadata] Glob deleted: {os.path.basename(p)}")

        print(f"[YTMetadata] Cleanup done")
