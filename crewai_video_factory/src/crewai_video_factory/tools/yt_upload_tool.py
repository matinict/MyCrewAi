"""
YouTube Upload Tool
Automates video uploads and multi-language subtitle (CC) injection.
Matches the directory structure: output/{Topic}/YT/{Format}/CC/
"""

import os
import json
import time
from typing import Type, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

# Google API Imports
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

class YTUploadToolInput(BaseModel):
    """Input schema for YTUploadTool."""
    topic:               str   = Field(...,  description="Topic name (e.g., 'LLM Alignment RLHF')")
    output_dir:          str   = Field(...,  description="Full path to the output/Topic directory")
    video_formats:       list  = Field(...,  description="Formats to upload: ['HD', 'Shorts']")
    upload_youtube_video: bool = Field(default=False, description="Master switch")
    channel:             str   = Field(default="PlayOwnAi", description="Channel prefix")
    privacy_status:      str   = Field(default="private", description="public, private, or unlisted")

class YTUploadTool(BaseTool):
    name: str = "yt_upload_tool"
    description: str = "Uploads videos and 30+ language subtitles to YouTube automatically."
    args_schema: Type[BaseModel] = YTUploadToolInput

    SCOPES: List[str] = [
        'https://www.googleapis.com/auth/youtube.upload',
        'https://www.googleapis.com/auth/youtube.force-ssl'
    ]

    def _run(self, topic: str, output_dir: str, video_formats: list,
             upload_youtube_video: bool, channel: str = "PlayOwnAi",
             privacy_status: str = "private") -> str:

        if not upload_youtube_video:
            return "Skipping YouTube upload (upload_youtube_video=false)."

        try:
            creds = self._get_credentials()
            youtube = build("youtube", "v3", credentials=creds)
        except Exception as e:
            return f"❌ Auth Error: {str(e)}"

        results = []
        errors = []

        for fmt in video_formats:
            # 1. Map File Paths
            clean_topic = topic.replace(" ", "_")
            video_name = f"{channel}_{clean_topic}_{fmt}.mp4"
            video_path = os.path.join(output_dir, video_name)

            # Metadata path: output/Topic/YT/HD/MD/en.json
            metadata_path = os.path.join(output_dir, "YT", fmt, "MD", "en.json")

            if not os.path.exists(video_path):
                errors.append(f"{fmt}: Video file not found: {video_path}")
                continue

            # 2. Upload Video
            metadata = self._load_metadata(metadata_path, topic)
            print(f"🚀 Uploading {fmt} to YouTube...")

            try:
                video_id = self._upload_video(youtube, video_path, metadata, privacy_status)

                # 3. Automatic CC Upload (The "n8n" style bulk loop)
                cc_stats = self._upload_cc_files(youtube, video_id, output_dir, fmt)

                results.append(
                    f"{fmt} (ID: {video_id}) | CC: {cc_stats['uploaded']} uploaded"
                )
            except Exception as e:
                errors.append(f"{fmt}: Upload failed - {str(e)}")

        return self._format_summary(results, errors)

    def _get_credentials(self):
        """Points to your 'input/' folder credentials."""
        token_path = 'input/token.json'
        secret_path = 'input/client_secrets.json'

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(secret_path, self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        return creds

    def _upload_video(self, youtube, file_path, metadata, privacy):
        body = {
            'snippet': {
                'title': metadata.get('title', 'AI Video')[:100],
                'description': metadata.get('description', '')[:5000],
                'tags': metadata.get('tags', []),
                'categoryId': '27' # Education
            },
            'status': {
                'privacyStatus': privacy,
                'selfDeclaredMadeForKids': False
            }
        }

        media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
        return response.get("id")

    def _upload_cc_files(self, youtube, video_id, output_dir, fmt):
        """Scans the CC folder and uploads every language file found."""
        cc_dir = os.path.join(output_dir, "YT", fmt, "CC")
        stats = {"uploaded": 0, "failed": 0}

        if not os.path.exists(cc_dir):
            return stats

        for filename in os.listdir(cc_dir):
            if filename.endswith(".txt"):
                lang_code = filename.replace(".txt", "")
                file_path = os.path.join(cc_dir, filename)

                try:
                    youtube.captions().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "videoId": video_id,
                                "language": lang_code,
                                "name": f"{lang_code} auto-translation",
                                "isDraft": False
                            }
                        },
                        media_body=MediaFileUpload(file_path, mimetype='text/plain')
                    ).execute()
                    stats["uploaded"] += 1
                except:
                    stats["failed"] += 1
        return stats

    def _load_metadata(self, path, topic):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {"title": topic, "description": "AI Generated Content", "tags": ["AI"]}

    def _format_summary(self, results, errors):
        summary = "✅ YouTube Success:\n" + "\n".join(results)
        if errors:
            summary += "\n\n❌ Errors:\n" + "\n".join(errors)
        return summary
