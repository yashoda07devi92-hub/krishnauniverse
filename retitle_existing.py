#!/usr/bin/env python3
"""
Rewrite the metadata of videos ALREADY published on the channel.

THE PROBLEM THIS SOLVES
-----------------------
Every video published before the SEO engine landed carries the same stamped
title suffix and the same hashtag block:

    "A Rescue Kitten Finds True Love | Cute & Wholesome #shorts #cute"
    "Puppy Discovers Snow For The First Time | Cute & Wholesome #shorts #cute"
    "The Sweetest Game of Hide and Seek | Cute & Wholesome #shorts #cute"

Fixing the generator only fixes FUTURE uploads. The back catalogue is still a
wall of near-identical metadata, and that is what a YouTube Partner Program
reviewer looks at when the channel applies, and what search matches today. This
script rewrites the existing videos in place.

WHAT IT CHANGES
---------------
For each video it rebuilds the title (search anchor + rotating pattern, legacy
suffix removed), the description (unique body + per-video hashtags) and the tags,
using the exact same modules/seo.py engine the generator now uses. The video
file, the view count, the URL and the publish date are untouched.

SCOPE REQUIREMENT
-----------------
Reading your own uploads and calling videos.update needs a broader OAuth scope
than uploading does:

    https://www.googleapis.com/auth/youtube.force-ssl

The YT_TOKEN_JSON used by the daily workflow only has `youtube.upload`, so mint
a SEPARATE token for this script:

    python retitle_existing.py --authorize

QUOTA
-----
The default YouTube Data API allowance is 10,000 units/day.
    videos.list   ~1 unit      videos.update  50 units
The daily workflow already spends roughly 8,000 units on uploads (1,600 each),
so keep --limit small (10-20) and run it across several days.

USAGE
-----
    python retitle_existing.py                      # DRY RUN, shows the diff
    python retitle_existing.py --limit 50            # dry run, more videos
    python retitle_existing.py --apply --limit 10    # actually write 10
    python retitle_existing.py --apply --only-legacy # only the stamped ones
"""

import argparse
import json
import logging
import os
import sys

from modules.config import BASE_DIR, get_cfg, get_env, setup_logging
from modules import seo

log = logging.getLogger("krishna.retitle")

# force-ssl is required for videos.update; upload alone is not enough.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TOKEN_FILE = os.path.join(str(BASE_DIR), "yt_token_manage.json")
CLIENT_SECRET_FILE = os.path.join(str(BASE_DIR), "yt_client_secret.json")

# The exact fingerprint the old uploader stamped onto every title.
LEGACY_MARKERS = ("| Cute & Wholesome", "Cute & Wholesome #shorts")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def _materialize(env_name, dest):
    raw = get_env(env_name)
    if not raw:
        return dest if os.path.exists(dest) else None
    try:
        json.loads(raw)
    except Exception as exc:
        log.error("%s is not valid JSON (%s).", env_name, exc)
        return dest if os.path.exists(dest) else None
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(raw)
    return dest


def authorize():
    """One-time interactive flow to mint a force-ssl token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = _materialize("YT_CLIENT_SECRET_JSON", CLIENT_SECRET_FILE)
    if not secret or not os.path.exists(secret):
        log.error("No client secret. Set YT_CLIENT_SECRET_JSON or place "
                  "yt_client_secret.json next to this script.")
        return None
    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print("\nSaved to %s" % TOKEN_FILE)
    print("\nYT_MANAGE_TOKEN_JSON contents (store as a GitHub Secret if you want "
          "to run this from Actions):\n")
    print(creds.to_json())
    return TOKEN_FILE


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    path = _materialize("YT_MANAGE_TOKEN_JSON", TOKEN_FILE)
    if not path or not os.path.exists(path):
        log.error(
            "No management token found.\n"
            "This script needs the youtube.force-ssl scope, which the daily\n"
            "upload token does NOT have. Run:\n"
            "    python retitle_existing.py --authorize"
        )
        return None
    try:
        creds = Credentials.from_authorized_user_file(path, SCOPES)
    except Exception as exc:
        log.error("Could not load token (%s).", exc)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
        except Exception as exc:
            log.error("Token refresh failed (%s).", exc)
            return None
    return creds


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def _uploads_playlist_id(youtube):
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        log.error("No channel found for this token.")
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _list_video_ids(youtube, playlist_id, max_items):
    ids = []
    page = None
    while len(ids) < max_items:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=playlist_id,
            maxResults=50, pageToken=page,
        ).execute()
        for item in resp.get("items", []):
            ids.append(item["contentDetails"]["videoId"])
        page = resp.get("nextPageToken")
        if not page:
            break
    return ids[:max_items]


def _fetch_videos(youtube, video_ids):
    out = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = youtube.videos().list(
            # statistics is needed for --skip-top, which protects the videos
            # that are actually earning views.
            part="snippet,status,statistics", id=",".join(chunk)
        ).execute()
        out.extend(resp.get("items", []))
    return out


# --------------------------------------------------------------------------
# Rewrite
# --------------------------------------------------------------------------
def _is_legacy(title):
    return any(marker in (title or "") for marker in LEGACY_MARKERS)


def _views(video):
    try:
        return int(video.get("statistics", {}).get("viewCount", 0))
    except Exception:
        return 0


def _protect_top(videos, skip_top):
    """Split videos into (safe_to_edit, protected) by view count.

    WHY THIS EXISTS: a video that is currently earning views has accumulated
    ranking signals against its existing title and description. Rewriting that
    metadata makes YouTube re-index it, and reach can dip for a few days. There
    is nothing to lose on a video sitting at 275 views, but there is on the ones
    carrying the channel. So the best performers are left alone by default.
    """
    skip_top = max(0, int(skip_top))
    if not skip_top:
        return videos, []
    ranked = sorted(videos, key=_views, reverse=True)
    protected = ranked[:skip_top]
    protected_ids = {v["id"] for v in protected}
    safe = [v for v in videos if v["id"] not in protected_ids]
    return safe, protected


def _original_core(video):
    """Recover the human-written part of the title, minus the stamped suffix."""
    title = video["snippet"].get("title", "")
    for marker in LEGACY_MARKERS:
        if marker in title:
            title = title.split(marker)[0]
            break
    return title.strip(" |-—")


def _narration_from_description(description):
    """The old descriptions opened with the full narration text, so it can be
    recovered and reused as the source for keyword extraction."""
    body = (description or "").strip()
    cut = body.find("Thanks for watching Krishna Universe")
    if cut > 0:
        body = body[:cut]
    return body.strip()


def plan_update(video):
    """Return (video_id, old, new) where new is a snippet-shaped dict."""
    snippet = video["snippet"]
    vid = video["id"]
    core = _original_core(video)
    narration = _narration_from_description(snippet.get("description", ""))
    existing_tags = snippet.get("tags") or []

    meta = seo.build_metadata(
        core_title=core or snippet.get("title", ""),
        text=narration,
        keywords=[t for t in existing_tags if " " in t][:6],
    )

    new_snippet = {
        # categoryId is REQUIRED on videos.update; omitting it wipes it.
        "categoryId": snippet.get("categoryId") or str(get_cfg("youtube.category_id", "15")),
        "title": meta["youtube_title"],
        "description": meta["youtube_description"],
        "tags": meta["youtube_tags"],
    }
    if snippet.get("defaultLanguage"):
        new_snippet["defaultLanguage"] = snippet["defaultLanguage"]

    old = {
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": existing_tags,
    }
    return vid, old, new_snippet


def run(limit=20, apply_changes=False, only_legacy=False, skip_top=15):
    from googleapiclient.discovery import build

    creds = _credentials()
    if creds is None:
        return 1

    youtube = build("youtube", "v3", credentials=creds)
    playlist_id = _uploads_playlist_id(youtube)
    if not playlist_id:
        return 1

    # Pull the whole catalogue: --skip-top has to rank against every video, not
    # just the slice we happen to be editing this run.
    video_ids = _list_video_ids(youtube, playlist_id, max_items=500)
    videos = _fetch_videos(youtube, video_ids)
    log.info("Fetched %d video(s) from the channel.", len(videos))

    if only_legacy:
        videos = [v for v in videos if _is_legacy(v["snippet"].get("title", ""))]
        log.info("%d carry the legacy '| Cute & Wholesome' stamp.", len(videos))

    videos, protected = _protect_top(videos, skip_top)
    if protected:
        log.info("Protecting the %d best-performing video(s):", len(protected))
        for v in protected:
            log.info("  %6d views  %s", _views(v), v["snippet"].get("title", "")[:56])

    # Worst performers first: least to lose, most to gain.
    videos.sort(key=_views)
    videos = videos[:limit]
    if not videos:
        log.info("Nothing to do.")
        return 0

    changed = 0
    for v in videos:
        vid, old, new = plan_update(v)
        print("\n" + "=" * 70)
        print(f"https://youtu.be/{vid}   ({_views(v)} views)")
        print(f"  OLD title : {old['title']}")
        print(f"  NEW title : {new['title']}")
        print(f"  OLD tags  : {len(old['tags'])} tag(s)")
        print(f"  NEW tags  : {len(new['tags'])} tag(s)")
        print(f"  NEW hashtags: {new['description'].strip().splitlines()[-1]}")

        if not apply_changes:
            continue
        try:
            youtube.videos().update(
                part="snippet", body={"id": vid, "snippet": new}
            ).execute()
            changed += 1
            log.info("Updated %s", vid)
        except Exception as exc:
            log.error("Failed to update %s (%s)", vid, exc)

    print("\n" + "=" * 70)
    if apply_changes:
        print(f"Updated {changed}/{len(videos)} video(s).")
        print("Search re-indexing usually shows up within a few hours.")
    else:
        print(f"DRY RUN - nothing was changed. {len(videos)} video(s) previewed.")
        print("Re-run with --apply once the new titles look right to you.")
    print("=" * 70)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rewrite titles/descriptions/tags of already-published videos."
    )
    parser.add_argument("--authorize", action="store_true",
                        help="One-time OAuth flow to mint a force-ssl token.")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max videos to touch this run (watch your API quota).")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write the changes. Without this it is a dry run.")
    parser.add_argument("--only-legacy", action="store_true",
                        help="Only videos still carrying the '| Cute & Wholesome' stamp.")
    parser.add_argument("--skip-top", type=int, default=15,
                        help="Leave the N best-performing videos untouched (default 15). "
                             "Rewriting a video that is currently earning views makes "
                             "YouTube re-index it and reach can dip for a few days. "
                             "Pass 0 to rewrite everything.")
    args = parser.parse_args(argv)

    setup_logging()
    if args.authorize:
        return 0 if authorize() else 1
    return run(
        limit=args.limit,
        apply_changes=args.apply,
        only_legacy=args.only_legacy,
        skip_top=args.skip_top,
    )


if __name__ == "__main__":
    sys.exit(main())
