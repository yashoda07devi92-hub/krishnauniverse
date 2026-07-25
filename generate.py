#!/usr/bin/env python3
"""
Krishna Universe - reel generation pipeline (CLI).

End-to-end, defensive pipeline that, for each reel:
  1. Generates a heartwarming ~150-word script (Gemini -> quotes.json fallback).
  2. Synthesizes a warm USA female voiceover (edge-tts -> gTTS fallback).
  3. Builds a cinematic 1080x1920 vertical reel with a scroll-stopping 5s hook,
     real Pexels footage (photo/Picsum/gradient fallbacks), and timing-based
     animated captions.
  4. Records everything in a manifest.json so the uploader can post later.

Usage examples
--------------
  # Generate ONE reel (the default the GitHub Actions schedule uses):
  python generate.py --days 1 --per-day 1

  # Generate a small batch:
  python generate.py --days 1 --per-day 3

  # Generate around a specific topic idea:
  python generate.py --topic "rescue kitten finds a forever home"

The total number of reels produced is days * per_day (optionally capped by
--limit). Heavy media libraries are imported lazily inside the modules so that
`python generate.py --help` works even before dependencies are installed.
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys

from modules.config import OUTPUT_DIR, BASE_DIR, setup_logging
from modules import gemini_script
from modules import history
from modules import seo
from modules import thumbnail as thumbnail_mod
from modules import tts
from modules import video_composer

log = logging.getLogger("krishna.generate")

MANIFEST_PATH = os.path.join(str(BASE_DIR), "manifest.json")


def _slugify(text, max_len=40):
    """Make a filesystem-safe slug from a title."""
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in (" ", "-", "_"):
            keep.append("-")
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "krishna")[:max_len]


def _load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("reels"), list):
            return data
    except Exception:
        pass
    return {"reels": []}


def _save_manifest(manifest):
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        log.info("Manifest updated: %s (%d reel(s)).", MANIFEST_PATH, len(manifest["reels"]))
    except Exception as exc:
        log.error("Could not write manifest (%s).", exc)


def _build_seo(script):
    """Build the full YouTube metadata bundle for this reel.

    Done HERE (at generate time) rather than at upload time on purpose: the
    uploader used to bolt a fixed "| Cute & Wholesome #shorts #cute" suffix onto
    every title and re-append the same hashtag block to every description, so
    all 100+ published videos shared an identical metadata fingerprint. Now the
    metadata is computed once, varies per video, and is stored in the manifest.
    """
    return seo.build_metadata(
        core_title=script.title,
        text=script.text,
        keywords=script.keywords,
        seekh=getattr(script, "seekh", ""),
    )


def generate_one(topic=None, index=0):
    """Generate a single reel. Returns a manifest entry dict or None."""
    # 1) Script
    script = gemini_script.generate_script(topic)
    log.info("Script: '%s' (%d words). Hook: %r", script.title, script.word_count, script.hook)

    stamp = _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(script.title)
    base_name = f"{stamp}-{index:02d}-{slug}"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    voice_path = os.path.join(str(OUTPUT_DIR), base_name + ".mp3")
    video_path = os.path.join(str(OUTPUT_DIR), base_name + ".mp4")
    thumb_path = os.path.join(str(OUTPUT_DIR), base_name + ".jpg")

    # 2) Voiceover
    if tts.synthesize(script.text, voice_path) is None:
        log.error("Voiceover synthesis failed; skipping this reel.")
        # Give the topic/hook/voice back so a failed run does not burn them.
        history.discard()
        return None

    # 3) Compose video.
    # NOTE: the on-screen hook is script.screen_hook (2-4 punchy words), NOT
    # script.hook (the long spoken sentence). Rendering a full sentence at
    # 150px was unreadable, which is part of why on-screen text was switched
    # off entirely -- and Shorts watched on mute then had no hook at all.
    try:
        out = video_composer.compose_video(
            voice_path=voice_path,
            text=script.text,
            keywords=script.keywords,
            hook_text=getattr(script, "screen_hook", "") or script.hook,
            flashes=getattr(script, "flashes", None),
            scene_prompts=getattr(script, "scene_prompts", None),
            out_path=video_path,
        )
    except Exception as exc:
        log.exception("Video composition failed (%s).", exc)
        history.discard()
        return None

    # 4) SEO metadata (unique per video).
    meta = _build_seo(script)

    # 5) Thumbnail for the channel grid / subscriptions feed (best-effort).
    thumb = None
    try:
        thumb = thumbnail_mod.generate_thumbnail(
            video_path=out,
            headline=getattr(script, "screen_hook", "") or script.title,
            out_path=thumb_path,
        )
    except Exception as exc:
        log.warning("Thumbnail generation failed (%s); continuing without one.", exc)

    entry = {
        "title": script.title,
        "hook": script.hook,
        "screen_hook": getattr(script, "screen_hook", ""),
        "flashes": list(getattr(script, "flashes", []) or []),
        "seekh": getattr(script, "seekh", ""),
        "scene_prompts": list(getattr(script, "scene_prompts", []) or []),
        "text": script.text,
        "keywords": list(script.keywords),
        "subject": meta["subject"],
        "youtube_title": meta["youtube_title"],
        "youtube_tags": meta["youtube_tags"],
        "hashtags": meta["hashtags"],
        "pinned_comment": meta["pinned_comment"],
        # Kept under the original key so the uploader and any old tooling that
        # reads `description` keeps working unchanged.
        "description": meta["youtube_description"],
        "video_path": os.path.relpath(out, str(BASE_DIR)),
        "voice_path": os.path.relpath(voice_path, str(BASE_DIR)),
        "thumbnail_path": os.path.relpath(thumb, str(BASE_DIR)) if thumb else None,
        "created_utc": stamp,
        "uploaded_youtube": False,
        "youtube_id": None,
        "uploaded_instagram": False,
    }

    # The reel exists, so the topic/hook/voice/flashes it consumed are now
    # permanently spent. Written here (not at pick time) so a run that dies
    # mid-render leaves the rotation untouched.
    history.commit()
    return entry


def run(days=1, per_day=1, limit=None, topic=None):
    """Generate days * per_day reels (optionally capped by limit)."""
    total = max(1, int(days)) * max(1, int(per_day))
    if limit is not None:
        total = min(total, max(1, int(limit)))
    log.info("Generating %d reel(s) (days=%s, per_day=%s, limit=%s).", total, days, per_day, limit)

    manifest = _load_manifest()
    produced = []
    for i in range(total):
        log.info("=== Reel %d/%d ===", i + 1, total)
        entry = generate_one(topic=topic, index=i)
        if entry:
            manifest["reels"].append(entry)
            produced.append(entry)
            _save_manifest(manifest)  # persist after each success
        else:
            log.warning("Reel %d/%d was not produced.", i + 1, total)

    log.info("Done. Produced %d/%d reel(s).", len(produced), total)
    return produced


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate Krishna Universe reels.")
    parser.add_argument("--days", type=int, default=1, help="Number of days to generate for.")
    parser.add_argument("--per-day", type=int, default=1, dest="per_day", help="Reels per day.")
    parser.add_argument("--limit", type=int, default=None, help="Hard cap on total reels.")
    parser.add_argument("--topic", type=str, default=None, help="Optional story topic hint.")
    args = parser.parse_args(argv)

    setup_logging()
    produced = run(days=args.days, per_day=args.per_day, limit=args.limit, topic=args.topic)
    if not produced:
        log.error("No reels were produced.")
        return 1
    print("\nGenerated reels:")
    for e in produced:
        print(f"  - {e.get('youtube_title') or e['title']}")
        print(f"      video     : {e['video_path']}")
        print(f"      subject   : {e.get('subject')}")
        print(f"      hashtags  : {' '.join(e.get('hashtags') or [])}")
        print(f"      pin this  : {e.get('pinned_comment')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
