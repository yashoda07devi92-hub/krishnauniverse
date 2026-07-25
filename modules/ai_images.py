# -*- coding: utf-8 -*-
"""
AI scene-image generation for Krishna Universe Shorts.

Uses Pollinations.ai to turn each narration beat into a cinematic vertical
(1080x1920) frame of the actual leela being told.

WHY THIS REPLACES STOCK FOOTAGE
-------------------------------
The parent pipeline's whole visual layer was Pexels search: the story was about
a puppy, so it searched "puppy playing" and got real footage. That approach has
no equivalent here - there is no video of Krishna lifting Govardhan, and generic
devotional stock clips have nothing to do with the leela being narrated, which
is exactly what makes a mythology channel feel like recycled wallpaper.

So the scenes are generated per beat from the ENGLISH scene prompts that
gemini_script requests in the same call as the narration. Real Pexels footage is
still used, but only for ATMOSPHERE (river, peacock, cows, diya, rain) which the
composer interleaves between these frames - see video_composer._mixed_background.
That mix of generated frames and genuine moving footage is what stops the result
reading as a slideshow.

Fully defensive: on any failure it returns whatever it managed to fetch, and the
composer falls back to atmosphere footage and then a gradient. A video is never
lost because image generation had a bad day.
"""

import logging
import os
import random
import time
import urllib.parse
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeout,
)

from .config import IMAGES_DIR, get_cfg, get_env

log = logging.getLogger("krishna.aiimages")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"

# Appended to every prompt. Pollinations has no dedicated negative-prompt
# parameter, so the exclusions ride along in the prompt text. Text suppression
# matters more here than on most channels: generated Devanagari is always
# malformed, and a frame with garbled Hindi scribbled across it looks broken.
NEGATIVE_HINT = (
    "no text, no watermark, no signature, no letters, no captions, "
    "no distorted faces, no extra limbs"
)


def _requests():
    try:
        import requests

        return requests
    except Exception as exc:
        log.error("'requests' is required for AI images (%s).", exc)
        return None


def _looks_like_image(path):
    try:
        if os.path.getsize(path) < 3000:
            return False
        with open(path, "rb") as fh:
            head = fh.read(12)
        return (
            head[:2] == b"\xff\xd8"                      # JPEG
            or head[:8] == b"\x89PNG\r\n\x1a\n"          # PNG
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        )
    except Exception:
        return False


def _clear_old_images():
    """Remove last run's frames so a partial failure cannot silently reuse them.

    Without this, a run where generation fails would quietly compose yesterday's
    scenes - a genuine repeat, and the one thing this channel must not produce.
    """
    try:
        for fname in os.listdir(str(IMAGES_DIR)):
            if fname.startswith("scene_") and fname.lower().endswith((".jpg", ".png", ".webp")):
                try:
                    os.remove(os.path.join(str(IMAGES_DIR), fname))
                except Exception:
                    pass
    except Exception:
        pass


def _fetch_one(requests, prompt, dest, width, height, seed):
    style = get_cfg("ai_images.style", "")
    full = ", ".join(p for p in (style, str(prompt).strip(), NEGATIVE_HINT) if p)
    url = POLLINATIONS_URL + urllib.parse.quote(full)
    params = {
        "width": width,
        "height": height,
        "nologo": "true",
        "seed": seed,
        "model": get_cfg("ai_images.model", "flux"),
        "referrer": "krishnauniverse",
    }
    # A Pollinations API key (free signup) removes most 429 rate-limiting. On
    # this channel the images ARE the video, so without a key a rate-limited run
    # produces a reel with no Krishna in it at all.
    headers = {}
    token = get_env("POLLINATIONS_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
        params["token"] = token
    else:
        log.warning(
            "POLLINATIONS_TOKEN is not set. Scene images will be rate-limited and "
            "many will fail. Get a free key at https://enter.pollinations.ai"
        )

    attempts = int(get_cfg("ai_images.attempts", 4))
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, params=params, headers=headers,
                              timeout=120, stream=True) as resp:
                if resp.status_code == 429:
                    wait = 5 * attempt
                    log.warning("Pollinations 429 (attempt %d) for %r; waiting %ds",
                                attempt, str(prompt)[:40], wait)
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    log.warning("Pollinations HTTP %s (attempt %d) for %r",
                                resp.status_code, attempt, str(prompt)[:50])
                    time.sleep(2 * attempt)
                    continue
                tmp = dest + ".part"
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
                os.replace(tmp, dest)
            if _looks_like_image(dest):
                return True
            try:
                os.remove(dest)
            except Exception:
                pass
        except Exception as exc:
            log.warning("Pollinations error attempt %d (%s).", attempt, exc)
            time.sleep(2 * attempt)
    return False


def generate_scene_images(scene_prompts, max_images=None):
    """Generate one vertical frame per scene prompt, in parallel.

    Returns local image paths in scene order. May be shorter than the input on
    partial failure, or empty if the service is unreachable.
    """
    if not get_cfg("ai_images.enabled", True):
        return []
    scene_prompts = [s for s in (scene_prompts or []) if s and str(s).strip()]
    if not scene_prompts:
        return []

    requests = _requests()
    if requests is None:
        return []

    if max_images is None:
        max_images = int(get_cfg("ai_images.max_images", 7))
    scene_prompts = scene_prompts[:max_images]

    # Vertical by default - these frames fill a 1080x1920 Short. Generating at
    # 16:9 and cropping (as the longform pipeline does) would cut the top of
    # Krishna's crown and the bottom of the scene on every single frame.
    width = int(get_cfg("ai_images.width", 1080))
    height = int(get_cfg("ai_images.height", 1920))
    workers = max(1, int(get_cfg("ai_images.workers", 4)))
    base_seed = random.randint(1, 9_999_999)

    os.makedirs(str(IMAGES_DIR), exist_ok=True)
    _clear_old_images()

    results = {}

    def _task(i, prompt):
        dest = os.path.join(str(IMAGES_DIR), "scene_%02d.jpg" % i)
        ok = _fetch_one(requests, prompt, dest, width, height, base_seed + i)
        return i, (dest if ok else None)

    t0 = time.time()
    budget = float(get_cfg("ai_images.time_budget_seconds", 240))
    ex = ThreadPoolExecutor(max_workers=workers)
    futures = [ex.submit(_task, i, p) for i, p in enumerate(scene_prompts)]
    done = 0
    try:
        for fut in as_completed(futures, timeout=budget):
            try:
                i, path = fut.result()
            except Exception as exc:
                log.warning("AI image task errored (%s).", exc)
                continue
            done += 1
            if path:
                results[i] = path
                log.info("Scene image ready (%d/%d done).", done, len(scene_prompts))
            else:
                log.warning("Scene image %d failed.", i + 1)
    except FuturesTimeout:
        log.warning("AI image time budget (%.0fs) reached; proceeding with %d image(s).",
                    budget, len(results))
    finally:
        # Never block the whole job on slow or rate-limited requests.
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)

    paths = [results[i] for i in sorted(results.keys())]
    if paths:
        log.info("Generated %d/%d scene image(s) in %.0fs (parallel x%d).",
                 len(paths), len(scene_prompts), time.time() - t0, workers)
    else:
        log.warning("No scene images generated; composer will use atmosphere footage.")
    return paths
