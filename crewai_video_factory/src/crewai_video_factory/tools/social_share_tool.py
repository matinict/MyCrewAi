"""
Social Share Tool - FULLY DYNAMIC VERSION
Reads upload_log.json and posts the video URL + thumbnail image to configured social platforms.
Supported platforms:
Facebook   (Graph API — Page post with image)
LinkedIn   (LinkedIn API v2 — Organization/Person post with image upload)
X          (Twitter API v2 — tweet with media upload)
YouTube    (YouTube Data API — Community post)
Instagram  (Graph API — Reel/Post with image)
Triggered by: "social_share_enabled": true in data.json
Credentials go in input/social_credentials.json (never committed to git).
"""
import os
import re
import json
import time
import base64
from typing import Type, List, Optional
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# ── Credentials file ────────────────────────────────────────────────────────
CREDS_PATH = "input/social_credentials.json"
CREDS_TEMPLATE = {
    "Facebook": {
        "page_id": "YOUR_PAGE_ID",
        "access_token": "YOUR_PAGE_ACCESS_TOKEN"
    },
    "LinkedIn": {
        "access_token": "YOUR_LINKEDIN_ACCESS_TOKEN",
        "owner": "urn:li:organization:YOUR_ORG_ID"
    },
    "X": {
        "api_key": "YOUR_API_KEY",
        "api_secret": "YOUR_API_SECRET",
        "access_token": "YOUR_ACCESS_TOKEN",
        "access_token_secret": "YOUR_ACCESS_TOKEN_SECRET",
        "bearer_token": "YOUR_BEARER_TOKEN"
    },
    "YouTube": {
        "client_secrets_file": "client_secrets.json",
        "token_file": "token.json"
    },
    "Instagram": {
        "ig_user_id": "YOUR_IG_USER_ID",
        "access_token": "YOUR_PAGE_ACCESS_TOKEN",
        "imgur_client_id": "YOUR_IMGUR_CLIENT_ID"
    }
}

class SocialShareInput(BaseModel):
    topic: str = Field(..., description="Topic name")
    filename: str = Field(..., description="Base filename slug")
    output_dir: str = Field(..., description="Output subdirectory")
    social_share_enabled: bool = Field(default=False, description="Enable social sharing")
    social_platforms: list = Field(default=["Facebook", "LinkedIn", "X", "YouTube"],
                                   description="Platforms to post to")
    video_formats: list = Field(default=["HD"], description="Video formats list")
    channel: str = Field(default="PlayOwnAi", description="Channel name for post text")
    website: str = Field(default="", description="Website URL for post footer")
    image_path: str = Field(default="", description="Path to thumbnail image for social posts")
    start_year: int = Field(default=2015, description="Start year for bar race")
    end_year: int = Field(default=2026, description="End year for bar race")
    video_url: str = Field(default="", description="Manual video URL override")
    dry_run: bool = Field(default=False, description="If true: generate & log post texts without posting live. Use for testing.")

# Platform character limits for definition section
# (total post budget minus ~400 chars for header/footer boilerplate)
PLATFORM_DEF_LIMITS = {
    "Facebook": 5000,   # ~63k total limit — effectively unlimited, use full text
    "LinkedIn": 2500,   # 3k total; ~2500 left after boilerplate
    "Instagram": 1600,  # 2200 total; ~1600 left after boilerplate
    "X": 0,             # no room — definition omitted entirely
    "Twitter": 0,
    "YouTube": 2500,    # community post, generous limit
}

class SocialShareTool(BaseTool):
    name: str = "Social Share Tool"
    description: str = (
        "Posts the uploaded YouTube video URL with thumbnail image to configured social media platforms. "
        "Reads upload_log.json to find the video URL. "
        "Supports image attachment for LinkedIn, Facebook, X, Instagram. "
        "All values (channel, year range, website) are dynamic from data.json. "
        "Triggered by social_share_enabled=true."
    )
    args_schema: Type[BaseModel] = SocialShareInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        social_share_enabled: bool = False,
        social_platforms: list = None,
        video_formats: list = None,
        channel: str = "PlayOwnAi",
        website: str = "",
        image_path: str = "",
        start_year: int = 2015,
        end_year: int = 2026,
        video_url: str = "",
        dry_run: bool = False,
    ) -> str:
        # Strip trailing/leading spaces from all string inputs
        topic = topic.strip()
        filename = filename.strip()
        output_dir = output_dir.strip()
        channel = channel.strip()
        website = website.strip()
        image_path = image_path.strip()
        video_url = video_url.strip()

        if not social_share_enabled:
            return "⏭️  Social share skipped (social_share_enabled=false)"

        if dry_run:
            print(f"[SocialShare] 🧪 DRY RUN MODE — posts will be generated and logged but NOT sent live")

        if social_platforms is None:
            social_platforms = ["Facebook", "LinkedIn", "X", "YouTube"]

        if video_formats is None:
            video_formats = ["HD"]

        # ── SMART SKIP — per-platform, per-format (skipped in dry_run) ───────────
        _smart_fmt = (video_formats[0] if video_formats else "HD")
        share_log_path = os.path.join(self._yt_dir(output_dir, _smart_fmt), "share_log.json")
        already_shared = set()

        if not dry_run and os.path.exists(share_log_path):
            try:
                with open(share_log_path) as _f:
                    _log = json.load(_f)
                for _share in _log.get("shares", []):
                    if _share.get("status") == "success":
                        already_shared.add(_share["platform"])
                if already_shared:
                    pending = [p for p in social_platforms if p not in already_shared]
                    if not pending:
                        _done = ", ".join(sorted(already_shared))
                        print(f"[SocialShare] ⏭️  Smart skip [{_smart_fmt}] — all platforms already posted: {_done}")
                        return f"⏭️  Smart skip [{_smart_fmt}] — already posted to all platforms: {_done}"
                    _skipped = ", ".join(sorted(already_shared))
                    print(f"[SocialShare] ⏭️  Smart skip [{_smart_fmt}] — already posted: {_skipped}")
                    social_platforms = pending
            except Exception as _e:
                print(f"[SocialShare] ⚠️  Could not read {share_log_path}: {_e}")

        # ── Resolve thumbnail path — DYNAMIC AUTO-DISCOVERY ────────────────────
        # Priority:
        #   1. image_path arg (if it actually exists on disk)
        #   2. YT/debate/{fmt}/Th/  or  YT/{fmt}/Th/  (auto-detect, prefer JPG)
        #   3. output_dir/{filename}.jpg / .png  (legacy animation pipeline)
        import glob as _iglob

        def _find_thumbnail(output_dir, fmt, filename):
            _th_dir = os.path.join(self._yt_dir(output_dir, fmt), "Th")
            print(f"[SocialShare] 🔍 Looking for thumbnail in: {_th_dir}")
            for _ext in (".jpg", ".jpeg", ".png"):
                _matches = sorted(_iglob.glob(os.path.join(_th_dir, f"*{_ext}")))
                if _matches:
                    return _matches[0]
            # Fallback: root output_dir (old animation pipeline)
            for _name in (f"{filename}.jpg", f"{filename}.jpeg", f"{filename}.png"):
                _p = os.path.join(output_dir, _name)
                if os.path.exists(_p):
                    return _p
            return ""

        if image_path and os.path.exists(image_path):
            # Caller-provided path is valid — use it directly
            pass
        else:
            if image_path:
                print(f"[SocialShare] ⚠️  image_path not found on disk: {image_path} — auto-detecting")
            image_path = _find_thumbnail(output_dir, _smart_fmt, filename)

        image_file = None
        if image_path and os.path.exists(image_path):
            _ext_lower = os.path.splitext(image_path)[1].lower()
            if _ext_lower in (".jpg", ".jpeg", ".png"):
                image_file = image_path
                print(f"[SocialShare] 🖼️  Using thumbnail: {image_file} ({os.path.getsize(image_file)//1024} KB)")
            else:
                print(f"[SocialShare] ⚠️  Invalid image extension: {image_path}")
        else:
            print(f"[SocialShare] ⚠️  No valid thumbnail found. Posts will be text+link only.")

        # ── Load upload_log.json ─────────────────────────────────────
        found_url = None
        fmt = video_formats[0] if video_formats else "HD"

        for fmt_check in video_formats:
            log_path = os.path.join(self._yt_dir(output_dir, fmt_check), "upload_log.json")
            if os.path.exists(log_path):
                with open(log_path) as f:
                    log = json.load(f)
                if log.get("video_id") and log.get("video_url"):
                    found_url = log["video_url"]
                    fmt = fmt_check
                    break

        if not found_url:
            if video_url:
                print(f"[SocialShare] ℹ️  No upload log found — using manual video_url: {video_url}")
                found_url = video_url
            else:
                # ── Fallback: recover URL from any existing share_log.json ─────
                for fmt_check in video_formats:
                    for log_name in ("share_log.json", "share_log_dryrun.json"):
                        slog_path = os.path.join(self._yt_dir(output_dir, fmt_check), log_name)
                        if os.path.exists(slog_path):
                            try:
                                with open(slog_path) as _sf:
                                    _slog = json.load(_sf)
                                _url = _slog.get("video_url", "")
                                if _url:
                                    found_url = _url
                                    fmt = fmt_check
                                    print(f"[SocialShare] ℹ️  Recovered video URL from {log_name}: {found_url}")
                                    break
                            except Exception as _e:
                                print(f"[SocialShare] ⚠️  Could not read {slog_path}: {_e}")
                    if found_url:
                        break

        if not found_url:
            return "❌ No video URL found. Run upload_youtube_video=true first, or set video_url manually in data.json."

        video_url = found_url
        topic_text = topic

        print(f"[SocialShare] 📎 Sharing URL: {video_url}  ({fmt})")
        print(f"[SocialShare] 📢 Platforms: {social_platforms}")
        print(f"[SocialShare] 📺 Channel: @{channel}")
        print(f"[SocialShare] 📅 Year Range: {start_year}–{end_year}")
        print(f"[SocialShare] 🌐 Website: {website}")

        # ── Load credentials ─────────────────────────────────────────────
        creds = self._load_credentials()

        # ── Build post text WITH DYNAMIC VALUES ────────────────────────────
        is_shorts_fmt = fmt in ("Shorts", "ShortsHD", "Shorts4K")

        # Load output/{filename}.txt — the topic definition file (HD: full, Shorts: What is section)
        definition_txt = self._load_definition_txt(output_dir, filename)

        short_text = self._build_post_text(topic_text, video_url, channel, website,
                                           short=True, start_year=start_year, end_year=end_year,
                                           fmt=fmt, definition=definition_txt, platform="X")

        results      = []
        errors       = []
        post_texts   = {}   # platform -> actual post text used (for logging)

        for platform in social_platforms:
            p = platform.strip()
            print(f"\n[SocialShare] ── {p} ──────────────────────────")
            # Build platform-specific post text — cc_en.txt content, smart-trimmed per platform
            _is_x = p in ("X", "Twitter")
            post_text = short_text if _is_x else self._build_post_text(
                topic_text, video_url, channel, website,
                short=False, start_year=start_year, end_year=end_year,
                fmt=fmt, definition=definition_txt, platform=p
            )
            post_texts[p] = post_text   # save for log
            print(f"[SocialShare] 📝 Post text ({len(post_text)} chars):\n{post_text[:200]}{'...' if len(post_text) > 200 else ''}")

            if dry_run:
                # ── DRY RUN: skip API call, record as dry_run result ──────────
                r = f"[DRY RUN] Post ready ({len(post_text)} chars) — not sent"
                results.append(f"✅ {p}: {r}")
                print(f"[SocialShare] 🧪 {p}: {r}")
                continue

            try:
                if p == "Facebook":
                    r = self._post_facebook(creds.get("Facebook", {}), post_text, video_url, image_file)
                elif p == "LinkedIn":
                    r = self._post_linkedin(creds.get("LinkedIn", {}), post_text, video_url, image_file)
                elif _is_x:
                    r = self._post_x(creds.get("X", {}), post_text, image_file)
                elif p == "YouTube":
                    r = self._post_youtube_community(creds.get("YouTube", {}), post_text, video_url)
                elif p == "Instagram":
                    r = self._post_instagram(creds.get("Instagram", {}), post_text, video_url, image_file)
                else:
                    r = f"⚠️ Unknown platform: {p}"
                results.append(f"✅ {p}: {r}")
                print(f"[SocialShare] ✅ {p}: {r}")
            except Exception as e:
                errors.append(f"❌ {p}: {str(e)}")
                print(f"[SocialShare] ❌ {p}: {str(e)}")

        self._save_share_log(output_dir, topic_text, video_url, fmt, social_platforms,
                            results, errors, channel, start_year, end_year, post_texts,
                             dry_run=dry_run)

        mode = "🧪 DRY RUN" if dry_run else "📢 Social Share"
        out = f"{mode} — {len(results)} {'previewed' if dry_run else 'posted'}, {len(errors)} failed\n"
        out += f"   Video URL: {video_url}\n"
        out += f"   Channel: @{channel}\n"
        out += f"   Year Range: {start_year}–{end_year}\n"
        if image_file:
            out += f"   Thumbnail: {image_file}\n"
        if website:
            out += f"   Website: {website}\n"
        out += "\n"
        if results:
            out += "\n".join(f"   {r}" for r in results)
        if errors:
            out += "\n\n⚠️ Errors:\n" + "\n".join(f"   {e}" for e in errors)
        return out

    @staticmethod
    def _yt_dir(output_dir: str, fmt: str) -> str:
        """Return the YT sub-directory for this format.
        Checks YT/debate/{fmt}/ first (debate pipeline), falls back to YT/{fmt}/.
        Mirrors the same logic in yt_upload_tool so all tools stay in sync.
        """
        debate_path = os.path.join(output_dir, "YT", "debate", fmt)
        if os.path.isdir(debate_path):
            return debate_path
        return os.path.join(output_dir, "YT", fmt)

    def _load_definition_txt(self, output_dir: str, filename: str) -> str:
        """
        Load output/{filename}.txt — the topic definition file.
        Searches both absolute (anchored to project root) and relative paths.
        Returns full text stripped, or empty string if not found.
        """
        import glob as _glob

        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _pkg_dir      = os.path.dirname(_tool_dir)
        _src_dir      = os.path.dirname(_pkg_dir)
        _project_root = os.path.dirname(_src_dir)
        _output_root  = os.path.join(_project_root, "output")

        candidates = [
            os.path.join(_output_root, f"{filename}.txt"),
            os.path.join("output", f"{filename}.txt"),
            os.path.join(output_dir, f"{filename}.txt"),
            f"output/{filename}.txt",
        ]

        print(f"[SocialShare] 📖 Looking for definition txt: {filename}.txt")
        for path in candidates:
            exists = os.path.exists(path)
            print(f"[SocialShare]   {'✅' if exists else '❌'} {path}")
            if exists:
                try:
                    text = open(path, encoding="utf-8").read().strip()
                    print(f"[SocialShare] ✅ Definition txt loaded: {len(text)} chars")
                    return text
                except Exception as e:
                    print(f"[SocialShare] Warning: could not read {path}: {e}")

        # Glob fallback
        for pat in [
            os.path.join(_output_root, f"{filename[:6]}*.txt"),
            os.path.join("output", f"{filename[:6]}*.txt"),
        ]:
            matches = sorted(_glob.glob(pat))
            if matches:
                path = matches[0]
                print(f"[SocialShare] ⚠️  Glob fallback: {path}")
                try:
                    text = open(path, encoding="utf-8").read().strip()
                    print(f"[SocialShare] ✅ Definition txt loaded via glob: {len(text)} chars")
                    return text
                except Exception as e:
                    print(f"[SocialShare] Warning: glob read failed: {e}")

        print(f"[SocialShare] ⚠️  No definition txt found for: {filename}.txt")
        return ""

    def _narration_to_viral(self, raw, topic, fmt, platform):
        """Shorts: WHAT IS section only. HD: full txt trimmed to platform limit."""
        import re as _re
        if not raw: return ""
        is_shorts = fmt in ("Shorts", "ShortsHD", "Shorts4K")
        limit = PLATFORM_DEF_LIMITS.get(platform, 1000)
        if limit == 0: return ""

        if is_shorts:
            # Extract WHAT IS section — handles both formats:
            #   A) Same line:   "WHAT IS X? Content here..."
            #   B) Next lines:  "WHAT IS X?" + newline + "Content here..."
            section = ""
            all_lines = raw.splitlines()
            for i, line in enumerate(all_lines):
                stripped = line.strip()
                if not _re.match(r"WHAT IS", stripped, _re.IGNORECASE):
                    continue
                # Grab inline content after the "?"
                q_pos = stripped.find("?")
                inline = stripped[q_pos + 1:].strip() if q_pos != -1 else stripped
                # Collect continuation lines until next section header or separator
                extra  = []
                for next_line in all_lines[i + 1:]:
                    ns = next_line.strip()
                    # Stop at next ALLCAPS header like "WHY DOES IT MATTER?"
                    if ns and _re.match(r"[A-Z][A-Z ]{3,}", ns):
                        break
                    # Stop at separator lines
                    if ns and len(ns) > 4 and len(set(ns)) <= 3:
                        break
                    if ns:
                        extra.append(ns)
                parts = ([inline] if inline else []) + extra
                section = " ".join(parts).strip()
                break
            if len(section) > 400:
                cut = section.rfind(". ", 0, 400)
                section = section[:cut + 1] if cut > 0 else section[:400]
            return section

        # HD: full txt trimmed to platform limit at paragraph/sentence boundary
        text = raw
        if len(text) <= limit: return text
        cut = text.rfind("\n\n", 0, limit)
        if cut > limit * 0.5: return text[:cut].strip()
        cut = text.rfind(". ", 0, limit)
        if cut > limit * 0.5: return text[:cut + 1].strip()
        return text[:limit].strip()

    def _smart_trim_definition(self, full_text: str, platform: str, fmt: str, topic: str) -> str:
        """Wrapper — converts raw cc_en.txt narration to viral post copy via _narration_to_viral."""
        return self._narration_to_viral(full_text, topic, fmt, platform)

     
    def _build_post_text(self, topic, url, channel, website, short=False,
                     start_year=2015, end_year=2026, fmt="HD", definition="",
                     platform="LinkedIn"):
        """
        Build clean social post WITH CHANNEL HASHTAG.
        """
        year_range  = f"{start_year}-{end_year}"
        is_shorts   = fmt in ("Shorts", "ShortsHD", "Shorts4K")
        is_debate   = fmt == "debate"
        txt_body    = self._smart_trim_definition(definition, platform, fmt, topic)
        
        # Channel hashtag - lowercase, no @ symbol
        channel_hashtag = f"#{channel.lower().replace('@', '')}"

        # X / Twitter — compact only
        if short:
            if is_debate:
                text = (
                    f"{topic} — AI Debate. "
                    f"Propose. Oppose. Decide. Watch: {url} "
                    f"#AIDebate #AI #Tech {channel_hashtag}"
                )
            elif is_shorts:
                text = (
                    f"[Short] {topic} {year_range} in 60 seconds. "
                    f"Who dominated? Find out: {url} "
                    f"#Shorts #AI #BarRace #DataViz {channel_hashtag}"
                )
            else:
                text = (
                    f"{topic} {year_range} -- "
                    f"Who led the race? Full breakdown: {url} "
                    f"#AI #DataVisualization #BarRace #MachineLearning {channel_hashtag}"
                )
            return text[:280]

        if is_debate:
            lines = [
                f"{topic} — AI Debate",
                " ",
                f"Watch now: {url}",
            ]
            if txt_body:
                lines += [" ", txt_body]
            lines += [
                " ",
                f"Subscribe to @{channel} for more AI debates and data-driven content.",
            ]
            if website:
                lines.append(f"More: {website}")
            lines += [" ", f"#AIDebate #AI #MachineLearning #Tech #FutureOfWork #TechDebate {channel_hashtag}"]

        elif is_shorts:
            lines = [
                f"[Short] {topic} -- Bar Race {year_range}",
                " ",
                f"Watch now: {url}",
            ]
            if txt_body:
                lines += [
                    " ",
                    f"What is {topic}? ",
                    txt_body,
                ]
            if website:
                lines.append(f"More: {website}")
            lines += [" ", f"#Shorts #AI #DataVisualization #BarRace #MachineLearning #TechTrends {channel_hashtag}"]

        else:
            lines = [
                f"{topic} -- Bar Race {year_range}",
                " ",
                f"Watch now: {url}",
            ]
            if txt_body:
                lines += [" ", txt_body]
            lines += [
                " ",
                f"Subscribe to @{channel} for more data-driven tech animations.",
            ]
            if website:
                lines.append(f"More: {website}")
            lines += [" ", f"#AI #MachineLearning #LLM #DataVisualization #BarRace #TechTrends {channel_hashtag}"]

        return "\n".join(lines)
    def _post_facebook(self, creds: dict, text: str, url: str, image_path: Optional[str] = None) -> str:
        """Post to Facebook Page via Graph API with optional image attachment."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        page_id = creds.get("page_id", "")
        access_token = creds.get("access_token", "")
        if not page_id or not access_token or "YOUR_" in access_token:
            raise RuntimeError("Facebook credentials not configured in input/social_credentials.json")

        if image_path and os.path.exists(image_path):
            # Upload image to /photos with message (correct endpoint for file upload)
            endpoint = f"https://graph.facebook.com/v19.0/{page_id}/photos"
            img_file = open(image_path, 'rb')
            payload  = {'message': f"{text}\n\n🎬 {url}", 'access_token': access_token}
            resp     = requests.post(endpoint, data=payload, files={'source': img_file}, timeout=60)
            img_file.close()
        else:
            # Text + link post (no image)
            endpoint = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload  = {"message": text, "link": url, "access_token": access_token}
            resp     = requests.post(endpoint, data=payload, timeout=30)

        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Graph API error: {data['error'].get('message', data)}")

        post_id = data.get("id", "unknown")
        return f"Posted — post_id: {post_id}" + (" 🖼️ +image" if image_path else "")

    def _post_linkedin(self, creds: dict, text: str, url: str, image_path: Optional[str] = None) -> str:
        """Post to LinkedIn Organization or Person via API v2 with optional image upload."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        access_token = creds.get("access_token", "")
        owner = creds.get("owner", "")
        if not access_token or not owner or "YOUR_" in access_token:
            raise RuntimeError("LinkedIn credentials not configured in input/social_credentials.json")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        if image_path and os.path.exists(image_path):
            # STEP 1: Register upload to get asset URN and upload URL
            register_payload = {
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": owner,
                    "serviceRelationships": [{
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }]
                }
            }
            register_resp = requests.post(
                "https://api.linkedin.com/v2/assets?action=registerUpload",
                headers=headers,
                json=register_payload,
                timeout=30
            )
            if register_resp.status_code not in (200, 201):
                raise RuntimeError(f"LinkedIn register upload failed: {register_resp.status_code}")

            register_data = register_resp.json().get("value", {})
            asset_urn = register_data.get("asset")
            upload_mechanism = register_data.get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
            upload_url = upload_mechanism.get("uploadUrl")
            upload_headers = upload_mechanism.get("headers", {})

            if not asset_urn or not upload_url:
                raise RuntimeError("Failed to get asset URN or upload URL from LinkedIn")

            # STEP 2: Upload image binary
            with open(image_path, 'rb') as img_file:
                img_data = img_file.read()

            upload_headers["Authorization"] = f"Bearer {access_token}"
            upload_resp = requests.post(upload_url, headers=upload_headers, data=img_data, timeout=60)
            if upload_resp.status_code not in (200, 201, 204):
                raise RuntimeError(f"LinkedIn image upload failed: {upload_resp.status_code}")

            # STEP 3: Create post with image URN
            body = {
                "author": owner,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "IMAGE",
                        "media": [{
                            "status": "READY",
                            "media": asset_urn,
                            "title": {"text": text[:100]},
                            "description": {"text": f"Watch: {url}"}
                        }]
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
            }
        else:
            # Fallback: Article/link post without image
            body = {
                "author": owner,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "ARTICLE",
                        "media": [{
                            "status": "READY",
                            "originalUrl": url,
                            "title": {"text": text[:100]},
                        }]
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
            }

        resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=body, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"LinkedIn API {resp.status_code}: {resp.text[:200]}")

        post_id = resp.headers.get("x-restli-id") or resp.json().get("id", "unknown")
        return f"Posted — post_id: {post_id}" + (" 🖼️ +image" if image_path else "")

    def _post_x(self, creds: dict, text: str, image_path: Optional[str] = None) -> str:
        """Post tweet via Twitter API v2 with optional media upload."""
        try:
            import requests
            from requests_oauthlib import OAuth1
        except ImportError:
            raise RuntimeError("Install: pip install requests requests-oauthlib")

        api_key = creds.get("api_key", "")
        api_secret = creds.get("api_secret", "")
        at = creds.get("access_token", "")
        at_secret = creds.get("access_token_secret", "")
        if not api_key or "YOUR_" in api_key:
            raise RuntimeError("X credentials not configured in input/social_credentials.json")

        auth = OAuth1(api_key, api_secret, at, at_secret)
        base_url = "https://api.twitter.com/2"

        media_ids = []
        if image_path and os.path.exists(image_path):
            if os.path.getsize(image_path) < 5 * 1024 * 1024:
                with open(image_path, 'rb') as f:
                    files = {'media': f}
                    upload_resp = requests.post(f"{base_url}/media/upload", auth=auth, files=files, timeout=60)
                    if upload_resp.status_code == 200:
                        media_id = upload_resp.json().get("media_id_string")
                        if media_id:
                            media_ids.append(media_id)

        payload = {"text": text[:280]}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}

        resp = requests.post(f"{base_url}/tweets", auth=auth, json=payload, timeout=30)
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"X API error: {data['errors']}")

        tweet_id = data.get("data", {}).get("id", "unknown")
        return f"Tweeted — tweet_id: {tweet_id}" + (" 🖼️ +image" if media_ids else "")

    def _post_youtube_community(self, creds: dict, text: str, url: str) -> str:
        """
        Handles YouTube 'sharing'.
        NOTE: YouTube Data API v3 does NOT support Community Posts.
        """
        print("[SocialShare] ℹ️  YouTube Community Posts are not supported via API.")
        return "Skipped — Feature not supported by YouTube Data API v3."

    def _post_instagram(self, creds: dict, text: str, url: str, image_path: Optional[str] = None) -> str:
        """Post to Instagram via Graph API."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        ig_user_id = creds.get("ig_user_id", "")
        access_token = creds.get("access_token", "")
        if not ig_user_id or "YOUR_" in ig_user_id:
            raise RuntimeError("Instagram credentials not configured in input/social_credentials.json")

        caption = f"{text}\n\n🎬 {url}"[:2200]

        if not (image_path and os.path.exists(image_path)):
            raise RuntimeError(
                "Instagram requires an image. No thumbnail found — ensure thumbnail is generated first."
            )

        # ── Get a public image URL ────────────────────────────────────────────
        # Instagram Graph API fetches the image from its own servers — the host
        # MUST allow hotlinking. imgbb blocks external crawlers (including Meta).
        # Priority:
        #   1. imgur_client_id  — Imgur anonymous upload (hotlinking allowed ✅)
        #   2. imgbb_api_key     — imgbb upload (may be blocked by Meta crawler ⚠️)
        #   3. image_url        — static public URL in creds (e.g. S3, CDN)
        img_url = ""

        imgur_client_id = creds.get("imgur_client_id", "")
        imgbb_key       = creds.get("imgbb_api_key", "")

        # ── Option 1: Imgur (preferred — hotlinking allowed) ─────────────────
        if imgur_client_id and not img_url:
            print(f"[SocialShare] 📤 Uploading thumbnail to Imgur: {os.path.basename(image_path)}")
            try:
                with open(image_path, "rb") as _f:
                    b64 = base64.b64encode(_f.read()).decode()
                _ir = requests.post(
                    "https://api.imgur.com/3/image",
                    headers={"Authorization": f"Client-ID {imgur_client_id}"},
                    data={"image": b64, "type": "base64"},
                    timeout=30
                ).json()
                # Imgur returns data.link — direct image URL (e.g. https://i.imgur.com/abc.jpg)
                img_url = _ir.get("data", {}).get("link", "")
                if img_url:
                    print(f"[SocialShare] ✅ Imgur upload OK: {img_url}")
                else:
                    print(f"[SocialShare] ⚠️  Imgur upload failed: {_ir}")
            except Exception as _e:
                print(f"[SocialShare] ⚠️  Imgur error: {_e}")

        # ── Option 2: imgbb (fallback — may be blocked by Meta) ──────────────
        if imgbb_key and not img_url:
            print(f"[SocialShare] 📤 Uploading thumbnail to imgbb: {os.path.basename(image_path)}")
            try:
                with open(image_path, "rb") as _f:
                    b64 = base64.b64encode(_f.read()).decode()
                _ir = requests.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": imgbb_key, "image": b64, "expiration": 604800},
                    timeout=30
                ).json()
                _data = _ir.get("data", {})
                img_url = (
                    _data.get("display_url") or
                    _data.get("image", {}).get("url") or
                    _data.get("url") or ""
                )
                if img_url:
                    print(f"[SocialShare] ✅ imgbb upload OK: {img_url}")
                    print(f"[SocialShare] ⚠️  Note: imgbb may be blocked by Meta's image crawler. Add imgur_client_id for reliability.")
                else:
                    print(f"[SocialShare] ⚠️  imgbb upload failed: {_ir}")
            except Exception as _e:
                print(f"[SocialShare] ⚠️  imgbb error: {_e}")

        # ── Option 3: static URL ──────────────────────────────────────────────
        if not img_url:
            img_url = creds.get("image_url", "")
            if img_url:
                print(f"[SocialShare] ℹ️  Using static image_url from creds: {img_url}")

        if not img_url:
            raise RuntimeError(
                "Instagram requires a public image URL. Add one of these to Instagram creds:\n"
                "  'imgur_client_id': get free at https://api.imgur.com/oauth2/addclient (select 'Anonymous usage')\n"
                "  'imgbb_api_key':   get free at https://api.imgbb.com\n"
                "  'image_url':       direct HTTPS link to your image (must allow hotlinking)"
            )

        # Validate: must be a direct image URL (jpg/png), not a page URL
        _img_url_lower = img_url.lower().split("?")[0]
        if not any(_img_url_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            print(f"[SocialShare] ⚠️  img_url may not be a direct image link: {img_url}")

        print(f"[SocialShare] 📸 Submitting to Instagram container: {img_url}")

        # Create image container — media_type=IMAGE is required by Instagram Graph API
        container_resp = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
            data={
                "image_url":  img_url,
                "media_type": "IMAGE",
                "caption":    caption,
                "access_token": access_token,
            },
            timeout=60
        ).json()

        print(f"[SocialShare] 📋 Container response: {container_resp}")

        if "error" in container_resp:
            raise RuntimeError(f"Instagram container error: {container_resp['error'].get('message', container_resp)}")

        container_id = container_resp.get("id")
        if not container_id:
            raise RuntimeError(f"Instagram container ID missing: {container_resp}")

        # Wait for container to be ready then publish
        # Poll status — can take 5-30s depending on image size
        print(f"[SocialShare] ⏳ Waiting for Instagram container ({container_id}) to be ready...")
        for _attempt in range(10):
            time.sleep(5)
            _status_resp = requests.get(
                f"https://graph.facebook.com/v19.0/{container_id}",
                params={"fields": "status_code,status", "access_token": access_token},
                timeout=15
            ).json()
            _status_code = _status_resp.get("status_code", "")
            print(f"[SocialShare]   Container status ({_attempt+1}/10): {_status_code} — {_status_resp.get('status', '')}")
            if _status_code == "FINISHED":
                break
            if _status_code == "ERROR":
                raise RuntimeError(f"Instagram container processing error: {_status_resp}")
        else:
            print(f"[SocialShare] ⚠️  Container not FINISHED after 50s — attempting publish anyway")
        publish_resp = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=30
        ).json()

        if "error" in publish_resp:
            raise RuntimeError(f"Instagram publish error: {publish_resp['error'].get('message', publish_resp)}")

        media_id = publish_resp.get("id", "unknown")
        return f"Image posted — media_id: {media_id} 🖼️"

    def _load_credentials(self) -> dict:
        if os.path.exists(CREDS_PATH):
            with open(CREDS_PATH) as f:
                return json.load(f)
        os.makedirs(os.path.dirname(CREDS_PATH), exist_ok=True)
        with open(CREDS_PATH, "w") as f:
            json.dump(CREDS_TEMPLATE, f, indent=2)
        print(f"[SocialShare] ⚠️  Created credentials template: {CREDS_PATH}")
        return {}
    def _save_share_log(self, output_dir, topic, video_url, fmt, platforms,
                    results, errors, channel, start_year, end_year, post_texts=None,
                        dry_run=False):
        """
        Save share results to:
        YT/{fmt}/share_log.json        — live run  (machine-readable)
        YT/{fmt}/share_log_dryrun.json — dry run   (machine-readable)
        YT/{fmt}/share_log.txt         — live run  (human-readable with full post bodies)
        YT/{fmt}/share_log_dryrun.txt  — dry run   (human-readable with full post bodies)
        
        MERGES with existing log to preserve ALL platforms (not just current run).
        """
        import datetime
        post_texts = post_texts or {}
        log_dir = self._yt_dir(output_dir, fmt)
        os.makedirs(log_dir, exist_ok=True)
        suffix = "_dryrun" if dry_run else ""

        # ── Parse current run results ─────────────────────────────
        parsed_results = []
        for r in results:
            platform = r.replace("✅ ", "").split(": ")[0].strip()
            detail = ": ".join(r.split(": ")[1:]).strip()
            parsed_results.append({
                "platform":  platform,
                "status":    "success",
                "detail":    detail,
                "post_text": post_texts.get(platform, ""),
            })
        for e in errors:
            platform = e.replace("❌ ", "").split(": ")[0].strip()
            detail = ": ".join(e.split(": ")[1:]).strip()
            parsed_results.append({
                "platform":  platform,
                "status":    "failed",
                "error":     detail,
                "post_text": post_texts.get(platform, ""),
            })

        # ── Load existing log (if any) to preserve ALL platforms ───
        existing_shares = []
        existing_log_path = os.path.join(log_dir, "share_log.json")
        if os.path.exists(existing_log_path) and not dry_run:
            try:
                with open(existing_log_path, "r", encoding="utf-8") as _f:
                    _existing = json.load(_f)
                existing_shares = _existing.get("shares", [])
                print(f"[SocialShare] 📖 Loaded existing share log: {len(existing_shares)} platforms")
            except Exception as _e:
                print(f"[SocialShare] ⚠️  Could not load existing log: {_e}")

        # ── Merge: new results override existing for same platform ─
        merged_shares = []
        processed_platforms = set()
        
        # Add existing shares first
        for _share in existing_shares:
            _plat = _share.get("platform", "")
            # Skip if this platform was re-processed in current run
            if any(_plat == p.get("platform") for p in parsed_results):
                continue
            merged_shares.append(_share)
        
        # Add new/updated shares
        merged_shares.extend(parsed_results)
        
        # Count success/failed
        _success = sum(1 for s in merged_shares if s.get("status") == "success")
        _failed = sum(1 for s in merged_shares if s.get("status") == "failed")

        # ── Build complete log data ────────────────────────────────
        data = {
            "topic":      topic,
            "channel":    channel,
            "year_range": f"{start_year}–{end_year}",
            "shared_at":  datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "video_url":  video_url,
            "format":     fmt,
            "dry_run":    dry_run,
            "platforms":  [s.get("platform") for s in merged_shares],  # ALL platforms
            "success":    _success,
            "failed":     _failed,
            "shares":     merged_shares,  # MERGED results
        }

        # ── Save JSON ──────────────────────────────────────────────
        json_path = os.path.join(log_dir, f"share_log{suffix}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Dry run ALSO writes share_log.json so smart-skip blocks a real accidental run
        if dry_run:
            real_log_path = os.path.join(log_dir, "share_log.json")
            with open(real_log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[SocialShare] 🧪 Dry run guard written → {real_log_path}")

        # ── Human-readable .txt log with full post bodies ──────────
        sep     = "━" * 60
        sep_mid = "─" * 60
        now_str = data["shared_at"]
        mode_label = "🧪  DRY RUN — POST PREVIEW" if dry_run else "📢  SOCIAL SHARE LOG"
        txt_lines = [
            sep,
            mode_label,
            sep,
            f"Topic      : {topic}",
            f"Channel    : @{channel}",
            f"Format     : {fmt}",
            f"Year Range : {start_year}–{end_year}",
            f"Shared at  : {now_str}",
            f"Video URL  : {video_url}",
            f"Result     : {_success} posted  |  {_failed} failed",
            f"Platforms  : {', '.join(data['platforms'])}",
            sep,
            " ",
        ]

        for s in merged_shares:
            icon   = "✅" if s["status"] == "success" else "❌"
            detail = s.get("detail") or s.get("error", "")
            p_text = s.get("post_text", "").strip()

            txt_lines += [
                f"{icon}  {s['platform']}  —  {detail}",
                sep_mid,
                "POST CONTENT:",
                p_text if p_text else "(no post text recorded)",
                " ",
            ]

        txt_lines += [sep, " "]

        txt_path = os.path.join(log_dir, f"share_log{suffix}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(txt_lines))

        print(f"[SocialShare] 💾 Share log → {json_path}")
        print(f"[SocialShare] 💾 Share log → {txt_path}")
        print(f"[SocialShare] 📊 Total platforms logged: {len(merged_shares)}")
    
    
    