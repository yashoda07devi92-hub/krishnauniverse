#!/usr/bin/env python3
"""
Upload generated Krishna Universe episodes to YouTube.

Reads manifest.json and uploads any episode not yet marked uploaded_youtube.
Each successful upload (and its thumbnail) is recorded back into the manifest.

Usage:
  python upload_youtube.py                 # upload all pending episodes
  python upload_youtube.py --limit 1       # upload only the next pending one
  python upload_youtube.py --authorize     # one-time local OAuth to mint a token
"""

import argparse
import json
import logging
import os
import sys

from modules.config import BASE_DIR, setup_logging
from modules import youtube

log = logging.getLogger("krishna.upload")

MANIFEST_PATH = os.path.join(str(BASE_DIR), "manifest.json")


def _load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("episodes"), list):
            return data
    except Exception as exc:
        log.error("Could not read manifest (%s).", exc)
    return {"episodes": []}


def _save_manifest(manifest):
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.error("Could not write manifest (%s).", exc)


def _abs(path):
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(str(BASE_DIR), path)


def run(limit=None):
    manifest = _load_manifest()
    pending = [e for e in manifest["episodes"] if not e.get("uploaded_youtube")]
    if not pending:
        log.info("No pending episodes to upload.")
        return 0
    if limit is not None:
        pending = pending[: max(1, int(limit))]

    uploaded = 0
    for entry in pending:
        video_path = _abs(entry.get("video_path"))
        if not video_path or not os.path.exists(video_path):
            log.warning("Video missing for '%s'; skipping.", entry.get("title"))
            continue
        # Prefer the SEO-built fields written at generate time; fall back to the
        # raw story fields so pre-existing manifest entries still upload.
        vid = youtube.upload_video(
            video_path=video_path,
            title=entry.get("youtube_title") or entry.get("title", "A Moral Story"),
            description=entry.get("description", ""),
            tags=entry.get("youtube_tags") or entry.get("keywords", []),
            thumbnail_path=_abs(entry.get("thumbnail_path")),
        )
        if vid:
            entry["uploaded_youtube"] = True
            entry["youtube_id"] = vid
            uploaded += 1
            _save_manifest(manifest)
        else:
            log.warning("Upload failed for '%s'.", entry.get("title"))

    log.info("Uploaded %d episode(s).", uploaded)
    return 0 if uploaded or not pending else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Upload Krishna Universe episodes to YouTube.")
    parser.add_argument("--authorize", action="store_true", help="Run one-time local OAuth flow.")
    parser.add_argument("--limit", type=int, default=None, help="Max episodes to upload now.")
    args = parser.parse_args(argv)

    setup_logging()
    if args.authorize:
        youtube.authorize()
        return 0
    return run(limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
