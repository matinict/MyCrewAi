"""
YouTube Upload Tool
Automates video uploads and multi-language subtitle (CC) injection.
Matches the directory structure: output/{Topic}/YT/{Format}/CC/

Improvements:
- Upload timeout (120s per chunk) with automatic retry (3 attempts)
- quotaExceeded on video upload → fails fast immediately (no pointless retries)
- Log saved IMMEDIATELY after video upload (before CC) — timeout won't lose video_id
- CC quota-exceeded → stops immediately, logs failed langs for retry
- Smart skip: already-uploaded formats skipped via upload_log.json
"""

import os
import json
import time
from typing import Type, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

# Google API libraries are lazy-imported inside methods.
# Install with: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client

CHUNK_SIZE      = 5 * 1024 * 1024   # 5 MB chunks (smaller = less data lost on timeout)
CHUNK_TIMEOUT   = 120                # seconds per chunk before raising timeout
MAX_RETRIES     = 3                  # chunk-level retries on timeout/transient error
RETRY_BACKOFF   = [5, 15, 30]        # seconds between retries


class YTUploadToolInput(BaseModel):
    """Input schema for YTUploadTool."""
    topic:                str   = Field(...,  description="Topic name (e.g., 'LLM Alignment RLHF')")
    output_dir:           str   = Field(...,  description="Full path to the output/Topic directory")
    video_formats:        list  = Field(...,  description="Formats to upload: ['HD', 'Shorts']")
    upload_youtube_video: bool  = Field(default=False,               description="Master switch — must be true to upload")
    channel:              str   = Field(default="PlayOwnAi",         description="Channel prefix for video filename lookup")
    privacy_status:       str   = Field(default="private",           description="private | unlisted | public")
    category_id:          str   = Field(default="28",                description="YouTube category ID. 28=Science & Tech, 27=Education")
    upload_cc:            bool  = Field(default=True,                description="Upload CC subtitle files after video upload")
    notify_subscribers:   bool  = Field(default=False,               description="Notify subscribers on upload")
    client_secrets_file:  str   = Field(default="client_secrets.json", description="Path to OAuth2 client secrets JSON")
    token_file:           str   = Field(default="token.json",        description="Path to saved OAuth2 token (auto-created on first run)")
    thumbnail_path:       str   = Field(default="",                  description="Path to thumbnail image (JPG/PNG). Auto-detected if empty.")


class YTUploadTool(BaseTool):
    name: str = "yt_upload_tool"
    description: str = "Uploads videos and 30+ language subtitles to YouTube automatically."
    args_schema: Type[BaseModel] = YTUploadToolInput

    SCOPES: List[str] = [
        'https://www.googleapis.com/auth/youtube.upload',
        'https://www.googleapis.com/auth/youtube.force-ssl'
    ]

    def _run(self, topic: str, output_dir: str, video_formats: list,
             upload_youtube_video: bool = False, channel: str = "PlayOwnAi",
             privacy_status: str = "private", category_id: str = "28",
             upload_cc: bool = True, notify_subscribers: bool = False,
             client_secrets_file: str = "client_secrets.json",
             token_file: str = "token.json",
             thumbnail_path: str = "") -> str:

        import re as _re

        if not upload_youtube_video:
            return "🔇 YouTube upload skipped (upload_youtube_video=false)."

        try:
            from googleapiclient.discovery import build
        except ImportError:
            return ("❌ Missing Google API libraries.\n"
                    "Run: pip install google-auth google-auth-oauthlib "
                    "google-auth-httplib2 google-api-python-client")

        if not os.path.exists(output_dir):
            return f"❌ Output directory not found: {output_dir}"

        # Normalize video_formats
        if isinstance(video_formats, str):
            video_formats = [v.strip() for v in _re.findall(r"[A-Za-z0-9]+", video_formats)]
        _valid = {"HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"}
        video_formats = [f for f in video_formats if f in _valid] or ["HD"]

        print(f"[YTUpload] 🚀 Starting — formats: {video_formats} | privacy: {privacy_status}")

        try:
            creds = self._get_credentials(client_secrets_file, token_file)
            youtube = build("youtube", "v3", credentials=creds)
            print(f"[YTUpload] ✅ Authenticated")
        except Exception as e:
            return f"❌ Auth Error: {str(e)}"

        results = []
        errors  = []

        for fmt in video_formats:
            fmt = fmt.strip()
            print(f"\n[YTUpload] ── Format: {fmt} ──────────────────")

            # ── Smart skip: check upload log ──────────────────────────────
            log_path = os.path.join(output_dir, "YT", fmt, "upload_log.json")
            if os.path.exists(log_path):
                try:
                    with open(log_path) as _lf:
                        _log = json.load(_lf)
                    vid_id = _log.get("video_id", "")
                    if vid_id:
                        url = f"https://youtu.be/{vid_id}"
                        notes = []

                        # ── Check CC: compare disk files vs what's on YouTube ──
                        import os as _os2
                        cc_dir_check = _os2.path.join(output_dir, "YT", fmt, "CC")
                        cc_total_on_disk = len([f for f in _os2.listdir(cc_dir_check) if f.endswith(".txt")]) if _os2.path.exists(cc_dir_check) else 0
                        # Ask YouTube how many captions the video actually has
                        try:
                            from googleapiclient.errors import HttpError as _HE
                            _cap_resp = youtube.captions().list(part="snippet", videoId=vid_id).execute()
                            cc_on_yt  = len(_cap_resp.get("items", []))
                        except Exception:
                            cc_on_yt  = _log.get("cc_uploaded", 0)
                        cc_failed = _log.get("cc_failed", 0)
                        cc_needs_upload = upload_cc and (cc_on_yt < cc_total_on_disk)
                        if cc_needs_upload:
                            reason = f"{cc_on_yt}/{cc_total_on_disk} on YouTube"
                            print(f"[YTUpload] ♻️  {fmt}: Video already uploaded ({vid_id}), uploading CC ({reason})")
                            cc_stats = self._upload_cc_files(youtube, vid_id, output_dir, fmt)
                            _log["cc_uploaded"] = _log.get("cc_uploaded", 0) + cc_stats["uploaded"]
                            _log["cc_failed"]   = cc_stats["failed"]
                            _log["cc_skipped"]  = _log.get("cc_skipped", 0) + cc_stats["skipped"]
                            with open(log_path, "w") as _lf:
                                json.dump(_log, _lf, indent=2)
                            notes.append(f"CC: +{cc_stats['uploaded']} uploaded, {cc_stats['failed']} failed")
                        else:
                            print(f"[YTUpload] ⏭️  {fmt}: CC complete ({cc_on_yt}/{cc_total_on_disk})")

                        # ── Localizations: always re-upload to keep in sync ────
                        _loc = self._upload_localizations(youtube, vid_id, output_dir, fmt)
                        _log["loc_uploaded"] = _loc["uploaded"]
                        with open(log_path, "w") as _lf:
                            json.dump(_log, _lf, indent=2)
                        notes.append(f"Loc: {_loc['uploaded']} languages")

                        note_str = " | ".join(notes) if notes else "all done"
                        results.append(f"⏭️ {fmt}: Already uploaded → {url} ({note_str})")
                        continue
                except Exception:
                    pass  # Corrupt log — proceed with upload

            # ── Find video file ────────────────────────────────────────────
            topic_slug = "_".join(_re.findall(r"\w+", topic)[:4]) if topic else "Video"
            video_name = f"{channel}_{topic_slug}_{fmt}.mp4"
            video_path = os.path.join(output_dir, video_name)

            if not os.path.exists(video_path):
                import glob as _glob
                seg_pfx = ("intro_", "bar_race_", "definition_video_", "_norm_")
                matches = [p for p in _glob.glob(os.path.join(output_dir, f"*_{fmt}.mp4"))
                           if not any(os.path.basename(p).startswith(px) for px in seg_pfx)]
                if matches:
                    video_path = matches[0]
                    print(f"[YTUpload] ⚠️  Fallback: {os.path.basename(video_path)}")
                else:
                    errors.append(f"❌ {fmt}: Video not found (expected: {video_name})")
                    print(f"[YTUpload] ❌ {fmt}: No video file — skipping")
                    continue

            # ── Load metadata ──────────────────────────────────────────────
            metadata_path = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
            metadata = self._load_metadata(metadata_path, topic)
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            print(f"[YTUpload]   📤 {os.path.basename(video_path)} ({size_mb:.1f} MB) → {privacy_status}")

            try:
                video_id = self._upload_video(
                    youtube, video_path, metadata, privacy_status, category_id, fmt
                )

                # ── Save log IMMEDIATELY after video upload ────────────────
                # This ensures the video_id is never lost, even if CC upload
                # times out or hits quota on a subsequent run.
                log_entry = {
                    "video_id":    video_id,
                    "video_url":   f"https://youtu.be/{video_id}",
                    "video_file":  os.path.basename(video_path),
                    "format":      fmt,
                    "privacy":     privacy_status,
                    "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "cc_uploaded": 0,
                    "cc_skipped":  0,
                    "cc_failed":   0,
                }
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w") as _lf:
                    json.dump(log_entry, _lf, indent=2)
                print(f"[YTUpload]   💾 Log saved → YT/{fmt}/upload_log.json (video secured)")

                # ── Upload CC files ────────────────────────────────────────
                cc_stats = {"uploaded": 0, "skipped": 0, "failed": 0}
                if upload_cc:
                    cc_stats = self._upload_cc_files(youtube, video_id, output_dir, fmt)
                    # Update log with CC results
                    log_entry.update({
                        "cc_uploaded": cc_stats["uploaded"],
                        "cc_skipped":  cc_stats["skipped"],
                        "cc_failed":   cc_stats["failed"],
                    })
                    with open(log_path, "w") as _lf:
                        json.dump(log_entry, _lf, indent=2)

                # ── Upload localizations (title & description per language) ──
                loc_stats = self._upload_localizations(youtube, video_id, output_dir, fmt)
                log_entry["loc_uploaded"] = loc_stats["uploaded"]
                with open(log_path, "w") as _lf:
                    json.dump(log_entry, _lf, indent=2)

                # ── Upload thumbnail ──────────────────────────────────
                thumb_note = ""
                _thumb_path = thumbnail_path
                if not _thumb_path:
                    # Auto-detect: look for filename.jpg or filename.png in output_dir
                    import glob as _tglob
                    _candidates = (
                        [p for p in _tglob.glob(os.path.join(output_dir, "*.jpg"))
                         if not os.path.basename(p).startswith("PlayOwnAi")] +
                        [p for p in _tglob.glob(os.path.join(output_dir, "*.png"))
                         if not os.path.basename(p).startswith("PlayOwnAi")]
                    )
                    _thumb_path = _candidates[0] if _candidates else ""
                if _thumb_path and os.path.exists(_thumb_path):
                    try:
                        _ext = os.path.splitext(_thumb_path)[1].lower()
                        _mime = "image/jpeg" if _ext in (".jpg", ".jpeg") else "image/png"
                        from googleapiclient.http import MediaFileUpload as _MFU
                        youtube.thumbnails().set(
                            videoId=video_id,
                            media_body=_MFU(_thumb_path, mimetype=_mime)
                        ).execute()
                        thumb_note = f" | Thumbnail: ✅ {os.path.basename(_thumb_path)}"
                        print(f"[YTUpload]   🖼️  Thumbnail uploaded: {os.path.basename(_thumb_path)}")
                    except Exception as _te:
                        thumb_note = f" | Thumbnail: ❌ {_te}"
                        print(f"[YTUpload]   ⚠️  Thumbnail upload failed: {_te}")
                else:
                    print(f"[YTUpload]   ⚠️  No thumbnail found — skipping")

                url = f"https://youtu.be/{video_id}"
                cc_note = f"CC: {cc_stats['uploaded']} uploaded, {cc_stats['skipped']} skipped"
                if cc_stats["failed"] > 0:
                    cc_note += f", {cc_stats['failed']} failed (run again to retry)"
                results.append(f"✅ {fmt}: {url} ({cc_note}{thumb_note})")

            except Exception as e:
                errors.append(f"❌ {fmt}: Upload failed — {str(e)}")
                print(f"[YTUpload] ❌ {fmt}: {e}")

        summary = self._format_summary(results, errors)
        self._save_upload_summary(results, errors, output_dir, topic)
        return summary

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    def _get_credentials(self, client_secrets_file="client_secrets.json", token_file="token.json"):
        """OAuth2 auth. Opens browser on first run, saves token.json for reuse."""
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                print(f"[YTUpload] 🔑 Token refreshed")
            else:
                if not os.path.exists(client_secrets_file):
                    raise RuntimeError(
                        f"client_secrets.json not found at: {client_secrets_file}\n"
                        "Download from: console.cloud.google.com → APIs & Services → Credentials"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
                print(f"[YTUpload] 🔑 New token obtained")
            with open(token_file, "w") as _tf:
                _tf.write(creds.to_json())
            print(f"[YTUpload] 💾 Token saved → {token_file}")
        return creds

    # ── Video upload with timeout + retry ─────────────────────────────────────

    def _upload_video(self, youtube, file_path, metadata, privacy,
                      category_id="28", fmt=""):
        from googleapiclient.http import MediaFileUpload
        import socket

        # Strip emoji / non-printable chars from free-text fields (title, description)
        def _clean_text(t):
            import re as _re
            t = str(t)
            t = _re.sub(u'[\U00002000-\U0010FFFF]', '', t)
            t = _re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u00C0-\u024F\u0400-\u04FF]', '', t)
            return t.strip()

        tags = []
        seen = set()
        total_len = 0
        for t in raw_tags:
            ct = _clean_tag(t)
            if not ct or ct.lower() in seen:
                continue
            if total_len + len(ct) > 500:
                break
            tags.append(ct)
            seen.add(ct.lower())
            total_len += len(ct)

        is_shorts = fmt in ("Shorts", "ShortsHD", "Shorts4K")
        if is_shorts:
            if "#Shorts" not in title:
                title = f"{title} #Shorts"
            for st in ["Shorts", "Short"]:
                if st.lower() not in seen and total_len + len(st) <= 500:
                    tags.insert(0, st)
                    seen.add(st.lower())
                    total_len += len(st)

        body = {
            "snippet": {
                "title":           title,
                "description":     _clean_text(
                    metadata.get("description", "") +
                    (("\n\n" + metadata["chapters"]) if metadata.get("chapters") else "")
                )[:5000],
                "tags":            tags,
                "categoryId":      category_id,
                "defaultLanguage":      "en",
                "defaultAudioLanguage": "en",
            },
            "status": {
                "privacyStatus":           privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media   = MediaFileUpload(file_path, chunksize=CHUNK_SIZE, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response  = None
        last_pct  = -1
        t0        = time.time()
        attempt   = 0

        # Set socket timeout so hung connections don't block forever
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(CHUNK_TIMEOUT)

        try:
            while response is None:
                try:
                    status, response = request.next_chunk()
                    attempt = 0  # reset on success
                    if status:
                        pct = int(status.progress() * 100)
                        if pct != last_pct:
                            print(f"[YTUpload]   ⬆️  {pct}% ({int(time.time()-t0)}s elapsed)")
                            last_pct = pct
                except Exception as chunk_err:
                    err_str = str(chunk_err)
                    # Fail fast on non-retryable errors
                    if "quotaExceeded" in err_str:
                        raise RuntimeError(
                            "YouTube API quota exceeded. "
                            "Resets at midnight Pacific Time (PT). "
                            "Request increase: console.cloud.google.com → "
                            "APIs & Services → YouTube Data API v3 → Quotas"
                        )
                    if "400" in err_str and "invalidTags" in err_str:
                        raise RuntimeError(
                            f"Invalid tags in metadata — check en.json tags field: {err_str}"
                        )
                    if "400" in err_str:
                        raise RuntimeError(f"Bad request (non-retryable): {err_str}")
                    attempt += 1
                    if attempt > MAX_RETRIES:
                        raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries: {err_str}")
                    wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
                    print(f"[YTUpload]   ⚠️  Chunk error (attempt {attempt}/{MAX_RETRIES}): {err_str}")
                    print(f"[YTUpload]   ⏳ Retrying in {wait}s …")
                    time.sleep(wait)
                    # next_chunk() on a resumable upload will resume from last committed byte
        finally:
            socket.setdefaulttimeout(old_timeout)

        video_id = response.get("id", "")
        print(f"[YTUpload] ✅ Upload complete → https://youtu.be/{video_id} ({int(time.time()-t0)}s)")
        return video_id


        title = _clean_text(metadata.get("title", "AI Video"))[:100]
        raw_tags = list(metadata.get("tags", []))

        # Sanitize tags: strip leading #, emoji, special chars, max 30 chars each
        def _clean_tag(t):
            import re as _re
            t = str(t).strip().lstrip('#')
            # Remove emoji and symbols (U+2000 and above covers all emoji)
            t = _re.sub(u'[\U00002000-\U0010FFFF]', '', t)
            # Remove YouTube-rejected chars
            t = _re.sub(r'[<>&]', '', t)
            t = t.replace('"', '').replace("'", '')
            # Keep only safe printable chars
            t = _re.sub(r'[^\x20-\x7E\u00C0-\u024F]', '', t)
            return t[:30].strip()


        # Strip emoji from free-text fields (title, description)
    # ── CC upload with quota early-exit ───────────────────────────────────────

    @staticmethod
    def _text_to_srt(text: str) -> str:
        """Convert plain narration text to SRT subtitle format.
        Splits text into ~10-word chunks with auto-generated timestamps."""
        import math
        words = text.split()
        if not words:
            return "1\n00:00:00,000 --> 00:00:05,000\n \n"

        chunk_size = 10  # words per subtitle line
        chunks = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]
        secs_per_chunk = 4.0  # approximate display time per chunk

        lines = []
        for i, chunk in enumerate(chunks):
            start_s = i * secs_per_chunk
            end_s   = start_s + secs_per_chunk

            def _fmt(s):
                h = int(s // 3600)
                m = int((s % 3600) // 60)
                sec = s % 60
                return f"{h:02d}:{m:02d}:{int(sec):02d},{int((sec % 1)*1000):03d}"

            lines.append(str(i + 1))
            lines.append(f"{_fmt(start_s)} --> {_fmt(end_s)}")
            lines.append(" ".join(chunk))
            lines.append("")

        return "\n".join(lines)

    # Map our ISO file codes → YouTube BCP-47 codes (used for BOTH CC and localizations)
    # CRITICAL: both must use the same code or YouTube creates duplicate rows per language
    _LANG_MAP = {
        "zh-cn":    "zh-Hans",   # Simplified Chinese
        "zh-tw":    "zh-Hant",   # Traditional Chinese
        "sr":       "sr-Latn",   # Serbian Latin
        "he":       "iw",        # Hebrew (YouTube still uses legacy "iw")
        "id":       "id",        # Indonesian (no change, but explicit)
        "fil":      "fil",       # Filipino
        "nb":       "no",        # Norwegian Bokmål → YouTube uses "no"
    }

    def _upload_localizations(self, youtube, video_id, output_dir, fmt):
        """Upload translated title & description for all languages via YouTube localizations API."""
        import re as _re2

        def _clean(t, limit):
            t = _re2.sub(u"[ -􏿿]", "", str(t))
            t = _re2.sub(r"[<>&]", "", t)
            return t.strip()[:limit]

        def _parse_md_txt(path):
            try:
                text = open(path, encoding="utf-8").read()
                title_m = _re2.search("TITLE:\n(.+?)(?:\n\n|\nDESCRIPTION:)", text, _re2.DOTALL)
                desc_m  = _re2.search("DESCRIPTION:\n(.+?)(?:\n\n|\nTAGS:|$)",  text, _re2.DOTALL)
                return (
                    title_m.group(1).strip() if title_m else "",
                    desc_m.group(1).strip()  if desc_m  else "",
                )
            except Exception:
                return "", ""

        md_dir = os.path.join(output_dir, "YT", fmt, "MD")
        if not os.path.exists(md_dir):
            print(f"[YTUpload]   ⚠️  No MD dir: {md_dir}")
            return {"uploaded": 0, "failed": 0}

        # Fetch existing localizations so we can merge (not overwrite)
        try:
            existing_resp = youtube.videos().list(
                part="localizations", id=video_id).execute()
            existing_locs = existing_resp["items"][0].get("localizations", {}) if existing_resp.get("items") else {}
        except Exception:
            existing_locs = {}

        # Build localizations dict — merge with existing
        localizations = dict(existing_locs)  # start from what's already there
        lang_files = [f for f in os.listdir(md_dir) if f.endswith(".txt") and f != "en.txt"]
        added = 0
        for fname in lang_files:
            raw_code = fname.replace(".txt", "")
            yt_code  = self._LANG_MAP.get(raw_code, raw_code)  # map to YT BCP-47
            title, desc = _parse_md_txt(os.path.join(md_dir, fname))
            if title:
                localizations[yt_code] = {
                    "title":       _clean(title, 100),
                    "description": _clean(desc,  5000),
                }
                added += 1

        if not added:
            print(f"[YTUpload]   ⚠️  No translated MD files found in {md_dir}")
            return {"uploaded": 0, "failed": 0}

        print(f"[YTUpload]   🌍 Uploading localizations for {added} languages …")
        try:
            youtube.videos().update(
                part="localizations",
                body={"id": video_id, "localizations": localizations},
            ).execute()
            print(f"[YTUpload]   ✅ Localizations uploaded: {added} languages")
            return {"uploaded": added, "failed": 0}
        except Exception as e:
            print(f"[YTUpload]   ❌ Localizations upload failed: {e}")
            return {"uploaded": 0, "failed": added}

    def _upload_cc_files(self, youtube, video_id, output_dir, fmt):
        """Upload CC files from YT/{fmt}/CC/. Stops immediately on quota exceeded."""
        from googleapiclient.http import MediaInMemoryUpload
        from googleapiclient.errors import HttpError

        cc_dir = os.path.join(output_dir, "YT", fmt, "CC")
        stats  = {"uploaded": 0, "skipped": 0, "failed": 0, "quota_hit": False}

        if not os.path.exists(cc_dir):
            print(f"[YTUpload]   ⚠️  No CC dir: {cc_dir}")
            return stats

        # Check what's already on the video
        try:
            existing       = youtube.captions().list(part="snippet", videoId=video_id).execute()
            existing_langs = {c["snippet"]["language"] for c in existing.get("items", [])}
        except HttpError as e:
            if "quotaExceeded" in str(e):
                print(f"[YTUpload]   🛑 CC quota exceeded on list() — skipping CC entirely. Try tomorrow.")
                stats["failed"] = len([f for f in os.listdir(cc_dir) if f.endswith(".txt")])
                return stats
            existing_langs = set()
        except Exception:
            existing_langs = set()

        cc_files = sorted(f for f in os.listdir(cc_dir) if f.endswith(".txt"))
        # Map raw filename codes to BCP-47 before comparing with existing_langs
        pending  = [f for f in cc_files
                    if self._LANG_MAP.get(f.replace(".txt",""), f.replace(".txt",""))
                    not in existing_langs]
        already  = len(cc_files) - len(pending)

        print(f"[YTUpload]   📝 CC: {len(cc_files)} total | {already} already uploaded | {len(pending)} to upload")
        if already:
            stats["skipped"] += already

        for filename in pending:
            raw_code  = filename.replace(".txt", "")
            lang_code = self._LANG_MAP.get(raw_code, raw_code)  # map to YouTube BCP-47
            file_path = os.path.join(cc_dir, filename)

            try:
                cc_text = open(file_path, encoding="utf-8").read().strip()
                if not cc_text:
                    stats["skipped"] += 1
                    continue

                # Convert plain text to SRT format for proper YouTube CC
                srt_content = self._text_to_srt(cc_text)
                media = MediaInMemoryUpload(srt_content.encode("utf-8"), mimetype="application/x-subrip")
                youtube.captions().insert(
                    part="snippet",
                    body={"snippet": {
                        "videoId":  video_id,
                        "language": lang_code,
                        "name":     "",        # empty = YouTube uses the language display name
                        "isDraft":  False,     # no suffix like "Arabic - ar" (was causing double rows)
                    }},
                    media_body=media
                ).execute()
                print(f"[YTUpload]     ✅ CC {lang_code}")
                stats["uploaded"] += 1
                time.sleep(0.3)

            except HttpError as e:
                if "quotaExceeded" in str(e):
                    # Count remaining pending files (exclude already-processed ones)
                    pending_done = stats["uploaded"] + stats["failed"]
                    remaining = max(0, len(pending) - pending_done - 1)
                    stats["failed"] += 1 + remaining
                    stats["quota_hit"] = True
                    print(f"[YTUpload]     ❌ CC {lang_code}: quota exceeded")
                    print(f"[YTUpload]   🛑 Quota hit — stopping CC upload. "
                          f"{stats['failed']} lang(s) failed. Run again tomorrow to retry.")
                    break
                else:
                    print(f"[YTUpload]     ❌ CC {lang_code}: {e}")
                    stats["failed"] += 1

            except Exception as e:
                print(f"[YTUpload]     ❌ CC {lang_code}: {e}")
                stats["failed"] += 1

        return stats

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_metadata(self, path, topic):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {"title": topic, "description": "AI Generated Content", "tags": ["AI"]}

    def _save_upload_summary(self, results, errors, output_dir, topic):
        """Save final upload summary JSON + TXT after all formats complete."""
        import datetime
        summary_dir = os.path.join(output_dir, "YT")
        os.makedirs(summary_dir, exist_ok=True)

        parsed = []
        for r in results:
            fmt_match = r.replace("✅ ", "").split(": ", 1)
            fmt  = fmt_match[0].strip() if len(fmt_match) > 1 else "unknown"
            rest = fmt_match[1] if len(fmt_match) > 1 else r
            url_match = [w for w in rest.split() if w.startswith("https://")]
            url = url_match[0] if url_match else ""
            video_id = url.replace("https://youtu.be/", "") if url else ""
            parsed.append({
                "format":         fmt,
                "video_id":       video_id,
                "video_url":      url,
                "youtube_studio": f"https://studio.youtube.com/video/{video_id}/edit" if video_id else "",
                "cc_note":        rest.split("(")[-1].rstrip(")") if "(" in rest else "",
                "status":         "success",
            })

        for e in errors:
            fmt = e.replace("❌ ", "").split(":")[0].strip()
            parsed.append({"format": fmt, "status": "failed", "error": e})

        data = {
            "topic":       topic,
            "uploaded_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total":       len(results) + len(errors),
            "success":     len(results),
            "failed":      len(errors),
            "uploads":     parsed,
        }

        json_path = os.path.join(summary_dir, "upload_summary.json")
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        txt_path = os.path.join(summary_dir, "upload_summary.txt")
        sep = "━" * 52
        lines = [
            sep,
            "📺 YOUTUBE UPLOAD SUMMARY",
            f"Topic     : {topic}",
            f"Uploaded  : {data['uploaded_at']}",
            f"Success   : {data['success']} / {data['total']}",
            sep, "",
        ]
        for u in parsed:
            if u["status"] == "success":
                lines += [
                    f"✅ {u['format']}",
                    f"   URL     : {u['video_url']}",
                    f"   Studio  : {u['youtube_studio']}",
                    f"   CC      : {u['cc_note']}",
                    "",
                ]
            else:
                lines += [f"❌ {u['format']} — {u.get('error', '')}", ""]
        lines.append(sep)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("".join(lines))

        print(f"[YTUpload] 💾 Summary → {json_path}")
        print(f"[YTUpload] 💾 Summary → {txt_path}")

    def _format_summary(self, results, errors):
        if not results and not errors:
            return "ℹ️ No formats processed"
        lines = []
        if results:
            lines.append(f"✅ YouTube Upload ({len(results)} format(s)):")
            lines.extend(f"   • {r}" for r in results)
        if errors:
            lines.append(f"\n⚠️ Errors ({len(errors)}):")
            lines.extend(f"   • {e}" for e in errors)
        return "\n".join(lines)
