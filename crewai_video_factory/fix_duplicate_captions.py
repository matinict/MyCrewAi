#!/usr/bin/env python3
"""
fix_duplicate_captions.py — with quota-safe resume
────────────────────────────────────────────────────
Fixes YouTube Studio double rows by deleting caption tracks with name=lang_code
and re-uploading them with name=''. Stops immediately on quota exceeded.
Re-run tomorrow — already-fixed tracks are automatically skipped.

Usage:Test
    .venv/bin/python fix_duplicate_captions.py \
        --video_id L2PTGiN9JTQ \
        --cc_dir output/LLMOptimizationQuantization/YT/Shorts/CC \
        --dry_run
Usage:Real
.venv/bin/python fix_duplicate_captions.py \
  --video_id L2PTGiN9JTQ \
  --cc_dir output/LLMOptimizationQuantization/YT/HD/CC
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
    words = text.split()
    if not words:
        return "1\n00:00:00,000 --> 00:00:05,000\n \n"
    chunks = [words[i:i+10] for i in range(0, len(words), 10)]
    lines = []
    for i, chunk in enumerate(chunks):
        s, e = i * 4.0, i * 4.0 + 4.0
        def fmt(x):
            h=int(x//3600); m=int((x%3600)//60); sec=x%60
            return f"{h:02d}:{m:02d}:{int(sec):02d},{int((sec%1)*1000):03d}"
        lines += [str(i+1), f"{fmt(s)} --> {fmt(e)}", " ".join(chunk), ""]
    return "\n".join(lines)


def is_quota_error(e):
    return "quotaExceeded" in str(e) or "403" in str(e) and "quota" in str(e).lower()


def fix_captions(video_id, cc_dir, dry_run=False,
                 secrets_file="client_secrets.json", token_file="token.json"):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaInMemoryUpload

    creds   = get_credentials(secrets_file, token_file)
    youtube = build("youtube", "v3", credentials=creds)

    # ── Fetch current caption tracks ─────────────────────────────────────────
    resp  = youtube.captions().list(part="snippet", videoId=video_id).execute()
    items = resp.get("items", [])
    print(f"\nFound {len(items)} caption track(s) on {video_id}")

    # Tracks still having name=lang_code (not yet fixed)
    bad_tracks = [
        it for it in items
        if it["snippet"].get("name") == it["snippet"].get("language")
        and it["snippet"].get("name") != ""
        and it["snippet"].get("trackKind") != "asr"
    ]

    # Tracks already fixed (name='') — just report them
    good_tracks = [
        it for it in items
        if it["snippet"].get("name") == ""
        and it["snippet"].get("trackKind") != "asr"
    ]

    asr_tracks = [it for it in items if it["snippet"].get("trackKind") == "asr"]

    print(f"  ✅ Already fixed (name=''):  {len(good_tracks)} tracks — skipping")
    print(f"  ⚠️  Still need fixing:        {len(bad_tracks)} tracks")
    print(f"  🤖 ASR auto-generated:        {len(asr_tracks)} tracks")

    if good_tracks:
        langs = ", ".join(t["snippet"]["language"] for t in good_tracks)
        print(f"     Skipped: {langs}")

    if not bad_tracks and not asr_tracks:
        print("\n✅ All done — nothing left to fix!")
        return

    fixed = 0; failed = 0; quota_hit = False

    # ── Fix bad tracks ────────────────────────────────────────────────────────
    for track in bad_tracks:
        lang = track["snippet"]["language"]
        tid  = track["id"]
        cc_file = os.path.join(cc_dir, f"{lang}.txt") if cc_dir else None
        has_cc  = bool(cc_file and os.path.exists(cc_file))

        print(f"\n  [{lang}] name={repr(track['snippet']['name'])} → fix to name=''")
        print(f"    CC file: {'found ✅' if has_cc else 'NOT FOUND ⚠️'}")

        if dry_run:
            print(f"    [DRY RUN] Would delete + re-upload with name=''")
            fixed += 1
            continue

        # Step 1: Delete old track
        try:
            youtube.captions().delete(id=tid).execute()
            print(f"    ✅ Deleted old track")
            time.sleep(1)
        except Exception as e:
            if is_quota_error(e):
                remaining = len(bad_tracks) - fixed - failed
                print(f"\n  🛑 QUOTA EXCEEDED — stopping. {fixed} fixed so far, ~{remaining} remaining.")
                print(f"  ⏰ YouTube quota resets at midnight Pacific Time.")
                print(f"  ▶️  Run this script again tomorrow — already-fixed tracks will be skipped.")
                quota_hit = True
                break
            print(f"    ❌ Delete failed: {e}")
            failed += 1
            continue

        if not has_cc:
            print(f"    ⚠️  No CC file — deleted but not re-uploaded")
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
                    "name":     "",
                    "isDraft":  False,
                }},
                media_body=media
            ).execute()
            print(f"    ✅ Re-uploaded with name='' → will merge in Studio")
            fixed += 1
            time.sleep(0.5)
        except Exception as e:
            if is_quota_error(e):
                remaining = len(bad_tracks) - fixed - failed
                print(f"\n  🛑 QUOTA EXCEEDED on re-upload — stopping. {fixed} fixed so far.")
                print(f"  ⏰ Re-run tomorrow — fixed tracks auto-skipped.")
                quota_hit = True
                break
            print(f"    ❌ Re-upload failed: {e}")
            failed += 1

    # ── Delete ASR tracks (only if quota not hit) ─────────────────────────────
    if not quota_hit:
        for track in asr_tracks:
            lang = track["snippet"]["language"]
            tid  = track["id"]
            print(f"\n  [{lang}] ASR auto-generated → deleting")
            if dry_run:
                print(f"    [DRY RUN] Would delete ASR track")
                fixed += 1
                continue
            try:
                youtube.captions().delete(id=tid).execute()
                print(f"    ✅ ASR track deleted")
                fixed += 1
            except Exception as e:
                if is_quota_error(e):
                    print(f"    🛑 Quota exceeded — will retry tomorrow")
                    break
                print(f"    ❌ Failed: {e}")
                failed += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done — {fixed} fixed, {failed} failed.")
    if quota_hit:
        print(f"⏰ Quota hit — run again tomorrow to continue.")
    elif not dry_run and fixed > 0:
        print("🎉 Refresh YouTube Studio to see merged rows.")
    if dry_run:
        print("Run without --dry_run to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video_id", required=True)
    parser.add_argument("--cc_dir",   default="")
    parser.add_argument("--dry_run",  action="store_true")
    parser.add_argument("--secrets",  default="client_secrets.json")
    parser.add_argument("--token",    default="token.json")
    args = parser.parse_args()
    fix_captions(args.video_id, args.cc_dir, args.dry_run, args.secrets, args.token)
