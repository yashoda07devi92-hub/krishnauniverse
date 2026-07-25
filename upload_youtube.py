#!/usr/bin/env python3
"""
Krishna Universe - YouTube uploader (CLI).

Reads reels recorded in manifest.json (newest first) and uploads the ones that
have not been uploaded yet via the YouTube Data API v3 (OAuth2). Credentials
come from environment variables (GitHub Secrets) - see modules/youtube.py.

Usage
-----
  # One-time interactive authorization to mint a token (run locally):
  python upload_youtube.py --authorize

  # Upload the most recent un-uploaded reel(s):
  python upload_youtube.py --limit 1

  # Upload as unlisted instead of public:
  python upload_youtube.py --limit 1 --privacy unlisted
"""

import argparse
import json
import logging
import os
import sys

from modules.config import BASE_DIR, get_cfg, setup_logging
from modules import seo
from modules import youtube

log = logging.getLogger("krishna.upload.youtube")

MANIFEST_PATH = os.path.join(str(BASE_DIR), "manifest.json")


def _load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("reels"), list):
            return data
    except Exception as exc:
        log.error("Could not read manifest (%s).", exc)
    return {"reels": []}


def _save_manifest(manifest):
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.error("Could not write manifest (%s).", exc)


def _build_title(entry):
    """Return the per-video SEO title produced at generate time.

    The previous implementation was:

        title = f"{base} | Cute & Wholesome #shorts #cute"

    ...which stamped a byte-identical 30-character suffix onto every single
    upload. It buried the click-worthy words past the point where the Shorts UI
    truncates the title, made every video compete for the same query, and gave
    the channel a textbook "template-based content" fingerprint.

    New behaviour: use `youtube_title` from the manifest. Entries created before
    this change (or hand-edited ones) are re-run through modules/seo.py so the
    legacy suffix is stripped rather than reproduced.
    """
    title = (entry.get("youtube_title") or "").strip()
    if title:
        return title[:100]

    log.info("No youtube_title in manifest for %r; deriving one now.", entry.get("title"))
    return seo.build_title(
        core_title=entry.get("title") or "A KrishnaUniverse Story",
        text=entry.get("text", ""),
        keywords=entry.get("keywords") or [],
    )[:100]


def _description(entry):
    """Description from the manifest, rebuilt on the fly for legacy entries."""
    desc = (entry.get("description") or "").strip()
    # Legacy entries stored the raw narration + boilerplate with no hashtags.
    if desc and "#" in desc:
        return desc
    meta = seo.build_metadata(
        core_title=entry.get("title") or "A KrishnaUniverse Story",
        text=entry.get("text", ""),
        keywords=entry.get("keywords") or [],
    )
    return meta["youtube_description"]


def _tags(entry):
    tags = entry.get("youtube_tags") or []
    if tags:
        return list(tags)
    return seo.build_tags(
        core_title=entry.get("title", ""),
        keywords=entry.get("keywords") or [],
        subject=seo.detect_subject(
            entry.get("title", ""), entry.get("text", ""), entry.get("keywords")
        ),
        extra=get_cfg("youtube.default_tags", []),
    )


def _thumbnail(entry):
    rel = entry.get("thumbnail_path")
    if not rel:
        return None
    path = os.path.join(str(BASE_DIR), rel)
    return path if os.path.exists(path) else None


def upload_pending(limit=1, privacy=None):
    manifest = _load_manifest()
    reels = manifest.get("reels", [])
    if not reels:
        log.warning("No reels in manifest; nothing to upload. Run generate.py first.")
        return {"pending": 0, "uploaded": 0, "failed": 0}

    privacy = privacy or get_cfg("youtube.privacy_status", "public")
    # Newest first.
    pending = [r for r in reversed(reels) if not r.get("uploaded_youtube")]
    if not pending:
        log.info("All reels already uploaded to YouTube.")
        return {"pending": 0, "uploaded": 0, "failed": 0}

    batch = pending[: max(1, int(limit))]
    uploaded = []
    failed = 0
    for entry in batch:
        video_rel = entry.get("video_path")
        video_path = os.path.join(str(BASE_DIR), video_rel) if video_rel else None
        if not video_path or not os.path.exists(video_path):
            log.error("Video file missing for '%s' (%s); skipping.", entry.get("title"), video_path)
            failed += 1
            continue
        vid = youtube.upload_video(
            video_path=video_path,
            title=_build_title(entry),
            description=_description(entry),
            tags=_tags(entry),
            privacy=privacy,
            thumbnail_path=_thumbnail(entry),
        )
        if vid:
            entry["uploaded_youtube"] = True
            entry["youtube_id"] = vid
            uploaded.append(entry)
            _save_manifest(manifest)
            # The pinned comment cannot be posted with the youtube.upload scope
            # alone (it needs youtube.force-ssl), so surface it in the log for
            # a 5-second manual paste that reliably kick-starts the comments.
            if entry.get("pinned_comment"):
                log.info(
                    "PIN THIS COMMENT on https://youtu.be/%s -> %s",
                    vid, entry["pinned_comment"],
                )
        else:
            log.error("Upload failed for '%s'.", entry.get("title"))
            failed += 1

    log.info("Uploaded %d reel(s) to YouTube (%d failed).", len(uploaded), failed)
    return {"pending": len(batch), "uploaded": len(uploaded), "failed": failed}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Upload KrishnaUniverse reels to YouTube.")
    parser.add_argument("--authorize", action="store_true", help="Run one-time OAuth authorization.")
    parser.add_argument("--limit", type=int, default=1, help="Max reels to upload this run.")
    parser.add_argument("--privacy", type=str, default=None,
                        choices=["public", "unlisted", "private"],
                        help="Privacy status (default from config.json: public).")
    args = parser.parse_args(argv)

    setup_logging()

    if args.authorize:
        path = youtube.authorize()
        return 0 if path else 1

    result = upload_pending(limit=args.limit, privacy=args.privacy)

    # Fail loudly: if there were reels waiting to upload and NONE made it, the
    # run must go RED so the failure is visible (token expired, quota, etc.).
    # Previously this always returned 0, so failed uploads looked "green" and
    # videos silently never appeared on YouTube.
    if result["uploaded"] == 0 and result["failed"] > 0:
        log.error(
            "No reels were uploaded though %d were pending. Failing the run so "
            "this is visible. Check the YouTube errors above.",
            result["failed"],
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
