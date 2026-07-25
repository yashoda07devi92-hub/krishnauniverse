#!/usr/bin/env python3
"""
Krishna Universe - OPTIONAL Instagram uploader (CLI).

DISABLED BY DEFAULT. Automated Instagram posting violates Instagram's Terms of
Service and can get your account banned. Enable only at your own risk by setting
config.instagram.enabled = true and providing IG_USERNAME / IG_PASSWORD.

Usage
-----
  python upload_instagram.py --limit 1
"""

import argparse
import json
import logging
import os
import sys

from modules.config import BASE_DIR, get_cfg, setup_logging
from modules import instagram

log = logging.getLogger("krishna.upload.instagram")

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


def _caption(entry):
    title = entry.get("title", "A KrishnaUniverse Story")
    hashtags = get_cfg(
        "youtube.hashtags",
        "#shorts #cute #puppy #baby #aww #animals #wholesome #heartwarming",
    )
    return f"{title}\n\nFollow Krishna Universe for your daily dose of joy.\n{hashtags}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Upload KrishnaUniverse reels to Instagram (optional).")
    parser.add_argument("--limit", type=int, default=1, help="Max reels to upload this run.")
    args = parser.parse_args(argv)

    setup_logging()

    if not get_cfg("instagram.enabled", False):
        log.warning(
            "Instagram uploading is OFF (config.instagram.enabled=false). "
            "Enable it explicitly and accept the ban risk to use this."
        )
        return 0

    manifest = _load_manifest()
    reels = manifest.get("reels", [])
    pending = [r for r in reversed(reels) if not r.get("uploaded_instagram")]
    if not pending:
        log.info("No pending reels for Instagram.")
        return 0

    batch = pending[: max(1, int(args.limit))]
    items = []
    for entry in batch:
        rel = entry.get("video_path")
        path = os.path.join(str(BASE_DIR), rel) if rel else None
        if path and os.path.exists(path):
            items.append((path, _caption(entry)))

    results = instagram.upload_many(items)
    # Mark successes.
    by_path = {os.path.join(str(BASE_DIR), e.get("video_path", "")): e for e in batch}
    for path, media_id in results:
        if media_id and path in by_path:
            by_path[path]["uploaded_instagram"] = True
    _save_manifest(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
