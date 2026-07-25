#!/usr/bin/env python3
"""
Krishna Universe Katha - daily moral-story video generation pipeline (CLI).

End-to-end, defensive pipeline that, for each episode:
  1. Generates a ~5-7 minute moral story (Gemini -> stories.json fallback) with
     a strong hook, retention beats and a clear moral.
  2. Synthesizes a warm USA storyteller voiceover (edge-tts -> gTTS fallback),
     chunked for reliability on long text.
  3. Builds a 1920x1080 HD video: scene-switching Pexels footage, an intro
     title card, full-length readable captions, soft music, and an outro CTA.
  4. Generates a bold thumbnail.
  5. Records everything in manifest.json so the uploader can post later.

Usage:
  python generate.py                 # one episode (the scheduled default)
  python generate.py --count 2       # a small batch
  python generate.py --lesson honesty --topic "a child finds a lost wallet"
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys

from modules import config as config_mod
from modules.config import OUTPUT_DIR, BASE_DIR, get_cfg, setup_logging
from modules import story as story_mod
from modules import tts
from modules import video_composer
from modules import ai_images as ai_images_mod
from modules import pexels_video as pexels_mod
from modules import history
from modules import seo
from modules import thumbnail as thumb_mod

log = logging.getLogger("krishna.generate")

MANIFEST_PATH = os.path.join(str(BASE_DIR), "manifest.json")

# A short, representative story used ONLY for fast/cheap test renders. It shows
# the exact LOOK (footage, captions, intro/outro, voice, grade) in ~1 minute so
# testing burns almost no GitHub Actions minutes.
_TEST_STORY_TEXT = (
    "Would you give back gold that wasn't yours? A poor woodcutter once dropped "
    "his only axe into a deep river. As he wept, a shining spirit rose holding an "
    "axe of pure gold. Is this yours, she asked. No, he said, mine was just old "
    "iron. Pleased by his honesty, the spirit gave him the gold axe too. The moral "
    "of the story is that honesty is always rewarded. "
)


def _make_test_story():
    cta = get_cfg("channel.cta", "Subscribe for a new moral story every day!")
    return story_mod.Story(
        title="Test: The Honest Woodcutter",
        text=_TEST_STORY_TEXT + cta,
        hook="Would you give back gold that wasn't yours?",
        moral="The moral of the story is that honesty is always rewarded.",
        keywords=["forest river sunlight", "old man working outdoor", "calm water nature"],
    )


def _slugify(text, max_len=40):
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in (" ", "-", "_"):
            keep.append("-")
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "moraltale")[:max_len]


def _load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("episodes"), list):
            return data
    except Exception:
        pass
    return {"episodes": []}


def _save_manifest(manifest):
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        log.info("Manifest updated: %s (%d episode(s)).", MANIFEST_PATH, len(manifest["episodes"]))
    except Exception as exc:
        log.error("Could not write manifest (%s).", exc)


def _media_duration(path):
    """Best-effort duration in seconds for a rendered file (None on failure).

    Needed so build_chapters() can place real timestamps rather than guesses.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        from moviepy.editor import AudioFileClip

        clip = AudioFileClip(path)
        try:
            return float(clip.duration or 0) or None
        finally:
            clip.close()
    except Exception as exc:
        log.warning("Could not probe duration of %s (%s).", path, exc)
        return None


def _build_seo(story, duration_seconds):
    """Build the YouTube metadata bundle for this episode.

    Replaces the old _build_description(), which produced the same four blocks
    for every upload, carried no search anchor in the title, had no chapters, and
    welcomed viewers to a brand name that did not match the channel.
    """
    return seo.build_metadata(story, duration_seconds=duration_seconds)


def _scene_queries(story):
    """Build one short, Pexels-friendly search phrase per story scene so the
    footage matches the character/subject of each beat (boy, dog, river...).
    Falls back to the story's keywords if no scenes are available."""
    queries = []
    for s in (getattr(story, "scenes", None) or []):
        words = str(s).strip().split()
        if not words:
            continue
        # First ~6 words usually carry the subject ("a poor young boy crying ...").
        phrase = " ".join(words[:6])
        queries.append(phrase)
    if not queries:
        queries = list(story.keywords or [])
    return queries


def generate_one(lesson=None, topic=None, index=0, test=False):
    """Generate a single episode. Returns a manifest entry dict or None.

    When test=True a short fixed story is used and footage is limited, so the
    full pipeline (voice + footage + render + thumbnail) runs in ~1 minute to
    verify the LOOK without burning GitHub Actions minutes.
    """
    # 1) Story
    if test:
        story = _make_test_story()
        # Fewer clips + no long render in test mode.
        try:
            config_mod.cfg.setdefault("pexels", {})["min_clips"] = 6
        except Exception:
            pass
        log.info("TEST MODE: short story, reduced footage.")
    else:
        story = story_mod.generate_story(lesson, topic)
    log.info("Story: '%s' (%d words). Hook: %r", story.title, story.word_count, story.hook)

    stamp = _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    base_name = f"{stamp}-{index:02d}-{_slugify(story.title)}"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    voice_path = os.path.join(str(OUTPUT_DIR), base_name + ".mp3")
    video_path = os.path.join(str(OUTPUT_DIR), base_name + ".mp4")
    thumb_path = os.path.join(str(OUTPUT_DIR), base_name + ".jpg")

    # 2) Voiceover
    if tts.synthesize(story.text, voice_path) is None:
        log.error("Voiceover synthesis failed; skipping this episode.")
        # Hand the topic seed and sign-off back so a failed run does not burn them.
        history.discard()
        return None

    # 2b) AI scene images. Prepend the fixed main-character description to each
    # scene so the SAME character appears across all scenes (consistency).
    try:
        max_imgs = 4 if test else None
        char = (getattr(story, "main_character", "") or "").strip()
        scene_prompts = story.scenes
        if char:
            scene_prompts = [f"{char}. {s}" for s in story.scenes]
        image_paths = ai_images_mod.generate_scene_images(scene_prompts, max_images=max_imgs)
    except Exception as exc:
        log.warning("AI image generation errored (%s); using stock footage.", exc)
        image_paths = []

    # If too few AI images came back (e.g. the free image service rate-limited
    # us), DON'T stretch 2 images across a 5-min video - that looks terrible.
    # Drop them so the composer uses real Pexels footage that changes per scene.
    # If too few AI images came back we still keep them - they'll be MIXED with
    # scene footage below so the character appears while footage adds variety.

    # 2c) Always fetch SCENE-MATCHED footage too, so we can mix it with the AI
    # character images (varied, non-repeating, story-following visuals).
    clip_paths = []
    if not test:
        try:
            queries = _scene_queries(story)
            clip_paths = pexels_mod.fetch_scene_clips(queries, max_clips=12)
        except Exception as exc:
            log.warning("Scene footage fetch errored (%s).", exc)
            clip_paths = []

    # 3) Compose video (composer mixes images + footage when both exist)
    try:
        out = video_composer.compose_video(
            voice_path=voice_path,
            text=story.text,
            keywords=story.keywords,
            title=story.title,
            hook_text=story.hook,
            out_path=video_path,
            image_paths=image_paths,
            clip_paths=clip_paths,
        )
    except Exception as exc:
        log.exception("Video composition failed (%s).", exc)
        history.discard()
        return None

    # 4) Thumbnail (best-effort)
    thumb = thumb_mod.generate_thumbnail(story.title, story.hook, out_path=thumb_path)

    # 5) SEO metadata. Chapter timestamps are derived from the real narration
    # length, so probe the voiceover rather than trusting the config target.
    meta = _build_seo(story, _media_duration(voice_path))

    entry = {
        "title": story.title,
        "hook": story.hook,
        "moral": story.moral,
        "text": story.text,
        "keywords": list(story.keywords),
        "youtube_title": meta["youtube_title"],
        "youtube_tags": meta["youtube_tags"],
        "hashtags": meta["hashtags"],
        "description": meta["youtube_description"],
        "video_path": os.path.relpath(out, str(BASE_DIR)),
        "voice_path": os.path.relpath(voice_path, str(BASE_DIR)),
        "thumbnail_path": os.path.relpath(thumb, str(BASE_DIR)) if thumb else None,
        "created_utc": stamp,
        "uploaded_youtube": False,
        "youtube_id": None,
    }

    # The episode exists, so the topic seed and sign-off it consumed are now
    # permanently spent. Written here rather than at pick time so a run that
    # dies mid-render leaves the rotation untouched.
    history.commit()
    return entry


def run(count=1, lesson=None, topic=None, test=False):
    count = max(1, int(count))
    log.info("Generating %d episode(s).%s", count, " [TEST MODE]" if test else "")
    manifest = _load_manifest()
    produced = []
    for i in range(count):
        log.info("=== Episode %d/%d ===", i + 1, count)
        entry = generate_one(lesson=lesson, topic=topic, index=i, test=test)
        if entry:
            manifest["episodes"].append(entry)
            produced.append(entry)
            _save_manifest(manifest)
        else:
            log.warning("Episode %d/%d was not produced.", i + 1, count)
    log.info("Done. Produced %d/%d episode(s).", len(produced), count)
    return produced


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate Krishna Universe long-form videos.")
    parser.add_argument("--count", type=int, default=1, help="Number of episodes to generate.")
    parser.add_argument("--lesson", type=str, default=None, help="Optional moral/lesson hint.")
    parser.add_argument("--topic", type=str, default=None, help="Optional story topic hint.")
    parser.add_argument("--test", action="store_true",
                        help="Fast cheap render: short fixed story + reduced footage (verifies the look).")
    args = parser.parse_args(argv)

    setup_logging()
    produced = run(count=args.count, lesson=args.lesson, topic=args.topic, test=args.test)
    if not produced:
        log.error("No episodes were produced.")
        return 1
    print("\nGenerated episodes:")
    for e in produced:
        print(f"  - {e['title']}  ->  {e['video_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
