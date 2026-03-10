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
- upload_cc_languages: allowlist filter e.g. ["en"] uploads only those langs
- upload_cc_lang / upload_md_lang: string-based limits e.g. "5" / "35"
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
    upload_cc_languages:  list  = Field(default_factory=list,        description="Allowlist of CC language codes to upload e.g. ['en','fr']. Empty = all.")
    upload_cc_lang:       str   = Field(default="0",                 description="Max CC languages to upload as string (0 = all). e.g. '5'")
    upload_md_lang:       str   = Field(default="0",                 description="Max MD localizations to upload as string (0 = all). e.g. '35'")
    notify_subscribers:   bool  = Field(default=False,               description="Notify subscribers on upload")
    client_secrets_file:  str   = Field(default="client_secrets.json", description="Path to OAuth2 client secrets JSON")
    token_file:           str   = Field(default="token.json",        description="Path to saved OAuth2 token (auto-created on first run)")
    thumbnail_path:       str   = Field(default="",                  description="Path to thumbnail image (JPG/PNG). Auto-detected if empty.")
    dry_run:              bool  = Field(default=False,               description="Dry run — validate files and metadata but skip actual upload")
    upload_cc_limit:      int   = Field(default=0,                   description="Max CC languages to upload (0 = all)")
    upload_md_limit:      int   = Field(default=0,                   description="Max MD localizations to upload (0 = all)")


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
             upload_cc: bool = True, upload_cc_languages: list = None,
             upload_cc_lang: str = "0", upload_md_lang: str = "0",
             notify_subscribers: bool = False,
             client_secrets_file: str = "client_secrets.json",
             token_file: str = "token.json",
             thumbnail_path: str = "",
             upload_cc_limit: int = 0,
             upload_md_limit: int = 0,
             dry_run: bool = False) -> str:

        import re as _re

        # ── Load lang.json once — rank order + yt_code map + cc eligibility ──
        self._lang_map, self._rank_order, self._cc_eligible = self._load_lang_config()
        _cc_lim_str = str(upload_cc_limit) if upload_cc_limit > 0 else "all"
        _md_lim_str = str(upload_md_limit) if upload_md_limit > 0 else "all"

        # Resolve string-based lang limits (e.g. "5", "35") → int, merging with int fields
        try:
            _cc_lang_int = int(upload_cc_lang) if upload_cc_lang else 0
        except (ValueError, TypeError):
            _cc_lang_int = 0
        try:
            _md_lang_int = int(upload_md_lang) if upload_md_lang else 0
        except (ValueError, TypeError):
            _md_lang_int = 0
        # String fields take priority over legacy int fields when non-zero
        if _cc_lang_int > 0:
            upload_cc_limit = _cc_lang_int
        if _md_lang_int > 0:
            upload_md_limit = _md_lang_int

        # Normalize upload_cc_languages allowlist
        _cc_langs = [l.strip().lower() for l in (upload_cc_languages or []) if l.strip()]

        # CC/MD-only mode: upload_youtube_video=False but upload_cc=True
        # → skip video upload, go straight to CC/MD update on existing video
        _cc_md_only = not upload_youtube_video and upload_cc
        if not upload_youtube_video and not upload_cc:
            return "🔇 YouTube upload skipped (upload_youtube_video=false, upload_cc=false)."

        if dry_run:
            # Validate files exist without touching YouTube API
            import glob as _dglob
            import re as _dre
            results = []
            for fmt in (video_formats if not isinstance(video_formats, str) else [video_formats]):
                fmt = fmt.strip()
                topic_slug = "_".join(_dre.findall(r"\w+", topic)[:4]) if topic else "Video"
                seg_pfx = ("intro_", "bar_race_", "definition_video_", "_norm_")
                candidates = []
                for pat in [f"*_{fmt}.mp4", f"*_{fmt}_*.mp4"]:
                    candidates += [p for p in _dglob.glob(os.path.join(output_dir, pat))
                                   if not any(os.path.basename(p).startswith(px) for px in seg_pfx)]
                # Metadata
                debate_md = os.path.join(output_dir, "YT", "debate", fmt, "MD", "en.json")
                std_md    = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
                md_path   = debate_md if os.path.exists(debate_md) else std_md
                # CC
                debate_cc = os.path.join(output_dir, "YT", "debate", fmt, "CC")
                std_cc    = os.path.join(output_dir, "YT", fmt, "CC")
                cc_dir    = debate_cc if os.path.exists(debate_cc) else std_cc
                cc_count  = len([f for f in os.listdir(cc_dir) if f.endswith(".txt")]) if os.path.exists(cc_dir) else 0
                if candidates:
                    size_mb = os.path.getsize(candidates[0]) / (1024*1024)
                    md_ok   = "✅" if os.path.exists(md_path) else "⚠️  missing"
                    results.append(
                        f"🧪 {fmt}: ✅ {os.path.basename(candidates[0])} ({size_mb:.1f}MB) | "
                        f"MD:{md_ok} | CC:{cc_count} files"
                    )
                else:
                    results.append(f"🧪 {fmt}: ❌ Video not found (expected: {channel}_{topic_slug}_{fmt}.mp4)")
            return "🧪 DRY RUN — no upload performed\n" + "\n".join(results)

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
        if dry_run:
            print(f"[YTUpload] 🧪 DRY RUN MODE — no files will be uploaded to YouTube")
        if _cc_langs:
            print(f"[YTUpload] 🔍 CC language filter: {_cc_langs}")
        # Always show resolved limits so operator can confirm parameters are active
        _cc_lim_str = str(upload_cc_limit) if upload_cc_limit > 0 else "all"
        _md_lim_str = str(upload_md_limit) if upload_md_limit > 0 else "all"
        print(f"[YTUpload] 🔢 Limits — CC: {_cc_lim_str} lang(s) per run | MD: {_md_lim_str} lang(s) per run")
        print(f"[YTUpload] 📋 upload_cc={upload_cc} | upload_cc_lang={upload_cc_lang!r} → {upload_cc_limit} | upload_md_lang={upload_md_lang!r} → {upload_md_limit}")

        try:
            creds = self._get_credentials(client_secrets_file, token_file)
            youtube = build("youtube", "v3", credentials=creds)
            print(f"[YTUpload] ✅ Authenticated")
        except Exception as e:
            return f"❌ Auth Error: {str(e)}"

        results = []
        errors  = []

        # ── CC/MD-only mode: no video upload, just update existing ─────
        if _cc_md_only:
            print(f"[YTUpload] 📝 CC/MD-only mode — updating existing videos")
            results, errors = [], []
            for fmt in video_formats:
                fmt = fmt.strip()
                print(f"\n[YTUpload] ── Format: {fmt} (CC/MD update) ──────────────")
                # Find video_id from upload log
                # Search all known log locations (path changed across versions)
                # Per-format logs first (have real video_id), root-level last
                _log_candidates = [
                    os.path.join(output_dir, "YT", fmt, "upload_log.json"),
                    os.path.join(output_dir, "YT", "debate", fmt, "upload_log.json"),
                    os.path.join(output_dir, "YT", "upload_log.json"),
                    os.path.join(output_dir, "YT", "debate", "upload_log.json"),
                ]
                # Pick first log that EXISTS and has a non-empty video_id
                log_path = None
                for _lc in _log_candidates:
                    if os.path.exists(_lc):
                        try:
                            _vid_check = json.load(open(_lc)).get("video_id","").strip()
                            if _vid_check:
                                log_path = _lc
                                break
                        except Exception:
                            pass
                if not log_path:  # fallback: first existing even if empty
                    log_path = next((p for p in _log_candidates if os.path.exists(p)), None)
                if not log_path:
                    # Also try upload_summary.json as fallback
                    _summary = os.path.join(output_dir, "YT", "upload_summary.json")
                    if os.path.exists(_summary):
                        try:
                            _s = json.load(open(_summary))
                            for _u in _s.get("uploads", []):
                                if _u.get("format","").upper() == fmt.upper() and _u.get("video_id"):
                                    # Reconstruct a minimal log from summary
                                    log_path = _log_candidates[0]
                                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                                    json.dump({"video_id": _u["video_id"], "format": fmt}, open(log_path,"w"))
                                    print(f"[YTUpload]   ♻️  Reconstructed log from upload_summary.json")
                                    break
                        except Exception: pass
                if not log_path or not os.path.exists(log_path):
                    errors.append(f"❌ {fmt}: upload_log.json not found — upload video first")
                    print(f"[YTUpload] ❌ {fmt}: no upload log found in any location")
                    print(f"[YTUpload]   Searched: {_log_candidates}")
                    continue
                try:
                    with open(log_path) as _lf:
                        _log = json.load(_lf)
                    vid_id = (_log.get("video_id") or _log.get("video_url","").replace("https://youtu.be/","")).strip()
                    if not vid_id:
                        # Try upload_summary.json as last resort
                        _summary = os.path.join(output_dir, "YT", "upload_summary.json")
                        if os.path.exists(_summary):
                            try:
                                _s = json.load(open(_summary))
                                for _u in _s.get("uploads", []):
                                    if _u.get("format","").upper() == fmt.upper() and _u.get("video_id"):
                                        vid_id = _u["video_id"]
                                        print(f"[YTUpload]   ♻️  video_id from summary: {vid_id}")
                                        break
                            except Exception: pass
                    if not vid_id:
                        errors.append(f"❌ {fmt}: no video_id in log — upload video first")
                        continue
                    print(f"[YTUpload] ✅ {fmt}: video_id={vid_id}")
                    notes = []
                    url = f"https://youtu.be/{vid_id}"

                    # ── Smart skip CC: check what's already on YouTube ──
                    try:
                        from googleapiclient.errors import HttpError as _HE2
                        _cap_resp   = youtube.captions().list(part="snippet", videoId=vid_id).execute()
                        _cc_on_yt   = {c["snippet"]["language"] for c in _cap_resp.get("items", [])}
                        _cc_on_yt_norm = set()
                        for _c in _cc_on_yt:
                            _cc_on_yt_norm.add(_c.lower())
                            _cc_on_yt_norm.add(_c.split("-")[0].lower())
                    except Exception:
                        _cc_on_yt_norm = set()

                    # Count pending CC files not yet on YouTube
                    _cc_dir_d = os.path.join(output_dir, "YT", "debate", fmt, "CC")
                    _cc_dir_s = os.path.join(output_dir, "YT", fmt, "CC")
                    _cc_dir   = _cc_dir_d if os.path.exists(_cc_dir_d) else _cc_dir_s
                    _cc_pending_count = 0
                    if os.path.exists(_cc_dir):
                        for _cf in os.listdir(_cc_dir):
                            if _cf.endswith(".txt"):
                                _rc = _cf.replace(".txt","")
                                _yc = self._lang_map.get(_rc, _rc)
                                if _yc.lower() not in _cc_on_yt_norm and _rc.lower() not in _cc_on_yt_norm:
                                    _cc_pending_count += 1

                    # Smart skip CC: only upload if pending langs exist
                    cc_stats = {"uploaded": 0, "skipped": 0, "failed": 0}
                    if _cc_pending_count == 0:
                        print(f"[YTUpload] ⏭️  {fmt}: CC complete — all langs already on YouTube")
                        notes.append(f"CC: all already uploaded")
                    else:
                        print(f"[YTUpload] ♻️  {fmt}: {_cc_pending_count} CC lang(s) pending")
                        cc_stats = self._upload_cc_files(
                            youtube, vid_id, output_dir, fmt,
                            limit=upload_cc_limit, languages=_cc_langs
                        )
                        if cc_stats["uploaded"] > 0 or cc_stats["failed"] > 0:
                            notes.append(f"CC: +{cc_stats['uploaded']} uploaded, {cc_stats['failed']} failed")
                    _log["cc_uploaded"] = _log.get("cc_uploaded", 0) + cc_stats["uploaded"]

                    # ── Smart skip MD: check what's already on YouTube ──
                    try:
                        _vid_resp  = youtube.videos().list(part="localizations", id=vid_id).execute()
                        _md_on_yt  = set((_vid_resp["items"][0].get("localizations", {}) if _vid_resp.get("items") else {}).keys())
                        _md_on_yt_norm = set()
                        for _m in _md_on_yt:
                            _md_on_yt_norm.add(_m.lower())
                            _md_on_yt_norm.add(_m.split("-")[0].lower())
                    except Exception:
                        _md_on_yt_norm = set()

                    # Count pending MD files not yet on YouTube
                    _md_dir_d = os.path.join(output_dir, "YT", "debate", fmt, "MD")
                    _md_dir_s = os.path.join(output_dir, "YT", fmt, "MD")
                    _md_dir   = _md_dir_d if os.path.exists(_md_dir_d) else _md_dir_s
                    _md_pending_count = 0
                    if os.path.exists(_md_dir):
                        for _mf in os.listdir(_md_dir):
                            if _mf.endswith(".txt") and _mf != "en.txt":
                                _rc = _mf.replace(".txt","")
                                _yc = self._lang_map.get(_rc, _rc)
                                if _yc.lower() not in _md_on_yt_norm and _rc.lower() not in _md_on_yt_norm:
                                    _md_pending_count += 1

                    # Smart skip MD: only upload if pending langs exist
                    loc_stats = {"uploaded": 0, "failed": 0}
                    if _md_pending_count == 0:
                        print(f"[YTUpload] ⏭️  {fmt}: MD complete — all langs already on YouTube")
                        notes.append(f"MD: all already uploaded")
                    else:
                        print(f"[YTUpload] ♻️  {fmt}: {_md_pending_count} MD lang(s) pending")
                        loc_stats = self._upload_localizations(
                            youtube, vid_id, output_dir, fmt, limit=upload_md_limit
                        )
                        if loc_stats["uploaded"] > 0:
                            notes.append(f"MD: +{loc_stats['uploaded']} languages")
                    _log["loc_uploaded"] = _log.get("loc_uploaded", 0) + loc_stats["uploaded"]

                    with open(log_path, "w") as _lf:
                        json.dump(_log, _lf, indent=2)
                    note_str = " | ".join(notes) if notes else "nothing new to upload"
                    results.append(f"✅ {fmt}: {url} ({note_str})")
                except Exception as _e:
                    errors.append(f"❌ {fmt}: {_e}")
            summary = self._format_summary(results, errors)
            self._save_upload_summary(results, errors, output_dir, topic)
            return summary

        for fmt in video_formats:
            fmt = fmt.strip()
            print(f"\n[YTUpload] ── Format: {fmt} ──────────────────")

            # ── Smart skip: check upload log ──────────────────────────────
            # Check both standard and debate log paths
            #_log_std    = os.path.join(output_dir, "YT", fmt, "upload_log.json")
            #_log_debate = os.path.join(output_dir, "YT", "debate", fmt, "upload_log.json")
            log_path = os.path.join(output_dir, "YT", "upload_log.json")
            #log_path = _log_debate if os.path.exists(_log_debate) else _log_std
            if os.path.exists(log_path):
                try:
                    with open(log_path) as _lf:
                        _log = json.load(_lf)
                    vid_id = _log.get("video_id", "")
                    if vid_id:
                        url = f"https://youtu.be/{vid_id}"
                        notes = []
                        print(f"[YTUpload] ⏭️  {fmt}: video_id={vid_id} found in log — checking CC/MD status")

                        # ── Check CC: compare disk files vs what's on YouTube ──
                        # Resolve CC dir (debate or standard)
                        _cc_dir_debate = os.path.join(output_dir, "YT", "debate", fmt, "CC")
                        _cc_dir_std    = os.path.join(output_dir, "YT", fmt, "CC")
                        cc_dir_check   = _cc_dir_debate if os.path.exists(_cc_dir_debate) else _cc_dir_std
                        cc_total_on_disk = len([f for f in os.listdir(cc_dir_check) if f.endswith(".txt")]) if os.path.exists(cc_dir_check) else 0

                        # Ask YouTube which captions already exist on this video
                        try:
                            from googleapiclient.errors import HttpError as _HE
                            _cap_resp      = youtube.captions().list(part="snippet", videoId=vid_id).execute()
                            cc_on_yt       = len(_cap_resp.get("items", []))
                            cc_langs_on_yt = {c["snippet"]["language"] for c in _cap_resp.get("items", [])}
                        except Exception:
                            cc_on_yt       = _log.get("cc_uploaded", 0)
                            cc_langs_on_yt = set()

                        # When upload_cc=False: only care about English CC
                        _cc_langs_sk = _cc_langs if upload_cc else ["en"]
                        _cc_limit_sk = upload_cc_limit if upload_cc else 1

                        # Determine how many relevant files are still pending on disk
                        if os.path.exists(cc_dir_check):
                            _all_cc = sorted(f.replace(".txt","") for f in os.listdir(cc_dir_check) if f.endswith(".txt"))
                            if _cc_langs_sk:
                                _all_cc = [l for l in _all_cc if l in _cc_langs_sk]
                            _cc_pending = [l for l in _all_cc if l not in cc_langs_on_yt]
                            # Apply per-run limit to pending only
                            _cc_to_upload = len(_cc_pending[:_cc_limit_sk] if _cc_limit_sk > 0 else _cc_pending)
                        else:
                            _cc_pending   = []
                            _cc_to_upload = 0

                        cc_needs_upload = _cc_to_upload > 0
                        if cc_needs_upload:
                            reason = f"{cc_on_yt} on YT | {_cc_to_upload} pending (limit={_cc_limit_sk if _cc_limit_sk > 0 else 'all'})"
                            print(f"[YTUpload] ♻️  {fmt}: uploading CC ({reason})")
                            cc_stats = self._upload_cc_files(
                                youtube, vid_id, output_dir, fmt,
                                limit=_cc_limit_sk, languages=_cc_langs_sk
                            )
                            _log["cc_uploaded"] = _log.get("cc_uploaded", 0) + cc_stats["uploaded"]
                            _log["cc_failed"]   = cc_stats["failed"]
                            _log["cc_skipped"]  = _log.get("cc_skipped", 0) + cc_stats["skipped"]
                            with open(log_path, "w") as _lf:
                                json.dump(_log, _lf, indent=2)
                            notes.append(f"CC: +{cc_stats['uploaded']} uploaded, {cc_stats['failed']} failed")
                        else:
                            print(f"[YTUpload] ✅ {fmt}: CC complete — {cc_on_yt}/{cc_total_on_disk} on YouTube")

                        # ── Localizations: only upload if there are still pending MD langs ──
                        _md_lim_sk = upload_md_limit if upload_cc else 1
                        _loc = self._upload_localizations(youtube, vid_id, output_dir, fmt, limit=_md_lim_sk)
                        if _loc["uploaded"] > 0:
                            _log["loc_uploaded"] = _log.get("loc_uploaded", 0) + _loc["uploaded"]
                            with open(log_path, "w") as _lf:
                                json.dump(_log, _lf, indent=2)
                            notes.append(f"MD: +{_loc['uploaded']} languages")
                        else:
                            print(f"[YTUpload] ✅ {fmt}: MD localizations complete — nothing new to upload")

                        note_str = " | ".join(notes) if notes else "✅ all complete"
                        results.append(f"⏭️ {fmt}: Already uploaded → {url} ({note_str})")
                        continue
                except Exception as _skip_err:
                    print(f"[YTUpload] ⚠️  {fmt}: log read error ({_skip_err}) — proceeding with upload")
                    pass  # Corrupt log — proceed with upload

            # ── Find video file ────────────────────────────────────────────
            import glob as _glob
            topic_slug = "_".join(_re.findall(r"\w+", topic)[:4]) if topic else "Video"
            video_name = f"{channel}_{topic_slug}_{fmt}.mp4"
            video_path = os.path.join(output_dir, video_name)

            if not os.path.exists(video_path):
                # Exclude segment/temp files
                seg_pfx = ("intro_", "bar_race_", "definition_video_", "_norm_")
                # Try: exact fmt match (e.g. *_HD.mp4, *_Shorts.mp4)
                # Also try: fmt with language suffix (e.g. *_HD_En.mp4) for debate videos
                candidates = []
                for pattern in [f"*_{fmt}.mp4", f"*_{fmt}_*.mp4"]:
                    candidates += [p for p in _glob.glob(os.path.join(output_dir, pattern))
                                   if not any(os.path.basename(p).startswith(px) for px in seg_pfx)]
                # Prefer exact match over language-suffixed; dedupe preserving order
                seen = set()
                matches = []
                for p in candidates:
                    if p not in seen:
                        seen.add(p)
                        matches.append(p)
                if matches:
                    video_path = matches[0]
                    print(f"[YTUpload] ⚠️  Fallback: {os.path.basename(video_path)}")
                else:
                    errors.append(f"❌ {fmt}: Video not found (expected: {video_name})")
                    print(f"[YTUpload] ❌ {fmt}: No video file — skipping")
                    continue

            # ── Load metadata — check debate subfolder first ───────────────
            # Debate videos store metadata under YT/debate/{fmt}/MD/en.json
            debate_md = os.path.join(output_dir, "YT", "debate", fmt, "MD", "en.json")
            standard_md = os.path.join(output_dir, "YT", fmt, "MD", "en.json")
            metadata_path = debate_md if os.path.exists(debate_md) else standard_md
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
                    cc_stats = self._upload_cc_files(
                        youtube, video_id, output_dir, fmt,
                        limit=upload_cc_limit, languages=_cc_langs
                    )
                else:
                    # upload_cc=False: still upload English CC only so the
                    # video has at least one subtitle track (required for
                    # YouTube features like auto-translate and chapters).
                    print(f"[YTUpload]   📝 upload_cc=False — uploading English CC only")
                    cc_stats = self._upload_cc_files(
                        youtube, video_id, output_dir, fmt,
                        limit=1, languages=["en"]
                    )
                # Update log with CC results
                log_entry.update({
                    "cc_uploaded": cc_stats["uploaded"],
                    "cc_skipped":  cc_stats["skipped"],
                    "cc_failed":   cc_stats["failed"],
                })
                with open(log_path, "w") as _lf:
                    json.dump(log_entry, _lf, indent=2)

                # ── Upload localizations (title & description per language) ──
                # upload_cc=False means "skip multi-lang" — still upload
                # English MD so title/description are set correctly.
                _md_limit = upload_md_limit if upload_cc else 1
                loc_stats = self._upload_localizations(youtube, video_id, output_dir, fmt, limit=_md_limit)
                log_entry["loc_uploaded"] = loc_stats["uploaded"]
                with open(log_path, "w") as _lf:
                    json.dump(log_entry, _lf, indent=2)

                # ── Upload thumbnail ──────────────────────────────────
                thumb_note = ""
                _thumb_path = thumbnail_path
                if not _thumb_path:
                    # Auto-detect thumbnail — check multiple locations
                    import glob as _tglob
                    _excl = ("PlayOwnAi", "flux-", "seedream-", "epsilon_")
                    def _find_thumbs(directory):
                        return [p for p in
                                _tglob.glob(os.path.join(directory, "*.jpg")) +
                                _tglob.glob(os.path.join(directory, "*.png"))
                                if not any(os.path.basename(p).startswith(x) for x in _excl)]
                    # Search: root, YT/debate/{fmt}/Th/, YT/{fmt}/Th/
                    _thumb_dirs = [
                        output_dir,
                        os.path.join(output_dir, "YT", "debate", fmt, "Th"),
                        os.path.join(output_dir, "YT", fmt, "Th"),
                    ]
                    _candidates = []
                    for _td in _thumb_dirs:
                        _candidates += _find_thumbs(_td)
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

        # Strip emoji from free-text fields (title, description)
        def _clean_text(t):
            import re as _re
            t = str(t)
            t = _re.sub(u'[\U00002000-\U0010FFFF]', '', t)
            t = _re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u00C0-\u024F\u0400-\u04FF]', '', t)
            return t.strip()

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

    # ── lang.json loader — single source of truth ────────────────────────────
    @staticmethod
    def _load_lang_config():
        """Load lang.json from data/lang.json (or fall back to defaults).
        Returns (lang_map, rank_order_codes, cc_eligible_codes).
          lang_map:          {file_code → yt_code}  e.g. "zh-hans" → "zh-Hans"
          rank_order_codes:  [file_code, ...]  sorted by rank ascending (1 = best)
          cc_eligible_codes: [file_code, ...]  only codes where cc=true, rank order
        """
        import os as _os
        # Search relative to CWD (crewai project root) and common locations
        for candidate in ["data/lang.json", "lang.json", "../data/lang.json"]:
            if _os.path.exists(candidate):
                try:
                    import json as _json
                    with open(candidate, encoding="utf-8") as _f:
                        data = _json.load(_f)
                    langs = sorted(data["languages"], key=lambda x: x["rank"])
                    lang_map   = {l["code"]: l["yt_code"] for l in langs}
                    # Also add aliases (e.g. "zh-cn" → "zh-hans" → yt_code)
                    for alias, target in data.get("aliases", {}).items():
                        if target in lang_map:
                            lang_map[alias] = lang_map[target]
                    rank_order = [l["code"] for l in langs]
                    cc_only    = [l["code"] for l in langs if l.get("cc", False)]
                    return lang_map, rank_order, cc_only
                except Exception as _e:
                    print(f"[YTUpload] ⚠️  lang.json load error: {_e} — using defaults")
                    break

        # ── Hardcoded fallback (mirrors lang.json) ────────────────────────────
        _fallback_map = {
            "zh-hans": "zh-Hans", "zh-hant": "zh-Hant",
            "zh-cn":   "zh-Hans", "zh-tw":   "zh-Hant",
            "iw":      "iw",      "pt-pt":   "pt-PT",
            "sr":      "sr-Latn",
        }
        _fallback_rank = [
            "en","es","ar","pt","id","tr","vi","fr","ru","zh-hans",
            "hi","ko","bn","it","th","fa","ja","de","pl","cs",
            "uk","zh-hant","ta","bs","pt-pt","ro","bg","el","hu",
            "iw","my","sr","te","ur","ms","et"
        ]
        _fallback_cc = [
            "en","es","ar","pt","id","tr","vi","fr","ru","zh-hans",
            "hi","ko","bn","it","th","fa","ja","de","pl","cs"
        ]
        return _fallback_map, _fallback_rank, _fallback_cc

    # Instance-level cache so lang.json is loaded only once per tool invocation
    _lang_map:    dict = {}
    _rank_order:  list = []
    _cc_eligible: list = []

    def _upload_localizations(self, youtube, video_id, output_dir, fmt, limit: int = 0):
        """Upload translated title & description for all languages via YouTube localizations API."""
        import re as _re2

        def _clean(t, maxlen):
            """Strip only emoji/symbol ranges; preserve ALL real text (CJK, Arabic, Cyrillic…)."""
            t = str(t)
            t = _re2.sub(u"[🌀-🫿]", "", t)  # emoji (faces, objects, flags)
            t = _re2.sub(u"[☀-➿]", "", t)           # misc symbols & dingbats
            t = _re2.sub(u"[︀-﻿]", "", t)           # variation selectors / BOM
            t = _re2.sub(r"[<>&]", "", t)                     # YouTube-rejected XML chars
            return t.strip()[:maxlen]

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

        # Check debate subfolder first (debate videos use YT/debate/{fmt}/MD/)
        debate_md = os.path.join(output_dir, "YT", "debate", fmt, "MD")
        md_dir = debate_md if os.path.exists(debate_md) else os.path.join(output_dir, "YT", fmt, "MD")
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
        _md_disk = {f.replace(".txt","") for f in os.listdir(md_dir)
                    if f.endswith(".txt") and f not in ("en.txt",)}
        # Sort MD files by lang.json rank (highest-view langs first)
        all_lang_files = (
            [f"{c}.txt" for c in self._rank_order if c in _md_disk and c != "en"] +
            sorted(f"{c}.txt" for c in _md_disk if c not in self._rank_order and c != "en")
        )

        # Separate already-uploaded from pending (so limit counts only NEW uploads)
        # Normalize existing_locs keys (YouTube may return "es" or "es-419")
        _existing_locs_norm = set()
        for _ek in existing_locs:
            _existing_locs_norm.add(_ek.lower())
            _existing_locs_norm.add(_ek.split("-")[0].lower())

        def _is_in_existing(raw_code):
            yt = self._lang_map.get(raw_code, raw_code)
            return yt.lower() in _existing_locs_norm or raw_code.lower() in _existing_locs_norm

        already_locs = {self._lang_map.get(f.replace(".txt",""), f.replace(".txt",""))
                        for f in all_lang_files if _is_in_existing(f.replace(".txt",""))}
        pending_files = [f for f in all_lang_files if not _is_in_existing(f.replace(".txt",""))]

        # Apply upload limit: caps how many NEW langs to upload this session (0 = all)
        if limit > 0:
            pending_files = pending_files[:limit]

        print(f"[YTUpload]   🌍 MD: {len(all_lang_files)} total | {len(already_locs)} already on YT (keep) | {len(pending_files)} to add (limit={limit if limit > 0 else 'all'})")

        added = 0
        skipped_empty = 0
        for fname in pending_files:
            raw_code = fname.replace(".txt", "")
            yt_code  = self._lang_map.get(raw_code, raw_code)  # map to YT BCP-47
            title, desc = _parse_md_txt(os.path.join(md_dir, fname))
            clean_title = _clean(title, 100)
            clean_desc  = _clean(desc,  5000)
            if not clean_title:
                print(f"[YTUpload]   ⚠️  MD {raw_code}: title empty after cleaning — skip")
                skipped_empty += 1
                continue
            localizations[yt_code] = {
                "title":       clean_title,
                "description": clean_desc,
            }
            added += 1

        if not added:
            reason = f"all {len(already_locs)} already on YT" if already_locs else f"{skipped_empty} had empty titles"
            print(f"[YTUpload]   ⚠️  No new MD to upload ({reason})")
            return {"uploaded": 0, "failed": 0}

        _new_codes = [self._lang_map.get(f.replace(".txt",""), f.replace(".txt","")) for f in pending_files]
        print(f"[YTUpload]   🌍 Uploading {added} new localizations (+ keeping {len(already_locs)} existing): {_new_codes[:added]}")
        try:
            youtube.videos().update(
                part="localizations",
                body={"id": video_id, "localizations": localizations},
            ).execute()
            print(f"[YTUpload]   ✅ Localizations uploaded: {added} language(s)")
            return {"uploaded": added, "failed": 0}
        except Exception as e:
            _payload_keys = list(localizations.keys())
            print(f"[YTUpload]   ❌ Localizations failed ({len(_payload_keys)} langs in payload): {e}")
            # Show first bad entry to help diagnose
            for _k, _v in list(localizations.items())[:3]:
                print(f"[YTUpload]      sample [{_k}] title={repr(_v.get('title',''))[:60]}")
            return {"uploaded": 0, "failed": added}

    def _upload_cc_files(self, youtube, video_id, output_dir, fmt,
                         limit: int = 0, languages: list = None):
        """Upload CC files from YT/{fmt}/CC/. Stops immediately on quota exceeded.
        languages: optional allowlist of lang codes e.g. ['en', 'fr']. Empty = all.
        """
        from googleapiclient.http import MediaInMemoryUpload
        from googleapiclient.errors import HttpError

        # Check debate subfolder first (debate videos use YT/debate/{fmt}/CC/)
        debate_cc = os.path.join(output_dir, "YT", "debate", fmt, "CC")
        cc_dir = debate_cc if os.path.exists(debate_cc) else os.path.join(output_dir, "YT", fmt, "CC")
        stats  = {"uploaded": 0, "skipped": 0, "failed": 0, "quota_hit": False}
        _lang_filter = [l.strip().lower() for l in (languages or []) if l.strip()]

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

        _disk_codes = {f.replace(".txt","") for f in os.listdir(cc_dir) if f.endswith(".txt")}
        # Sort CC files by lang.json rank (highest-view langs first), then alphabetical fallback
        cc_files = (
            [f"{c}.txt" for c in self._rank_order if c in _disk_codes] +
            sorted(f"{c}.txt" for c in _disk_codes if c not in self._rank_order)
        )

        # Apply language allowlist filter if provided
        if _lang_filter:
            cc_files = [f for f in cc_files if f.replace(".txt", "").lower() in _lang_filter]
            print(f"[YTUpload]   🔍 CC language filter active: {_lang_filter} → {len(cc_files)} file(s)")

        # Map filenames to YouTube BCP-47 codes for accurate dedup check
        _mapped = {f.replace(".txt",""): self._lang_map.get(f.replace(".txt",""), f.replace(".txt",""))
                   for f in cc_files}
        _remapped = {k: v for k, v in _mapped.items() if k != v}
        if _remapped:
            print(f"[YTUpload]   🗺️  CC lang code remaps: {_remapped}")

        # Normalize existing_langs: also include the root code (e.g. "es" matches "es-419")
        _existing_normalized = set()
        for _el in existing_langs:
            _existing_normalized.add(_el.lower())
            _existing_normalized.add(_el.split("-")[0].lower())  # root code fallback
        already_done = [f for f in cc_files
                        if _mapped[f.replace(".txt","")].lower() in _existing_normalized
                        or f.replace(".txt","").lower() in _existing_normalized]
        pending      = [f for f in cc_files if f not in already_done]
        already      = len(already_done)

        # Apply upload limit: caps how many NEW langs to upload this session (0 = all)
        if limit > 0:
            pending = pending[:limit]

        print(f"[YTUpload]   📝 CC: {len(cc_files)} total | {already} already on YT (skip) | {len(pending)} to upload (limit={limit if limit > 0 else 'all'})")
        if already:
            stats["skipped"] += already

        for filename in pending:
            raw_code  = filename.replace(".txt", "")
            lang_code = self._lang_map.get(raw_code, raw_code)  # map to YouTube BCP-47
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
                        "name":     "",        # empty = YouTube uses its own display name, prevents duplicate tracks
                        "isDraft":  False,
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
