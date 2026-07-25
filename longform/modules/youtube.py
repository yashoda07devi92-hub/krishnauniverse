"""
YouTube auto-upload for Krishna Universe Katha via the YouTube Data API v3 + OAuth2.

Credentials are read from environment variables (so they can live in GitHub
Secrets) and written to local files at runtime:
  * YT_CLIENT_SECRET_JSON - the FULL contents of the OAuth client secret JSON
    from Google Cloud Console.
  * YT_TOKEN_JSON         - the FULL contents of an authorized OAuth token JSON
    (refresh token etc.), e.g. produced by `python upload_youtube.py --authorize`.

A thumbnail is uploaded too when one is provided. Heavy google-api libraries
are imported lazily so importing this module never hard-fails.
"""

import json
import logging
import os

from .config import BASE_DIR, get_cfg, get_env

log = logging.getLogger("krishna.youtube")

# upload scope covers video insert + thumbnail set.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CLIENT_SECRET_FILE = os.path.join(str(BASE_DIR), "yt_client_secret.json")
TOKEN_FILE = os.path.join(str(BASE_DIR), "yt_token.json")

# YouTube rejects the request if the tags field exceeds 500 characters in total.
TAGS_CHAR_BUDGET = 480


def _trim_tags(tags):
    """Drop tags from the end until the whole list fits the 500-char budget."""
    kept, used = [], 0
    for tag in tags:
        tag = str(tag or "").strip()
        if not tag:
            continue
        cost = len(tag) + 1
        if used + cost > TAGS_CHAR_BUDGET:
            continue
        kept.append(tag)
        used += cost
    return kept


def _materialize_env_json(env_name, dest_path):
    raw = get_env(env_name)
    if not raw:
        return dest_path if os.path.exists(dest_path) else None
    try:
        json.loads(raw)
    except Exception as exc:
        log.error("%s does not contain valid JSON (%s).", env_name, exc)
        return dest_path if os.path.exists(dest_path) else None
    try:
        with open(dest_path, "w", encoding="utf-8") as fh:
            fh.write(raw)
        log.info("Wrote %s -> %s", env_name, os.path.basename(dest_path))
        return dest_path
    except Exception as exc:
        log.error("Could not write %s (%s).", dest_path, exc)
        return dest_path if os.path.exists(dest_path) else None


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = _materialize_env_json("YT_TOKEN_JSON", TOKEN_FILE)
    if not token_path or not os.path.exists(token_path):
        log.error(
            "No YouTube token available. Provide YT_TOKEN_JSON or run "
            "`python upload_youtube.py --authorize` locally first."
        )
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    except Exception as exc:
        log.error("Could not load token (%s).", exc)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
            log.info("Refreshed YouTube OAuth token.")
        except Exception as exc:
            log.error("Token refresh failed (%s).", exc)
            return None
    return creds


def authorize():
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret_path = _materialize_env_json("YT_CLIENT_SECRET_JSON", CLIENT_SECRET_FILE)
    if not secret_path or not os.path.exists(secret_path):
        log.error("No client secret found. Provide YT_CLIENT_SECRET_JSON.")
        return None
    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    log.info("Authorization complete. Token saved to %s", TOKEN_FILE)
    print("\nYT_TOKEN_JSON contents (copy this into your GitHub Secret):\n")
    print(creds.to_json())
    return TOKEN_FILE


def _build_metadata(title, description, tags):
    """Assemble the API request body.

    The static config hashtag string and default tag list are now FALLBACKS
    only. modules/seo.py builds a per-episode hashtag and tag set at generate
    time; appending the same fixed block on top of it is what gave every episode
    an identical metadata footprint.
    """
    all_tags = list(dict.fromkeys(tags or []))
    if not all_tags:
        all_tags = list(dict.fromkeys(get_cfg("youtube.default_tags", [])))
    all_tags = _trim_tags(all_tags)

    full_desc = (description or "").strip()
    if "#" not in full_desc:
        hashtags = get_cfg("youtube.hashtags", "#moralstories #storiesforkids")
        if hashtags:
            full_desc = (full_desc + "\n\n" + hashtags).strip()
    return {
        "snippet": {
            "title": title[:100],
            "description": full_desc[:4900],
            "tags": all_tags,
            "categoryId": str(get_cfg("youtube.category_id", "24")),
        },
        "status": {
            "privacyStatus": get_cfg("youtube.privacy_status", "public"),
            "selfDeclaredMadeForKids": bool(get_cfg("youtube.made_for_kids", False)),
        },
    }


def _set_thumbnail(youtube, video_id, thumbnail_path):
    from googleapiclient.http import MediaFileUpload

    if not thumbnail_path or not os.path.exists(thumbnail_path):
        return False
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
        ).execute()
        log.info("Thumbnail set for %s", video_id)
        return True
    except Exception as exc:
        log.warning("Could not set thumbnail (%s).", exc)
        return False


def upload_video(video_path, title, description="", tags=None, privacy=None, thumbnail_path=None):
    """Upload a single video (+ optional thumbnail) to YouTube. Returns id/None."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    if not os.path.exists(video_path):
        log.error("Video file not found: %s", video_path)
        return None
    creds = _load_credentials()
    if creds is None:
        return None

    body = _build_metadata(title, description, tags)
    if privacy:
        body["status"]["privacyStatus"] = privacy

    try:
        youtube = build("youtube", "v3", credentials=creds)
        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        log.info("Uploading '%s' to YouTube...", title)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("Upload progress: %d%%", int(status.progress() * 100))
        video_id = response.get("id")
        log.info("Uploaded! https://youtu.be/%s", video_id)
        if thumbnail_path:
            _set_thumbnail(youtube, video_id, thumbnail_path)
        return video_id
    except HttpError as exc:
        log.error("YouTube API error (%s).", exc)
        return None
    except Exception as exc:
        log.error("Upload failed (%s).", exc)
        return None
