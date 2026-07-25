# -*- coding: utf-8 -*-
"""
AI scene-image generation for Krishna Universe Shorts (vertical 9:16).

WHY THIS IS THE PRIMARY VISUAL SOURCE HERE
------------------------------------------
The pipeline this was ported from built its background out of Pexels stock
VIDEO: search "puppy playing", get real moving footage. That approach cannot
work for this channel, because there is no stock footage of Krishna, Vrindavan
or Kurukshetra anywhere. Searching Pexels for "krishna" returns unrelated
photographs of people.

So the character frames are generated per-scene from the SAME model output that
wrote the narration (see gemini_script: `scene_prompts`), and real Pexels
footage is demoted to atmosphere cutaways between them -- river water, peacocks,
lamp flames, monsoon rain. That mix is what stops the reel reading as a
slideshow; see video_composer._mixed_background.

Generated with Pollinations.ai. A free API token (POLLINATIONS_TOKEN) massively
reduces 429 rate-limiting; without it most requests fail and the reel would fall
back to plain atmosphere footage with no Krishna in it at all, so the token is
effectively required for this channel rather than optional.

Fully defensive: on ANY failure it returns whatever it managed to fetch. The
video never fails because of this module.

stdlib + requests only.
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

# Appended to every prompt. Two jobs:
#   1) hold one consistent art direction across the whole channel, so a viewer
#      recognises the look in the feed before they read the title;
#   2) suppress text. Diffusion models love to paint garbled pseudo-Devanagari
#      into the frame, and a Hindi-looking scribble on a devotional video looks
#      worse than no text at all.
NEGATIVE_SUFFIX = (
    "no text, no words, no letters, no watermark, no signature, no caption, "
    "no frame border, single coherent scene"
)


def _requests():
    try:
        import requests

        return requests
    except Exception as exc:  # pragma: no cover
        log.error("'requests' is required for AI images (%s).", exc)
        return None


def _looks_like_image(path):
    try:
        if os.path.getsize(path) < 3000:
            return False
        with open(path, "rb") as fh:
            head = fh.read(12)
        return (
            head[:2] == b"\xff\xd8"                       # JPEG
            or head[:8] == b"\x89PNG\r\n\x1a\n"           # PNG
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        )
    except Exception:
        return False


def _clear_old_images():
    """Remove last run's frames so a partial failure cannot silently reuse
    yesterday's pictures under today's narration."""
    try:
        for fname in os.listdir(IMAGES_DIR):
            if fname.startswith("scene_") and fname.lower().endswith((".jpg", ".png", ".webp")):
                try:
                    os.remove(os.path.join(IMAGES_DIR, fname))
                except Exception:
                    pass
    except Exception:
        pass


def _full_prompt(prompt):
    style = get_cfg(
        "ai_images.style",
        "cinematic devotional Indian art, richly detailed painterly realism, "
        "warm golden hour light, volumetric god rays, deep saturated colours, "
        "ornate traditional Indian clothing and jewellery, 85mm depth of field",
    )
    return "%s, %s, %s" % (str(prompt).strip(), style, NEGATIVE_SUFFIX)


def _fetch_one(requests, prompt, dest, width, height, seed):
    url = POLLINATIONS_URL + urllib.parse.quote(_full_prompt(prompt))
    params = {
        "width": width,
        "height": height,
        "nologo": "true",
        "seed": seed,
        "model": get_cfg("ai_images.model", "flux"),
        "referrer": "krishnauniverse",
    }
    headers = {}
    token = get_env("POLLINATIONS_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
        params["token"] = token
    else:
        log.warning(
            "POLLINATIONS_TOKEN is not set. Krishna frames are the whole visual "
            "on this channel, and without a token most requests get 429'd."
        )

    attempts = max(1, int(get_cfg("ai_images.attempts", 3)))
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, params=params, headers=headers,
                              timeout=90, stream=True) as resp:
                if resp.status_code == 429:
                    wait = 5 * attempt
                    log.warning("Pollinations 429 (attempt %d) for %r; waiting %ds",
                                attempt, prompt[:40], wait)
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    log.warning("Pollinations HTTP %s (attempt %d) for %r",
                                resp.status_code, attempt, prompt[:50])
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

    Returns local image paths IN SCENE ORDER (possibly shorter than the input on
    partial failure, or empty if the service is unavailable). Order matters: the
    frames are shown in narration order, so an out-of-order list would show the
    ending while the opening line is still being spoken.
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
        max_images = int(get_cfg("ai_images.max_images", 6))
    scene_prompts = scene_prompts[:max_images]

    width = int(get_cfg("ai_images.width", 1080))
    height = int(get_cfg("ai_images.height", 1920))
    workers = max(1, int(get_cfg("ai_images.workers", 3)))
    # One seed family per run keeps the frames of a single reel visually
    # consistent with each other while still differing between reels.
    base_seed = random.randint(1, 9_999_999)

    os.makedirs(IMAGES_DIR, exist_ok=True)
    _clear_old_images()

    results = {}

    def _task(i, prompt):
        dest = os.path.join(str(IMAGES_DIR), "scene_%02d.jpg" % i)
        ok = _fetch_one(requests, prompt, dest, width, height, base_seed + i)
        return i, (dest if ok else None)

    t0 = time.time()
    budget = float(get_cfg("ai_images.time_budget_seconds", 150))
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
                log.info("AI frame ready (%d/%d done).", done, len(scene_prompts))
            else:
                log.warning("AI frame %d failed.", i + 1)
    except FuturesTimeout:
        log.warning("AI image budget (%.0fs) reached; proceeding with %d frame(s).",
                    budget, len(results))
    finally:
        # Never block the whole job on slow / rate-limited image requests: a reel
        # with four frames published on time beats six frames published late.
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)

    paths = [results[i] for i in sorted(results.keys())]
    if paths:
        log.info("Generated %d/%d AI frame(s) in %.0fs (parallel x%d).",
                 len(paths), len(scene_prompts), time.time() - t0, workers)
    else:
        log.error(
            "No AI frames generated. The reel will fall back to atmosphere "
            "footage only, which means it will contain no Krishna imagery. "
            "Check POLLINATIONS_TOKEN."
        )
    return paths
