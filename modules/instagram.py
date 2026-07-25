"""
OPTIONAL Instagram Reels uploader for Krishna Universe via instagrapi.

IMPORTANT - READ THIS:
  Automated posting to Instagram is AGAINST Instagram's Terms of Service and
  carries a REAL risk of getting the account temporarily or permanently
  banned. This module is therefore DISABLED by default (config.instagram.enabled
  = false) and is provided for completeness only. Use a throwaway / dedicated
  account, post conservatively (one at a time, with generous delays), and never
  store your password in plaintext.

Credentials are read from the environment:
  * IG_USERNAME
  * IG_PASSWORD
A session file (ig_session.json) is cached so we do not log in every run.

instagrapi is imported lazily so importing this module never hard-fails.
"""

import logging
import os
import time

from .config import BASE_DIR, get_cfg, get_env

log = logging.getLogger("krishna.instagram")

SESSION_FILE = os.path.join(str(BASE_DIR), "ig_session.json")

# Conservative delay (seconds) between consecutive uploads to look human.
UPLOAD_DELAY_SECONDS = 90


def _enabled():
    return bool(get_cfg("instagram.enabled", False))


def _get_client():
    """Return a logged-in instagrapi Client, or None on any problem."""
    username = get_env("IG_USERNAME")
    password = get_env("IG_PASSWORD")
    if not username or not password:
        log.error("IG_USERNAME / IG_PASSWORD not set; cannot use Instagram.")
        return None

    try:
        from instagrapi import Client
    except Exception as exc:
        log.error("instagrapi not available (%s).", exc)
        return None

    cl = Client()
    # Reuse a cached session when possible to reduce login challenges.
    try:
        if os.path.exists(SESSION_FILE):
            cl.load_settings(SESSION_FILE)
            log.info("Loaded cached Instagram session.")
    except Exception as exc:
        log.warning("Could not load IG session (%s); logging in fresh.", exc)

    try:
        cl.login(username, password)
        cl.dump_settings(SESSION_FILE)
        log.info("Instagram login OK for @%s.", username)
        return cl
    except Exception as exc:
        log.error("Instagram login failed (%s).", exc)
        return None


def upload_reel(video_path, caption):
    """Upload a single Reel. Returns media pk/id on success, else None."""
    if not _enabled():
        log.warning("Instagram uploading is disabled in config (instagram.enabled=false).")
        return None
    if not os.path.exists(video_path):
        log.error("Video not found for Instagram upload: %s", video_path)
        return None

    cl = _get_client()
    if cl is None:
        return None

    try:
        log.info("Uploading Reel to Instagram: %s", os.path.basename(video_path))
        media = cl.clip_upload(video_path, caption)
        media_id = getattr(media, "pk", None) or getattr(media, "id", None)
        log.info("Instagram Reel uploaded (id=%s).", media_id)
        return media_id
    except Exception as exc:
        log.error("Instagram upload failed (%s).", exc)
        return None


def upload_many(items):
    """Upload several reels conservatively (one at a time, with delays).

    `items` is an iterable of (video_path, caption) tuples.
    """
    if not _enabled():
        log.warning("Instagram uploading disabled; skipping batch.")
        return []
    results = []
    first = True
    for video_path, caption in items:
        if not first:
            log.info("Waiting %ds before next Instagram upload (anti-ban).", UPLOAD_DELAY_SECONDS)
            time.sleep(UPLOAD_DELAY_SECONDS)
        first = False
        media_id = upload_reel(video_path, caption)
        results.append((video_path, media_id))
    return results
