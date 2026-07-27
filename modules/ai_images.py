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
from . import history

log = logging.getLogger("krishna.aiimages")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"

# Chosen once per run and reused for every scene in that reel. Two competing
# requirements meet here:
#   - WITHIN one reel every frame must share a look, or the 16 cuts read as a
#     random image dump instead of one video.
#   - ACROSS reels the look must MOVE, or the channel grid becomes five near
#     identical golden-god-ray tiles a day. That was the owner's actual
#     complaint: "सारे बैनर एक जैसे, लगता है सबने पेंटिंग कर दी हो."
# A single global style string satisfied the first and caused the second.
_run_style = None

# Appended to every prompt. Pollinations has no dedicated negative-prompt
# parameter, so the exclusions ride along in the prompt text. Text suppression
# matters more here than on most channels: generated Devanagari is always
# malformed, and a frame with garbled Hindi scribbled across it looks broken.
NEGATIVE_HINT = (
    "no text, no watermark, no signature, no letters, no captions, "
    "no distorted faces, no extra limbs"
)


def _pick_run_style(force_new=False):
    """Resolve the visual style for this reel.

    ai_images.style is the constant part (the palette and the subject matter that
    make the channel recognisable). ai_images.style_variants supplies the part
    that changes per reel - lens, time of day, camera height - drawn through
    history so consecutive uploads cannot land on the same one.
    """
    global _run_style
    if _run_style is not None and not force_new:
        return _run_style
    base = str(get_cfg("ai_images.style", "") or "").strip()
    variants = [v for v in (get_cfg("ai_images.style_variants", []) or []) if str(v).strip()]
    variant = ""
    if variants:
        variant = history.pick("image_styles", variants) or variants[0]
    _run_style = ", ".join(p for p in (base, variant) if p)
    if variant:
        log.info("Visual variant for this reel: %s", variant)
    return _run_style


def _reset_run_style():
    """Force the next reel in a batch to draw its own variant."""
    global _run_style
    _run_style = None


def _requests():
    try:
        import requests

        return requests
    except Exception as exc:
        log.error("'requests' is required for AI images (%s).", exc)
        return None


def _postprocess(path, target_w, target_h):
    """Upscale to the size the motion engine needs, and sharpen.

    TWO PROBLEMS THIS SOLVES
    ------------------------
    1. STRETCHING. Images were requested at 1080x1920 - 2.07 megapixels at a
       0.5625 aspect. Diffusion models are trained on roughly 1 megapixel
       "buckets", and pushing both the pixel count and an extreme aspect past
       that is what distorts anatomy: wide faces, broad bodies. Generating in a
       native bucket instead (see ai_images.width/height) keeps proportions
       correct.

    2. SOFTNESS. The motion engine works on an OVERSCANNED frame so it has room
       to pan, so the image gets upscaled either way. Letting moviepy do it
       applies a plain bilinear resize per frame, which looks mushy. Doing it
       ONCE here with LANCZOS plus an unsharp mask is both sharper and cheaper -
       the per-frame path then has nothing left to scale.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except Exception as exc:
        log.info("Pillow unavailable (%s); skipping upscale/sharpen.", exc)
        return

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            src_w, src_h = img.size

            # Cover the target without distorting: scale by the larger ratio,
            # then centre-crop the overflow.
            scale = max(target_w / float(src_w), target_h / float(src_h))
            new_w = max(1, int(round(src_w * scale)))
            new_h = max(1, int(round(src_h * scale)))
            img = img.resize((new_w, new_h), Image.LANCZOS)

            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            img = img.crop((left, top, left + target_w, top + target_h))

            # Unsharp after upscaling, not before - sharpening then enlarging
            # just enlarges the halos.
            amount = float(get_cfg("ai_images.sharpen_percent", 130))
            if amount > 0:
                img = img.filter(ImageFilter.UnsharpMask(
                    radius=2, percent=int(amount), threshold=3))

            contrast = float(get_cfg("ai_images.contrast", 1.06))
            saturation = float(get_cfg("ai_images.saturation", 1.08))
            if contrast != 1.0:
                img = ImageEnhance.Contrast(img).enhance(contrast)
            if saturation != 1.0:
                img = ImageEnhance.Color(img).enhance(saturation)

            img.save(path, "JPEG", quality=95, subsampling=0)
        log.info("Scene image %dx%d -> %dx%d, sharpened.",
                 src_w, src_h, target_w, target_h)
    except Exception as exc:
        log.warning("Upscale/sharpen failed for %s (%s); using as-is.", path, exc)


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


def _fetch_one(requests, prompt, dest, width, height, seed, style=None):
    style = _pick_run_style() if style is None else style
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


def generate_thumbnail_image(prompt, dest, target_w=None, target_h=None):
    """Generate ONE dedicated image for the channel-grid thumbnail.

    WHY THE THUMBNAIL GETS ITS OWN GENERATION
    -----------------------------------------
    The thumbnail used to be a frame grabbed out of the finished MP4. Every
    degradation in the pipeline was therefore baked into the single image that
    decides whether anyone clicks:

      * the frame is a crop from a still that was upscaled to overscan size and
        is mid-pan, so it is the softest moment of that shot;
      * the moving grain layer (grain.opacity) sits on top of it, which is
        correct for 30fps video and is just noise in a static JPEG;
      * the warm grade has already been applied, so the thumbnail's own
        saturation boost was a second pass on top of a first;
      * and all of it survived an x264 encode at crf 16 before being re-encoded
        as JPEG.
    Four lossy steps, then sharpening applied to the result - which is exactly
    what makes an image look like a smeared painting.

    Generating one purpose-built frame instead costs a single extra API call and
    skips all four. The prompt is also composed differently: a thumbnail is read
    at about 250px wide on a phone grid, so it needs one large subject and an
    uncluttered background, not a wide cinematic composition with seven things in
    it.

    Returns the path on success, None on any failure (never raises).
    """
    if not get_cfg("ai_images.enabled", True):
        return None
    prompt = str(prompt or "").strip()
    if not prompt:
        return None

    requests = _requests()
    if requests is None:
        return None

    width = int(get_cfg("thumbnail.hero_width", 1024))
    height = int(get_cfg("thumbnail.hero_height", 1792))

    # Composition rules for a 250px-wide tile, appended to the scene's own
    # description so the picture still matches the video.
    framing = str(get_cfg(
        "thumbnail.hero_framing",
        "close up portrait composition, single clear subject filling the frame, "
        "expressive face, simple uncluttered background, strong rim light, "
        "high micro detail, tack sharp focus",
    ) or "").strip()
    style = ", ".join(p for p in (_pick_run_style(), framing) if p)

    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    seed = random.randint(1, 9_999_999)
    ok = _fetch_one(requests, prompt, dest, width, height, seed, style=style)
    if not ok:
        log.warning("Dedicated thumbnail image failed; falling back to a scene image.")
        return None

    if target_w and target_h:
        _postprocess(dest, int(target_w), int(target_h))
    log.info("Dedicated thumbnail image ready: %s", dest)
    return dest


def scene_image_paths():
    """Existing scene frames for this run, in order. Used by the thumbnail.

    These are the images BEFORE they were animated and encoded, saved at JPEG
    quality 95 with no chroma subsampling, so they are by a wide margin the
    sharpest version of the reel's visuals that exists on disk.
    """
    try:
        names = sorted(
            f for f in os.listdir(str(IMAGES_DIR))
            if f.startswith("scene_") and f.lower().endswith(".jpg")
        )
    except Exception:
        return []
    return [os.path.join(str(IMAGES_DIR), n) for n in names]


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

    # Requested at a NATIVE diffusion bucket (~1-1.8 MP), not at the final frame
    # size. Asking for 1080x1920 (2.07 MP) produced visibly stretched figures -
    # wide faces, broad bodies - because that is well past the resolution the
    # model was trained on. _postprocess() then upscales and sharpens to the
    # size the motion engine actually needs.
    width = int(get_cfg("ai_images.width", 1080))
    height = int(get_cfg("ai_images.height", 1920))
    workers = max(1, int(get_cfg("ai_images.workers", 4)))
    base_seed = random.randint(1, 9_999_999)

    os.makedirs(str(IMAGES_DIR), exist_ok=True)
    _clear_old_images()

    # Draw this reel's variant ONCE, here, before any worker starts. Chosen at
    # this point rather than lazily inside _fetch_one because four threads calling
    # a lazy initialiser would race and could hand different scenes different
    # looks. It is deliberately NOT reset afterwards: the thumbnail is generated
    # later in the run and must match the frames the viewer is about to see.
    _reset_run_style()
    _pick_run_style()

    results = {}

    # The motion engine pans across an OVERSCANNED frame, so deliver the image
    # at that size already sharpened rather than letting moviepy upscale it on
    # every frame.
    over = float(get_cfg("motion.overscan", 1.18))
    tw = int(int(get_cfg("video.width", 1080)) * over)
    th = int(int(get_cfg("video.height", 1920)) * over)
    tw += tw % 2
    th += th % 2

    def _task(i, prompt):
        dest = os.path.join(str(IMAGES_DIR), "scene_%02d.jpg" % i)
        ok = _fetch_one(requests, prompt, dest, width, height, base_seed + i)
        if ok:
            _postprocess(dest, tw, th)
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
