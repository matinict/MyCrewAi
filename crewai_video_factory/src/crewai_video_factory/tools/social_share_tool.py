"""
Social Share Tool
Reads upload_summary.json and posts the video URL to configured social platforms.

Supported platforms:
  - Facebook  (Graph API — Page post)
  - LinkedIn  (LinkedIn API v2 — Organization or Person post)
  - X         (Twitter API v2 — tweet)
  - YouTube   (YouTube Data API — Community post)
  - Instagram (Graph API — requires video/image, posts caption+link as comment workaround)

Triggered by: "social_share_enabled": true in data.json

Credentials go in input/social_credentials.json (never committed to git).

data.json example:
  "social_share_enabled": true,
  "social_platforms": ["Facebook", "LinkedIn", "X", "YouTube"],
"""

import os
import re
import json
import time
from typing import Type, List
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# ── Credentials file ────────────────────────────────────────────────────────
CREDS_PATH = "input/social_credentials.json"

CREDS_TEMPLATE = {
    "Facebook": {
        "page_id":       "YOUR_PAGE_ID",
        "access_token":  "YOUR_PAGE_ACCESS_TOKEN"
    },
    "LinkedIn": {
        "access_token":  "YOUR_LINKEDIN_ACCESS_TOKEN",
        "owner":         "urn:li:organization:YOUR_ORG_ID"
        # For personal: "urn:li:person:YOUR_PERSON_ID"
    },
    "X": {
        "api_key":            "YOUR_API_KEY",
        "api_secret":         "YOUR_API_SECRET",
        "access_token":       "YOUR_ACCESS_TOKEN",
        "access_token_secret":"YOUR_ACCESS_TOKEN_SECRET",
        "bearer_token":       "YOUR_BEARER_TOKEN"
    },
    "YouTube": {
        "client_secrets_file": "client_secrets.json",
        "token_file":          "token.json"
        # Reuses same OAuth as yt_upload_tool
    },
    "Instagram": {
        "ig_user_id":    "YOUR_IG_USER_ID",
        "access_token":  "YOUR_PAGE_ACCESS_TOKEN"
    }
}


class SocialShareInput(BaseModel):
    topic:                 str   = Field(...,  description="Topic name")
    filename:              str   = Field(...,  description="Base filename slug")
    output_dir:            str   = Field(...,  description="Output subdirectory")
    social_share_enabled:  bool  = Field(default=False, description="Enable social sharing")
    social_platforms:      list  = Field(default=["Facebook","LinkedIn","X","YouTube"],
                                         description="Platforms to post to")
    channel:               str   = Field(default="PlayOwnAi", description="Channel name for post text")
    website:               str   = Field(default="", description="Website URL for post footer")


class SocialShareTool(BaseTool):
    name: str = "Social Share Tool"
    description: str = (
        "Posts the uploaded YouTube video URL to configured social media platforms. "
        "Reads upload_summary.json to find the video URL. "
        "Triggered by social_share_enabled=true."
    )
    args_schema: Type[BaseModel] = SocialShareInput

    def _run(
        self,
        topic:                str,
        filename:             str,
        output_dir:           str,
        social_share_enabled: bool  = False,
        social_platforms:     list  = None,
        channel:              str   = "PlayOwnAi",
        website:              str   = "",
    ) -> str:

        if not social_share_enabled:
            return "⏭️  Social share skipped (social_share_enabled=false)"

        if social_platforms is None:
            social_platforms = ["Facebook", "LinkedIn", "X", "YouTube"]

        # ── Load upload_summary.json ─────────────────────────────────────
        summary_path = os.path.join(output_dir, "YT", "upload_summary.json")
        if not os.path.exists(summary_path):
            return f"❌ upload_summary.json not found at {summary_path}\nRun YouTube upload first."

        with open(summary_path) as f:
            summary = json.load(f)

        uploads = [u for u in summary.get("uploads", []) if u.get("status") == "success"]
        if not uploads:
            return "❌ No successful uploads found in upload_summary.json"

        # Pick URL — match first entry in video_formats, else first success
        target = next((u for u in uploads if u["format"] == video_formats[0]), None) if video_formats else None
        if not target:
            target = uploads[0]

        video_url  = target["video_url"]
        video_id   = target["video_id"]
        fmt        = target["format"]
        topic_text = summary.get("topic", topic)

        print(f"[SocialShare] 📎 Sharing URL: {video_url}  ({fmt})")
        print(f"[SocialShare] 📢 Platforms: {social_platforms}")

        # ── Load credentials ─────────────────────────────────────────────
        creds = self._load_credentials()

        # ── Build post text ──────────────────────────────────────────────
        post_text = self._build_post_text(topic_text, video_url, channel, website)
        short_text = self._build_post_text(topic_text, video_url, channel, website, short=True)

        results = []
        errors  = []

        for platform in social_platforms:
            p = platform.strip()
            print(f"\n[SocialShare] ── {p} ──────────────────────────")
            try:
                if p == "Facebook":
                    r = self._post_facebook(creds.get("Facebook", {}), post_text, video_url)
                elif p == "LinkedIn":
                    r = self._post_linkedin(creds.get("LinkedIn", {}), post_text, video_url)
                elif p in ("X", "Twitter"):
                    r = self._post_x(creds.get("X", {}), short_text)
                elif p == "YouTube":
                    r = self._post_youtube_community(creds.get("YouTube", {}), post_text, video_url)
                elif p == "Instagram":
                    r = self._post_instagram(creds.get("Instagram", {}), post_text, video_url)
                else:
                    r = f"⚠️ Unknown platform: {p}"
                results.append(f"✅ {p}: {r}")
                print(f"[SocialShare] ✅ {p}: {r}")
            except Exception as e:
                errors.append(f"❌ {p}: {e}")
                print(f"[SocialShare] ❌ {p}: {e}")

        # ── Save share log ───────────────────────────────────────────────
        self._save_share_log(output_dir, topic_text, video_url, fmt, social_platforms, results, errors)

        # ── Summary ──────────────────────────────────────────────────────
        out = f"📢 Social Share — {len(results)} posted, {len(errors)} failed\n"
        out += f"   Video URL: {video_url}\n\n"
        if results:
            out += "\n".join(f"   {r}" for r in results)
        if errors:
            out += "\n\n⚠️ Errors:\n" + "\n".join(f"   {e}" for e in errors)
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # POST TEXT BUILDER
    # ─────────────────────────────────────────────────────────────────────────
    def _build_post_text(self, topic, url, channel, website, short=False):
        hashtags = "#AI #DataVisualization #BarRace #MachineLearning #TechTrends"
        if short:
            # X: 280 char limit — keep tight
            text = f"📊 {topic} — Bar Race 2015–2026\n{url}\n\n#AI #DataViz #BarRace"
            return text[:280]
        lines = [
            f"📊 {topic} — Bar Race 2015–2026",
            "",
            f"Which approach dominated? Watch the data race unfold year by year! 🚀",
            "",
            f"🎬 Watch now: {url}",
            "",
            f"📺 Subscribe to @{channel} for more data-driven insights.",
        ]
        if website:
            lines.append(f"🌐 {website}")
        lines += ["", hashtags]
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # FACEBOOK
    # ─────────────────────────────────────────────────────────────────────────
    def _post_facebook(self, creds: dict, text: str, url: str) -> str:
        """Post to Facebook Page via Graph API."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        page_id      = creds.get("page_id", "")
        access_token = creds.get("access_token", "")
        if not page_id or not access_token or "YOUR_" in access_token:
            raise RuntimeError("Facebook credentials not configured in input/social_credentials.json")

        endpoint = f"https://graph.facebook.com/v19.0/{page_id}/feed"
        payload  = {"message": text, "link": url, "access_token": access_token}
        resp     = requests.post(endpoint, data=payload, timeout=30)
        data     = resp.json()

        if "error" in data:
            raise RuntimeError(f"Graph API error: {data['error'].get('message', data)}")

        post_id = data.get("id", "unknown")
        return f"Posted — post_id: {post_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # LINKEDIN
    # ─────────────────────────────────────────────────────────────────────────
    def _post_linkedin(self, creds: dict, text: str, url: str) -> str:
        """Post to LinkedIn Organization or Person via API v2."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        access_token = creds.get("access_token", "")
        owner        = creds.get("owner", "")   # urn:li:organization:xxx or urn:li:person:xxx
        if not access_token or not owner or "YOUR_" in access_token:
            raise RuntimeError("LinkedIn credentials not configured in input/social_credentials.json")

        headers = {
            "Authorization":  f"Bearer {access_token}",
            "Content-Type":   "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        body = {
            "author":     owner,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "ARTICLE",
                    "media": [{
                        "status":      "READY",
                        "originalUrl": url,
                        "title":       {"text": text[:100]},
                    }]
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        resp = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers, json=body, timeout=30
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"LinkedIn API {resp.status_code}: {resp.text[:200]}")

        post_id = resp.headers.get("x-restli-id", resp.json().get("id", "unknown"))
        return f"Posted — post_id: {post_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # X (TWITTER)
    # ─────────────────────────────────────────────────────────────────────────
    def _post_x(self, creds: dict, text: str) -> str:
        """Post tweet via Twitter API v2."""
        try:
            import requests
            from requests_oauthlib import OAuth1
        except ImportError:
            raise RuntimeError("Install: pip install requests requests-oauthlib")

        api_key    = creds.get("api_key", "")
        api_secret = creds.get("api_secret", "")
        at         = creds.get("access_token", "")
        at_secret  = creds.get("access_token_secret", "")
        if not api_key or "YOUR_" in api_key:
            raise RuntimeError("X credentials not configured in input/social_credentials.json")

        auth    = OAuth1(api_key, api_secret, at, at_secret)
        payload = {"text": text[:280]}
        resp    = requests.post(
            "https://api.twitter.com/2/tweets",
            auth=auth, json=payload, timeout=30
        )
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"X API error: {data['errors']}")

        tweet_id = data.get("data", {}).get("id", "unknown")
        return f"Tweeted — tweet_id: {tweet_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # YOUTUBE COMMUNITY POST
    # ─────────────────────────────────────────────────────────────────────────
    def _post_youtube_community(self, creds: dict, text: str, url: str) -> str:
        """Post YouTube Community post via YouTube Data API v3."""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            import google.auth.transport.requests as google_requests
        except ImportError:
            raise RuntimeError("Install: pip install google-auth-oauthlib google-api-python-client")

        SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
        token_file          = creds.get("token_file", "token.json")
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
                flow     = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
                cred_obj = flow.run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(cred_obj.to_json())

        youtube = build("youtube", "v3", credentials=cred_obj)
        body    = {
            "snippet": {
                "type":   "textPost",
                "textOriginalPost": f"{text}\n\n{url}"
            }
        }
        resp    = youtube.communityPosts().insert(part="snippet", body=body).execute()
        post_id = resp.get("id", "unknown")
        return f"Community post — post_id: {post_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # INSTAGRAM
    # ─────────────────────────────────────────────────────────────────────────
    def _post_instagram(self, creds: dict, text: str, url: str) -> str:
        """
        Post to Instagram via Graph API.
        Note: Instagram does not allow link-only posts.
        This posts a text caption with the URL embedded.
        A video/image container is required — posts a reel if video exists,
        otherwise raises a clear error.
        """
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed: pip install requests")

        ig_user_id   = creds.get("ig_user_id", "")
        access_token = creds.get("access_token", "")
        if not ig_user_id or "YOUR_" in ig_user_id:
            raise RuntimeError("Instagram credentials not configured in input/social_credentials.json")

        # Instagram requires a media object — post caption only via container
        # (Only works if you have a publicly accessible video URL)
        caption = f"{text}\n\n🎬 {url}"[:2200]

        # Step 1: Create media container (requires public video URL)
        container_resp = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
            data={
                "video_url":    url,
                "caption":      caption,
                "media_type":   "REELS",
                "access_token": access_token,
            },
            timeout=60
        ).json()

        if "error" in container_resp:
            raise RuntimeError(f"Instagram container error: {container_resp['error'].get('message', container_resp)}")

        container_id = container_resp.get("id")
        time.sleep(5)  # Wait for processing

        # Step 2: Publish
        publish_resp = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=30
        ).json()

        if "error" in publish_resp:
            raise RuntimeError(f"Instagram publish error: {publish_resp['error'].get('message', publish_resp)}")

        media_id = publish_resp.get("id", "unknown")
        return f"Reel posted — media_id: {media_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _load_credentials(self) -> dict:
        if os.path.exists(CREDS_PATH):
            with open(CREDS_PATH) as f:
                return json.load(f)
        # Auto-create template so user knows what to fill in
        os.makedirs(os.path.dirname(CREDS_PATH), exist_ok=True)
        with open(CREDS_PATH, "w") as f:
            json.dump(CREDS_TEMPLATE, f, indent=2)
        print(f"[SocialShare] ⚠️  Created credentials template: {CREDS_PATH}")
        print(f"[SocialShare]    Fill in your API keys and run again.")
        return {}

    def _save_share_log(self, output_dir, topic, video_url, fmt, platforms, results, errors):
        """Save share results to output/{filename}/YT/share_log.json + share_log.txt"""
        import datetime
        log_dir = os.path.join(output_dir, "YT")
        os.makedirs(log_dir, exist_ok=True)

        parsed_results = []
        for r in results:
            platform = r.replace("✅ ", "").split(":")[0].strip()
            detail   = ":".join(r.split(":")[1:]).strip()
            parsed_results.append({"platform": platform, "status": "success", "detail": detail})
        for e in errors:
            platform = e.replace("❌ ", "").split(":")[0].strip()
            detail   = ":".join(e.split(":")[1:]).strip()
            parsed_results.append({"platform": platform, "status": "failed",  "error":  detail})

        data = {
            "topic":      topic,
            "shared_at":  datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "video_url":  video_url,
            "format":     fmt,
            "platforms":  platforms,
            "success":    len(results),
            "failed":     len(errors),
            "shares":     parsed_results,
        }

        json_path = os.path.join(log_dir, "share_log.json")
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        sep = "━" * 52
        txt_lines = [
            sep,
            "📢 SOCIAL SHARE LOG",
            f"Topic     : {topic}",
            f"Shared at : {data['shared_at']}",
            f"Video URL : {video_url}",
            f"Success   : {len(results)} / {len(platforms)}",
            sep, "",
        ]
        for s in parsed_results:
            icon = "✅" if s["status"] == "success" else "❌"
            key  = "detail" if s["status"] == "success" else "error"
            txt_lines.append(f"{icon} {s['platform']}: {s.get(key,'')}")
        txt_lines += ["", sep]

        txt_path = os.path.join(log_dir, "share_log.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(txt_lines))

        print(f"[SocialShare] 💾 Share log → {json_path}")
        print(f"[SocialShare] 💾 Share log → {txt_path}")