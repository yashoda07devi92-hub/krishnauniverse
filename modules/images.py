"""
Image fetching for Krishna Universe: Pexels PHOTOS and keyless Picsum images.

Both return lists of local file paths and are used by the video composer to
build Ken-Burns backgrounds when no Pexels video footage is available.

stdlib + requests + Pillow only.
"""

# ---------------------------------------------------------------------------
# Pillow >= 10 removed Image.ANTIALIAS (and friends) which moviepy 1.0.3 and
# our own resizing rely on. Re-add the constants at import time so the rest of
# the module is safe regardless of the installed Pillow version.
# ---------------------------------------------------------------------------
try:
    from PIL import Image as _PILImage
    if not hasattr(_PILImage, "ANTIALIAS"):
        _PILImage.ANTIALIAS = _PILImage.Resampling.LANCZOS
    for _n in ("BILINEAR", "BICUBIC", "NEAREST", "LANCZOS", "HAMMING", "BOX"):
        if not hasattr(_PILImage, _n) and hasattr(_PILImage, "Resampling"):
            setattr(_PILImage, _n, getattr(_PILImage.Resampling, _n))
except Exception:
    pass

import hashlib
import logging
import os
import time

from .config import CACHE_DIR, IMAGES_DIR, get_cfg, get_env

log = logging.getLogger("krishna.images")

PEXELS_PHOTO_SEARCH = "https://api.pexels.com/v1/search"
PICSUM_URL = "https://picsum.photos/seed/{seed}/1080/1920"

_MAX_BODY_LOG = 300

# Magic bytes for common image formats.
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_GIF = (b"GIF87a", b"GIF89a")
_WEBP_RIFF = b"RIFF"


def _requests():
    try:
        import requests

        return requests
    except Exception as exc:
        log.error("The 'requests' library is required (%s).", exc)
        return None


def _is_valid_image(path):
    """Validate image by magic bytes (no full decode needed)."""
    try:
        if os.path.getsize(path) < 1024:
            return False
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(_JPEG):
            return True
        if head.startswith(_PNG):
            return True
        if any(head.startswith(sig) for sig in _GIF):
            return True
        if head.startswith(_WEBP_RIFF) and b"WEBP" in head:
            return True
        return False
    except Exception:
        return False


def _download(url, dest, requests, headers=None):
    if os.path.exists(dest) and _is_valid_image(dest):
        log.info("Using cached image: %s", os.path.basename(dest))
        return True
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=headers or {}, stream=True, timeout=45)
            if resp.status_code != 200:
                body = ""
                try:
                    body = resp.text[:_MAX_BODY_LOG]
                except Exception:
                    pass
                log.warning(
                    "Image download HTTP %s %s (attempt %d) url=%s body=%s",
                    resp.status_code,
                    getattr(resp, "reason", ""),
                    attempt,
                    url[:80],
                    body,
                )
                if resp.status_code in (401, 403):
                    return False
                time.sleep(1.2 * attempt)
                continue
            tmp = dest + ".part"
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 15):
                    if chunk:
                        fh.write(chunk)
            os.replace(tmp, dest)
            if _is_valid_image(dest):
                return True
            log.warning("Downloaded image failed validation: %s", dest)
            try:
                os.remove(dest)
            except Exception:
                pass
        except Exception as exc:
            log.warning("Image download error attempt %d (%s).", attempt, exc)
            time.sleep(1.2 * attempt)
    return False


# --------------------------------------------------------------------------
# Pexels photos
# --------------------------------------------------------------------------
def fetch_pexels_photos(keywords, min_images=None):
    """Return local file paths for Pexels portrait photos matching keywords.

    Returns [] if PEXELS_API_KEY is missing/invalid or nothing was found.
    """
    key = get_env("PEXELS_API_KEY")
    if not key:
        log.warning("PEXELS_API_KEY not set - skipping Pexels photos.")
        return []
    requests = _requests()
    if requests is None:
        return []

    if min_images is None:
        min_images = get_cfg("pexels.min_images", 6)
    per_page = get_cfg("pexels.per_query", 15)
    default_keywords = get_cfg("pexels.default_keywords", [])
    keywords = [k for k in (keywords or []) if k] or list(default_keywords)

    headers = {"Authorization": key}
    os.makedirs(IMAGES_DIR, exist_ok=True)
    collected = []
    seen = set()

    passes = [
        ("themed + portrait", keywords, "portrait"),
        ("themed + any", keywords, None),
        ("defaults + any", default_keywords, None),
    ]

    for label, kw_list, orientation in passes:
        if len(collected) >= min_images:
            break
        if not kw_list:
            continue
        log.info("Pexels photo pass: %s", label)
        for query in kw_list:
            if len(collected) >= min_images:
                break
            params = {"query": query, "per_page": per_page}
            if orientation:
                params["orientation"] = orientation
            try:
                resp = requests.get(PEXELS_PHOTO_SEARCH, headers=headers, params=params, timeout=30)
            except Exception as exc:
                log.warning("Pexels photo request error '%s' (%s).", query, exc)
                continue
            if resp.status_code != 200:
                body = ""
                try:
                    body = resp.text[:_MAX_BODY_LOG]
                except Exception:
                    pass
                log.error(
                    "Pexels photo search HTTP %s %s query=%r body=%s",
                    resp.status_code,
                    getattr(resp, "reason", ""),
                    query,
                    body,
                )
                if resp.status_code in (401, 403):
                    return collected
                if resp.status_code == 429:
                    time.sleep(3)
                continue
            try:
                photos = resp.json().get("photos", [])
            except Exception:
                photos = []
            for photo in photos:
                if len(collected) >= min_images:
                    break
                pid = photo.get("id")
                if pid in seen:
                    continue
                src = photo.get("src", {})
                # Prefer the HIGHEST-res source so Ken-Burns does not upscale a
                # small image into blur: original > large2x > portrait > large.
                link = (
                    src.get("original")
                    or src.get("large2x")
                    or src.get("portrait")
                    or src.get("large")
                )
                if not link:
                    continue
                dest = os.path.join(IMAGES_DIR, "pexels_%s.jpg" % pid)
                if _download(link, dest, requests, headers=None):
                    seen.add(pid)
                    collected.append(dest)
                    log.info("Got photo %d/%d: %s", len(collected), min_images, os.path.basename(dest))

    if collected:
        log.info("Collected %d Pexels photo(s).", len(collected))
    else:
        log.warning("No Pexels photos collected.")
    return collected


# --------------------------------------------------------------------------
# Picsum (keyless safety net)
# --------------------------------------------------------------------------
def fetch_picsum_images(keywords, count=None):
    """Return local file paths for keyless Picsum images (1080x1920).

    Picsum requires no API key, making this the guaranteed no-key safety net.
    Keywords are only used to derive stable, varied seeds.
    """
    requests = _requests()
    if requests is None:
        return []
    if count is None:
        count = get_cfg("pexels.min_images", 6)
    count = max(1, int(count))

    os.makedirs(IMAGES_DIR, exist_ok=True)
    base = "-".join(keywords) if keywords else "krishna"
    collected = []

    for i in range(count):
        raw = f"{base}-{i}-{int(time.time() // 3600)}"
        seed = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
        url = PICSUM_URL.format(seed=seed)
        dest = os.path.join(IMAGES_DIR, "picsum_%s.jpg" % seed)
        if _download(url, dest, requests):
            collected.append(dest)
            log.info("Got Picsum image %d/%d: %s", len(collected), count, os.path.basename(dest))

    if collected:
        log.info("Collected %d Picsum image(s) (keyless safety net).", len(collected))
    else:
        log.warning("No Picsum images collected.")
    return collected
