#!/usr/bin/env python3
"""
fix_duplicate_captions.py
─────────────────────────
Fixes the YouTube Studio "double row" problem caused by uploading captions
with name=lang_code (e.g. name='ar') instead of name=''.

When name='ar', YouTube displays:
  Arabic          → Title & description only (from localizations)
  Arabic - ar     → Subtitles only           (from captions with name='ar')

Fix: delete the caption track with name=lang_code and re-upload it with name=''.
This merges the two rows into one "Arabic" row showing both.

Usage:
    .venv/bin/python fix_duplicate_captions.py --video_id VIDEO_ID --cc_dir PATH --dry_run
    .venv/bin/python fix_duplicate_captions.py --video_id VIDEO_ID --cc_dir PATH

Example:
    .venv/bin/python fix_duplicate_captions.py \\
        --video_id M0ur9bkK8M4 \\
        --cc_dir output/LLMOptimizationQuantization/YT/Shorts/CC \\
        --dry_run
"""

import os
import time
import argparse

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

def get_credentials(secrets_file="client_secrets.json", token_file="token.json"):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return creds


def text_to_srt(text: str) -> str:
    """Convert plain narration text to SRT format."""
    import math
    words = text.split()
    if not words:
        return "1\n00:00:00,000 --> 00:00:05,000\n \n"
    chunk_size = 10
    chunks = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]
    secs_per_chunk = 4.0
    lines = []
    for i, chunk in enumerate(chunks):
        start_s = i * secs_per_chunk
        end_s   = start_s + secs_per_chunk
        def fmt(s):
            h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
            return f"{h:02d}:{m:02d}:{int(sec):02d},{int((sec%1)*1000):03d}"
        lines += [str(i+1), f"{fmt(start_s)} --> {fmt(end_s)}", " ".join(chunk), ""]
    return "\n".join(lines)


def fix_captions(video_id, cc_dir, dry_run=False,
                 secrets_file="client_secrets.json", token_file="token.json"):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaInMemoryUpload

    creds   = get_credentials(secrets_file, token_file)
    youtube = build("youtube", "v3", credentials=creds)

    # ── Fetch all caption tracks ─────────────────────────────────────────────
    resp  = youtube.captions().list(part="snippet", videoId=video_id).execute()
    items = resp.get("items", [])
    print(f"\nFound {len(items)} caption track(s) on {video_id}")

    # Find tracks where name == lang_code (the bad ones, e.g. name='ar')
    bad_tracks = [
        it for it in items
        if it["snippet"].get("name") == it["snippet"].get("language")
        and it["snippet"].get("name") != ""
        and it["snippet"].get("trackKind") != "asr"
    ]

    # Also find lone ASR (auto-generated English)
    asr_tracks = [it for it in items if it["snippet"].get("trackKind") == "asr"]

    print(f"  Bad tracks (name=lang_code): {len(bad_tracks)}")
    print(f"  ASR auto-generated tracks:   {len(asr_tracks)}")

    if not bad_tracks and not asr_tracks:
        print("\n✅ Nothing to fix.")
        return

    # ── Fix bad tracks: delete + re-upload with name='' ─────────────────────
    fixed = 0; failed = 0

    for track in bad_tracks:
        lang = track["snippet"]["language"]
        tid  = track["id"]
        name = track["snippet"]["name"]

        # Find CC file for this language
        cc_file = os.path.join(cc_dir, f"{lang}.txt") if cc_dir else None
        has_cc  = cc_file and os.path.exists(cc_file)

        print(f"\n  [{lang}] name={repr(name)} → fix to name=''")
        print(f"    CC file: {cc_file} ({'found ✅' if has_cc else 'NOT FOUND ⚠️'})")

        if dry_run:
            print(f"    [DRY RUN] Would delete track {tid[:30]}… and re-upload with name=''")
            fixed += 1
            continue

        # Step 1: Delete the bad track
        try:
            youtube.captions().delete(id=tid).execute()
            print(f"    ✅ Deleted old track")
            time.sleep(1)
        except Exception as e:
            print(f"    ❌ Delete failed: {e}")
            failed += 1
            continue

        if not has_cc:
            print(f"    ⚠️  No CC file — track deleted but not re-uploaded (subtitle will be missing)")
            continue

        # Step 2: Re-upload with name=''
        try:
            cc_text = open(cc_file, encoding="utf-8").read().strip()
            srt     = text_to_srt(cc_text)
            media   = MediaInMemoryUpload(srt.encode("utf-8"), mimetype="application/x-subrip")
            youtube.captions().insert(
                part="snippet",
                body={"snippet": {
                    "videoId":  video_id,
                    "language": lang,
                    "name":     "",        # ← empty name = merges with localization row
                    "isDraft":  False,
                }},
                media_body=media
            ).execute()
            print(f"    ✅ Re-uploaded with name='' → row will merge in Studio")
            fixed += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"    ❌ Re-upload failed: {e}")
            failed += 1

    # ── Delete ASR tracks ─────────────────────────────────────────────────────
    for track in asr_tracks:
        lang = track["snippet"]["language"]
        tid  = track["id"]
        print(f"\n  [en] ASR auto-generated → delete")
        if dry_run:
            print(f"    [DRY RUN] Would delete ASR track {tid[:30]}…")
            fixed += 1
            continue
        try:
            youtube.captions().delete(id=tid).execute()
            print(f"    ✅ ASR track deleted")
            fixed += 1
        except Exception as e:
            print(f"    ❌ Delete failed: {e}")
            failed += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done — {fixed} fixed, {failed} failed.")
    if dry_run:
        print("Run without --dry_run to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video_id", required=True, help="YouTube video ID")
    parser.add_argument("--cc_dir",   default="",   help="Path to CC folder (YT/Shorts/CC) for re-upload")
    parser.add_argument("--dry_run",  action="store_true")
    parser.add_argument("--secrets",  default="client_secrets.json")
    parser.add_argument("--token",    default="token.json")
    args = parser.parse_args()
    fix_captions(args.video_id, args.cc_dir, args.dry_run, args.secrets, args.token)
