"""
Facebook Video Upload Tool
Uploads videos to a Facebook Page using the Graph API.
Mirrors yt_upload_tool.py structure and directory conventions.

Features:
- Uploads Shorts → Facebook Reels  (portrait 9:16)
- Uploads HD     → Facebook Video  (landscape 16:9)
- Reads metadata from YT/debate/{fmt}/MD/en.json (or YT/{fmt}/MD/en.json)
- Smart skip: already-uploaded formats skipped via fb_upload_log.json
- Dry-run mode: validates files/metadata without uploading
- Saves fb_upload_log.json + fb_upload_summary.json

Requirements:
    pip install requests

Facebook Setup:
    1. Create a Facebook App at developers.facebook.com
    2. Add "Pages" product and request publish_video permission
    3. Generate a Page Access Token (long-lived, not user token)
    4. Set page_id  = your Facebook Page numeric ID
    5. Set page_access_token = your long-lived Page Access Token

    Store in fb_credentials.json:
    {
        "page_id": "123456789",
        "page_access_token": "EAAxxxxxxx..."
    }
"""

import os
import json
import time
import re
from typing import Type
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

GRAPH_API_VERSION  = "v19.0"
GRAPH_VIDEO_URL    = f"https://graph-video.facebook.com/{GRAPH_API_VERSION}"
GRAPH_API_URL      = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
CHUNK_SIZE         = 10 * 1024 * 1024   # 10 MB chunks
MAX_RETRIES        = 3
RETRY_BACKOFF      = [5, 15, 30]


# ── Input Schema ──────────────────────────────────────────────────────────────

class FBUploadToolInput(BaseModel):
    """Input schema for FBUploadTool."""
    topic:               str  = Field(...,   description="Topic name")
    output_dir:          str  = Field(...,   description="Full path to output/Topic directory")
    video_formats:       list = Field(...,   description="Formats to upload: ['Shorts', 'HD']")
    upload_facebook_video: bool = Field(default=False, description="Master switch — must be true to upload")
    channel:             str  = Field(default="PlayOwnAi", description="Channel prefix for filename lookup")
    privacy_status:      str  = Field(default="SELF",      description="EVERYONE | FRIENDS | SELF (default=SELF=private)")
    credentials_file:    str  = Field(default="fb_credentials.json", description="Path to Facebook credentials JSON")
    dry_run:             bool = Field(default=False, description="Validate files/metadata without uploading")


# ── Tool ──────────────────────────────────────────────────────────────────────

class FBUploadTool(BaseTool):
    name:        str = "fb_upload_tool"
    description: str = (
        "Uploads debate videos to a Facebook Page. "
        "Shorts → Facebook Reels. HD → Facebook Video. "
        "Reads metadata from YT/debate/{fmt}/MD/en.json."
    )
    args_schema: Type[BaseModel] = FBUploadToolInput

    def _run(
        self,
        topic: str,
        output_dir: str,
        video_formats: list,
        upload_facebook_video: bool = False,
        channel: str = "PlayOwnAi",
        privacy_status: str = "SELF",
        credentials_file: str = "fb_credentials.json",
        dry_run: bool = False,
    ) -> str:

        if not upload_facebook_video:
            return "🔇 Facebook upload skipped (upload_facebook_video=false)."

        try:
            import requests
        except ImportError:
            return "❌ requests not installed. Run: pip install requests"

        # ── Load credentials ──────────────────────────────────────────────────
        creds = self._load_credentials(credentials_file)
        if not creds:
            return f"❌ Credentials not found: {credentials_file}\nCreate it with: {{\"page_id\": \"...\", \"page_access_token\": \"...\"}}"

        page_id    = creds.get("page_id", "").strip()
        page_token = creds.get("page_access_token", "").strip()
        if not page_id or not page_token:
            return "❌ fb_credentials.json must contain 'page_id' and 'page_access_token'."

        print(f"[FBUpload] 🚀 Starting — formats: {video_formats} | privacy: {privacy_status}")
        if dry_run:
            print(f"[FBUpload] 🧪 DRY RUN — no actual uploads")

        results = []
        errors  = []

        for fmt in video_formats:
            print(f"\n[FBUpload] ── Format: {fmt} ──────────────────")
            is_reel = fmt in ("Shorts", "ShortsHD", "Shorts4K")

            # ── Smart skip ────────────────────────────────────────────────────
            log_path = self._log_path(output_dir, fmt)
            if os.path.exists(log_path):
                try:
                    _log = json.load(open(log_path))
                    vid_id = _log.get("video_id", "").strip()
                    if vid_id:
                        url = f"https://www.facebook.com/video/{vid_id}"
                        print(f"[FBUpload] ⏭️  {fmt}: already uploaded → {url}")
                        results.append(f"⏭️ {fmt}: Already uploaded → {url}")
                        continue
                except Exception:
                    pass

            # ── Find video file ───────────────────────────────────────────────
            video_path = self._find_video(output_dir, channel, topic, fmt)
            if not video_path:
                errors.append(f"❌ {fmt}: video file not found")
                print(f"[FBUpload] ❌ {fmt}: video file not found")
                continue

            # ── Load metadata ─────────────────────────────────────────────────
            metadata = self._load_metadata(output_dir, fmt, topic)
            title    = self._clean_text(metadata.get("title", topic))[:255]
            desc     = self._build_description(metadata)

            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            upload_type = "Reel" if is_reel else "Video"
            print(f"[FBUpload]   📤 {os.path.basename(video_path)} ({size_mb:.1f} MB) → Facebook {upload_type}")
            print(f"[FBUpload]   📝 Title: {title[:80]}")

            if dry_run:
                results.append(f"🧪 {fmt}: Dry run OK — {os.path.basename(video_path)} ({size_mb:.1f} MB)")
                continue

            # ── Upload ────────────────────────────────────────────────────────
            try:
                if is_reel:
                    video_id = self._upload_reel(
                        page_id, page_token, video_path, title, desc, privacy_status
                    )
                else:
                    video_id = self._upload_video(
                        page_id, page_token, video_path, title, desc, privacy_status
                    )

                url = f"https://www.facebook.com/video/{video_id}"
                print(f"[FBUpload] ✅ {fmt}: uploaded → {url}")

                # ── Save log immediately ──────────────────────────────────────
                self._save_log(log_path, video_id, video_path, fmt, privacy_status)

                results.append(f"✅ {fmt}: Uploaded → {url}")

            except Exception as e:
                errors.append(f"❌ {fmt}: {e}")
                print(f"[FBUpload] ❌ {fmt}: {e}")

        # ── Summary ───────────────────────────────────────────────────────────
        self._save_summary(output_dir, topic, results, errors)

        lines = [f"✅ Facebook Upload ({len(video_formats)} format(s)):"]
        for r in results:
            lines.append(f"   • {r}")
        for e in errors:
            lines.append(f"   • {e}")
        return "\n".join(lines)

    # ── Upload: standard video ────────────────────────────────────────────────

    def _upload_video(self, page_id, token, file_path, title, description, privacy):
        """Upload as a regular Facebook Page video (resumable)."""
        import requests

        file_size = os.path.getsize(file_path)

        # Step 1: Start upload session
        start_r = requests.post(
            f"{GRAPH_VIDEO_URL}/{page_id}/videos",
            data={
                "upload_phase":  "start",
                "file_size":     file_size,
                "access_token":  token,
            },
            timeout=30,
        )
        start_r.raise_for_status()
        start_data   = start_r.json()
        upload_session_id = start_data.get("upload_session_id")
        video_id          = start_data.get("video_id")
        if not upload_session_id:
            raise RuntimeError(f"No upload_session_id: {start_data}")
        print(f"[FBUpload]   🆔 session={upload_session_id}  video_id={video_id}")

        # Step 2: Transfer chunks
        self._transfer_chunks(page_id, token, upload_session_id, file_path, file_size)

        # Step 3: Finish
        finish_r = requests.post(
            f"{GRAPH_VIDEO_URL}/{page_id}/videos",
            data={
                "upload_phase":    "finish",
                "upload_session_id": upload_session_id,
                "title":           title,
                "description":     description,
                "privacy":         json.dumps({"value": privacy}),
                "access_token":    token,
            },
            timeout=60,
        )
        finish_r.raise_for_status()
        finish_data = finish_r.json()
        if not finish_data.get("success"):
            raise RuntimeError(f"Finish failed: {finish_data}")

        return video_id

    # ── Upload: Reels ─────────────────────────────────────────────────────────

    def _upload_reel(self, page_id, token, file_path, title, description, privacy):
        """Upload as a Facebook Reel."""
        import requests

        file_size = os.path.getsize(file_path)

        # Step 1: Initialize Reel upload
        init_r = requests.post(
            f"{GRAPH_API_URL}/{page_id}/video_reels",
            data={
                "upload_phase":  "start",
                "access_token":  token,
            },
            timeout=30,
        )
        init_r.raise_for_status()
        init_data = init_r.json()
        video_id  = init_data.get("video_id")
        if not video_id:
            raise RuntimeError(f"No video_id from Reel init: {init_data}")
        print(f"[FBUpload]   🎬 Reel video_id={video_id}")

        # Step 2: Upload binary
        upload_url = init_data.get("upload_url", f"{GRAPH_VIDEO_URL}/{video_id}")
        with open(file_path, "rb") as f:
            upload_r = requests.post(
                upload_url,
                headers={
                    "Authorization":       f"OAuth {token}",
                    "offset":              "0",
                    "file_size":           str(file_size),
                },
                data=f,
                timeout=600,
            )
        upload_r.raise_for_status()

        # Step 3: Publish Reel
        pub_r = requests.post(
            f"{GRAPH_API_URL}/{page_id}/video_reels",
            data={
                "upload_phase":  "finish",
                "video_id":      video_id,
                "title":         title,
                "description":   description,
                "privacy":       json.dumps({"value": privacy}),
                "video_state":   "PUBLISHED",
                "access_token":  token,
            },
            timeout=60,
        )
        pub_r.raise_for_status()
        pub_data = pub_r.json()
        if not pub_data.get("success"):
            raise RuntimeError(f"Reel publish failed: {pub_data}")

        return video_id

    # ── Chunked transfer ──────────────────────────────────────────────────────

    def _transfer_chunks(self, page_id, token, session_id, file_path, file_size):
        import requests

        offset  = 0
        t0      = time.time()

        with open(file_path, "rb") as f:
            while offset < file_size:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                for attempt in range(MAX_RETRIES):
                    try:
                        r = requests.post(
                            f"{GRAPH_VIDEO_URL}/{page_id}/videos",
                            data={
                                "upload_phase":      "transfer",
                                "upload_session_id": session_id,
                                "start_offset":      offset,
                                "access_token":      token,
                            },
                            files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
                            timeout=120,
                        )
                        r.raise_for_status()
                        resp = r.json()
                        next_offset = int(resp.get("start_offset", offset + len(chunk)))
                        pct = int((next_offset / file_size) * 100)
                        elapsed = int(time.time() - t0)
                        print(f"[FBUpload]   ⬆️  {pct}% ({elapsed}s)")
                        offset = next_offset
                        break
                    except Exception as e:
                        if attempt < MAX_RETRIES - 1:
                            wait = RETRY_BACKOFF[attempt]
                            print(f"[FBUpload]   ⚠️  Chunk error ({e}) — retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                            time.sleep(wait)
                        else:
                            raise RuntimeError(f"Chunk upload failed after {MAX_RETRIES} attempts: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_credentials(self, credentials_file: str) -> dict:
        for path in [credentials_file, os.path.join(os.getcwd(), credentials_file)]:
            if os.path.exists(path):
                try:
                    return json.load(open(path))
                except Exception:
                    pass
        return {}

    def _find_video(self, output_dir, channel, topic, fmt) -> str:
        import glob as _glob
        topic_slug = "_".join(re.findall(r"\w+", topic)[:4]) if topic else "Video"
        # Exact name first
        exact = os.path.join(output_dir, f"{channel}_{topic_slug}_{fmt}.mp4")
        if os.path.exists(exact):
            return exact
        # Glob fallback (debate videos have language suffix e.g. _HD_En.mp4)
        seg_pfx = ("intro_", "bar_race_", "definition_video_", "_norm_")
        candidates = []
        for pat in [f"*_{fmt}.mp4", f"*_{fmt}_*.mp4"]:
            candidates += [
                p for p in _glob.glob(os.path.join(output_dir, pat))
                if not any(os.path.basename(p).startswith(px) for px in seg_pfx)
            ]
        return candidates[0] if candidates else None

    def _load_metadata(self, output_dir, fmt, topic) -> dict:
        for md_path in [
            os.path.join(output_dir, "YT", "debate", fmt, "MD", "en.json"),
            os.path.join(output_dir, "YT", fmt, "MD", "en.json"),
        ]:
            if os.path.exists(md_path):
                try:
                    return json.load(open(md_path))
                except Exception:
                    pass
        return {"title": topic, "description": topic, "tags": [], "chapters": ""}

    def _build_description(self, metadata) -> str:
        desc     = metadata.get("description", "")
        chapters = metadata.get("chapters", "")
        tags     = metadata.get("tags", [])
        parts    = [desc]
        if chapters:
            parts.append(f"\n\nCHAPTERS:\n{chapters}")
        if tags:
            hashtags = " ".join(f"#{t.replace(' ','')}" for t in tags[:10] if t)
            parts.append(f"\n\n{hashtags}")
        return self._clean_text("\n".join(parts))[:5000]

    def _clean_text(self, text: str) -> str:
        text = str(text)
        text = re.sub(u'[\U00002000-\U0010FFFF]', '', text)
        text = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF]', '', text)
        return text.strip()

    def _log_path(self, output_dir, fmt) -> str:
        return os.path.join(output_dir, "YT", "debate", fmt, "fb_upload_log.json")

    def _save_log(self, log_path, video_id, video_path, fmt, privacy):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log = {
            "video_id":    video_id,
            "video_url":   f"https://www.facebook.com/video/{video_id}",
            "video_file":  os.path.basename(video_path),
            "format":      fmt,
            "privacy":     privacy,
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform":    "facebook",
        }
        with open(log_path, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[FBUpload] 💾 Log → {log_path}")

    def _save_summary(self, output_dir, topic, results, errors):
        yt_dir = os.path.join(output_dir, "YT")
        os.makedirs(yt_dir, exist_ok=True)

        summary = {
            "topic":       topic,
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total":       len(results) + len(errors),
            "success":     len(results),
            "failed":      len(errors),
            "uploads":     [],
        }
        for r in results:
            fmt_match = re.search(r"(Shorts|HD|2K|4K|8K)", r)
            fmt = fmt_match.group(1) if fmt_match else "unknown"
            url_match = re.search(r"https://\S+", r)
            summary["uploads"].append({
                "format":    fmt,
                "video_url": url_match.group(0) if url_match else "",
                "status":    "success" if r.startswith("✅") else "skipped",
            })

        json_path = os.path.join(yt_dir, "fb_upload_summary.json")
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        txt_path = os.path.join(yt_dir, "fb_upload_summary.txt")
        sep = "━" * 50
        lines = [sep, "📘 FACEBOOK UPLOAD SUMMARY",
                 f"Topic     : {topic}",
                 f"Uploaded  : {summary['uploaded_at']}",
                 f"Success   : {summary['success']} / {summary['total']}",
                 sep]
        for u in summary["uploads"]:
            lines.append(f"{'✅' if u['status']=='success' else '⏭️'} {u['format']}")
            if u["video_url"]:
                lines.append(f"   URL: {u['video_url']}")
        lines.append(sep)
        with open(txt_path, "w") as f:
            f.write("\n".join(lines))

        print(f"[FBUpload] 💾 Summary → {json_path}")
