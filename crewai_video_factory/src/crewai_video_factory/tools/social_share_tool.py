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
        "access_token": "YOUR_PAGE_ACCESS_TOKEN"
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

        if social_platforms is None:
            social_platforms = ["Facebook", "LinkedIn", "X", "YouTube"]

        if video_formats is None:
            video_formats = ["HD"]

        # ── SMART SKIP — per-platform, per-format ────────────────────────────────
        _smart_fmt = (video_formats[0] if video_formats else "HD")
        share_log_path = os.path.join(output_dir, "YT", _smart_fmt, "share_log.json")
        already_shared = set()

        if os.path.exists(share_log_path):
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

        # Auto-detect image path if not provided
        if not image_path:
            png_path = os.path.join(output_dir, f"{filename}.png")
            jpg_path = os.path.join(output_dir, f"{filename}.jpg")
            if os.path.exists(png_path):
                image_path = png_path
            elif os.path.exists(jpg_path):
                image_path = jpg_path
            else:
                image_path = ""

        # Check if image exists and is valid
        image_file = None
        if image_path and os.path.exists(image_path):
            if image_path.endswith('.png') or image_path.endswith('.jpg') or image_path.endswith('.jpeg'):
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
            log_path = os.path.join(output_dir, "YT", fmt_check, "upload_log.json")
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
                return "❌ No video URL found. Run upload_youtube_video=true first."

        video_url = found_url
        topic_text = topic

        print(f"[SocialShare] 📎 Sharing URL: {video_url}  ({fmt})")
        print(f"[SocialShare] 📢 Platforms: {social_platforms}")
        print(f"[SocialShare] 📺 Channel: @{channel}")
        print(f"[SocialShare] 📅 Year Range: {start_year}–{end_year}")
        print(f"[SocialShare] 🌐 Website: {website}")

        # ── Load credentials ─────────────────────────────────────────────
        creds = self._load_credentials()

        # ── Build post text WITH DYNAMIC VALUES ─────────────────────────────
        post_text = self._build_post_text(topic_text, video_url, channel, website,
                                          short=False, start_year=start_year, end_year=end_year)
        short_text = self._build_post_text(topic_text, video_url, channel, website,
                                           short=True, start_year=start_year, end_year=end_year)

        results = []
        errors = []

        for platform in social_platforms:
            p = platform.strip()
            print(f"\n[SocialShare] ── {p} ──────────────────────────")
            try:
                if p == "Facebook":
                    r = self._post_facebook(creds.get("Facebook", {}), post_text, video_url, image_file)
                elif p == "LinkedIn":
                    r = self._post_linkedin(creds.get("LinkedIn", {}), post_text, video_url, image_file)
                elif p in ("X", "Twitter"):
                    r = self._post_x(creds.get("X", {}), short_text, image_file)
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
                            results, errors, channel, start_year, end_year)

        out = f"📢 Social Share — {len(results)} posted, {len(errors)} failed\n"
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

    def _build_post_text(self, topic, url, channel, website, short=False,
                         start_year=2015, end_year=2026):
        """Build social post text with DYNAMIC channel, year range, and website."""
        hashtags = "#AI #DataVisualization #BarRace #MachineLearning #TechTrends"
        year_range = f"{start_year}–{end_year}"

        if short:
            text = f"📊 {topic} — Bar Race {year_range}\n{url}\n\n#AI #DataViz #BarRace"
            return text[:280]

        lines = [
            f"📊 {topic} — Bar Race {year_range}",
            " ",
            f"Which approach dominated? Watch the data race unfold year by year! 🚀",
            " ",
            f"🎬 Watch now: {url}",
            " ",
            f"📺 Subscribe to @{channel} for more data-driven insights.",
        ]
        if website:
            lines.append(f"🌐 {website}")
        lines += [" ", hashtags]
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

    # def _post_youtube_community(self, creds: dict, text: str, url: str) -> str:
    #     """Post YouTube Community post via YouTube Data API v3."""
    def _post_youtube_community(self, creds: dict, text: str, url: str) -> str:
        """
        Handles YouTube 'sharing'.
        NOTE: YouTube Data API v3 does NOT support Community Posts.
        """
        # Option 1: Inform the user of the limitation
        print("[SocialShare] ℹ️  YouTube Community Posts are not supported via API.")
        return "Skipped — Feature not supported by YouTube Data API v3."

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            import google.auth.transport.requests as google_requests
        except ImportError:
            raise RuntimeError("Install: pip install google-auth-oauthlib google-api-python-client")

        SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
        token_file = creds.get("token_file", "token.json")
        client_secrets_file = creds.get("client_secrets_file", "client_secrets.json")

        cred_obj = None
        if os.path.exists(token_file):
            cred_obj = Credentials.from_authorized_user_file(token_file, SCOPES)

        if not cred_obj or not cred_obj.valid:
            if cred_obj and cred_obj.expired and cred_obj.refresh_token:
                cred_obj.refresh(google_requests.Request())
            else:
                if not os.path.exists(client_secrets_file):
                    raise RuntimeError(f"client_secrets.json not found: {client_secrets_file}")
                flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
                cred_obj = flow.run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(cred_obj.to_json())

        youtube = build("youtube", "v3", credentials=cred_obj)
        body = {"snippet": {"type": "textPost", "textOriginalPost": f"{text}\n\n🎬 {url}"}}
        resp = youtube.communityPosts().insert(part="snippet", body=body).execute()
        post_id = resp.get("id", "unknown")
        return f"Community post — post_id: {post_id}"

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

        # Instagram cannot fetch YouTube URLs — post thumbnail as image instead
        if image_path and os.path.exists(image_path):
            # Upload image via imgbb or use a publicly accessible image URL
            # Strategy: encode image to base64 and use imgbb free API for temp hosting
            import base64, os as _os
            imgbb_key = creds.get("imgbb_api_key", "")
            img_url = ""
            if imgbb_key:
                with open(image_path, "rb") as _f:
                    b64 = base64.b64encode(_f.read()).decode()
                _ir = requests.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": imgbb_key, "image": b64, "expiration": 604800},  # 7 days
                    timeout=30
                ).json()
                img_url = _ir.get("data", {}).get("url", "")

            if not img_url:
                # Fallback: check if creds has a static image_url to use
                img_url = creds.get("image_url", "")

            if not img_url:
                raise RuntimeError(
                    "Instagram requires a public image URL. "
                    "Add 'imgbb_api_key' (free at imgbb.com) or 'image_url' to Instagram creds."
                )

            # Create image container
            container_resp = requests.post(
                f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
                data={"image_url": img_url, "caption": caption, "access_token": access_token},
                timeout=60
            ).json()
        else:
            raise RuntimeError(
                "Instagram requires an image. No thumbnail found — ensure thumbnail is generated first."
            )

        if "error" in container_resp:
            raise RuntimeError(f"Instagram container error: {container_resp['error'].get('message', container_resp)}")

        container_id = container_resp.get("id")
        if not container_id:
            raise RuntimeError(f"Instagram container ID missing: {container_resp}")

        # Wait for container to be ready then publish
        time.sleep(8)
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
                       results, errors, channel, start_year, end_year):
        """Save share results to output/{filename}/YT/{fmt}/share_log.json + share_log.txt"""
        import datetime
        log_dir = os.path.join(output_dir, "YT", fmt)
        os.makedirs(log_dir, exist_ok=True)

        parsed_results = []
        for r in results:
            platform = r.replace("✅ ", "").split(": ")[0].strip()
            detail = ": ".join(r.split(": ")[1:]).strip()
            parsed_results.append({"platform": platform, "status": "success", "detail": detail})
        for e in errors:
            platform = e.replace("❌ ", "").split(": ")[0].strip()
            detail = ": ".join(e.split(": ")[1:]).strip()
            parsed_results.append({"platform": platform, "status": "failed", "error": detail})

        data = {
            "topic": topic,
            "channel": channel,
            "year_range": f"{start_year}–{end_year}",
            "shared_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "video_url": video_url,
            "format": fmt,
            "platforms": platforms,
            "success": len(results),
            "failed": len(errors),
            "shares": parsed_results,
        }

        json_path = os.path.join(log_dir, "share_log.json")
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        sep = "━" * 52
        txt_lines = [
            sep,
            "📢 SOCIAL SHARE LOG",
            f"Topic     : {topic}",
            f"Channel   : @{channel}",
            f"Year Range: {start_year}–{end_year}",
            f"Shared at : {data['shared_at']}",
            f"Video URL : {video_url}",
            f"Success   : {len(results)} / {len(platforms)}",
            sep, " ",
        ]
        for s in parsed_results:
            icon = "✅" if s["status"] == "success" else "❌"
            key = "detail" if s["status"] == "success" else "error"
            txt_lines.append(f"{icon} {s['platform']}: {s.get(key,'')}")
        txt_lines += [" ", sep]

        txt_path = os.path.join(log_dir, "share_log.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(txt_lines))

        print(f"[SocialShare] 💾 Share log → {json_path}")
        print(f"[SocialShare] 💾 Share log → {txt_path}")
