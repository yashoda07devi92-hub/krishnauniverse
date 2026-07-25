"""
Robust Pexels VIDEO fetching for Krishna Universe Katha (LANDSCAPE 16:9).

Design goals (loud + defensive):
  * Detect a missing/blank/placeholder PEXELS_API_KEY early with a clear error.
  * On non-200 responses, log status + reason + a truncated body.
      - 401 / 403 => key invalid: stop retrying.
      - 429       => rate limited: back off.
  * Multi-pass search to maximise landscape footage variety.
  * Cache downloads on disk and validate file magic bytes.
  * Fetch MANY clips (a long story needs lots of scene changes).

stdlib + requests only.
"""

import logging
import os
import random
import time

from .config import CLIPS_DIR, get_cfg, get_env

log = logging.getLogger("krishnakatha.pexels")

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
_MAX_BODY_LOG = 300


def _api_key():
    key = get_env("PEXELS_API_KEY")
    if not key:
        log.error(
            "PEXELS_API_KEY is missing/blank/placeholder. Pexels video will be "
            "skipped; the pipeline will fall back to a gradient background. "
            "Set PEXELS_API_KEY to enable real stock footage."
        )
        return None
    if len(key) < 20:
        log.warning("PEXELS_API_KEY looks unusually short - it may be invalid.")
    return key


def _requests():
    try:
        import requests

        return requests
    except Exception as exc:  # pragma: no cover
        log.error("The 'requests' library is required (%s).", exc)
        return None


def _looks_like_video(path):
    try:
        if os.path.getsize(path) < 10000:
            return False
        with open(path, "rb") as fh:
            head = fh.read(64)
        return b"ftyp" in head or b"moov" in head or b"mdat" in head
    except Exception:
        return False


def _download(url, dest, requests):
    if os.path.exists(dest) and _looks_like_video(dest):
        return True
    for attempt in range(1, 3):
        try:
            with requests.get(url, stream=True, timeout=120) as resp:
                if resp.status_code != 200:
                    log.warning("Download HTTP %s (attempt %d) %s", resp.status_code, attempt, url[:80])
                    time.sleep(1.5 * attempt)
                    continue
                tmp = dest + ".part"
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
                os.replace(tmp, dest)
            if _looks_like_video(dest):
                return True
            try:
                os.remove(dest)
            except Exception:
                pass
        except Exception as exc:
            log.warning("Download error attempt %d (%s).", attempt, exc)
            time.sleep(1.5 * attempt)
    return False


def _pick_landscape_file(video_files):
    """Choose the rendition that fills a 1920x1080 landscape frame as crisply as
    possible (least upscaling), softly preferring true landscape sources and
    Pexels hd/uhd quality tags. Avoids huge 4K files that slow CI / time out.
    """
    target_w, target_h = 1920, 1080
    best, best_score = None, float("-inf")
    for vf in video_files:
        w = vf.get("width") or 0
        h = vf.get("height") or 0
        link = vf.get("link")
        if not link or w <= 0 or h <= 0:
            continue
        scale = max(target_w / float(w), target_h / float(h))
        if scale <= 1.0:
            fit_score = 1000.0 + scale * 100.0  # closest to 1 wins (smallest sufficient)
        else:
            fit_score = 100.0 - (scale - 1.0) * 100.0  # upscaling penalised
        landscape_reward = 30.0 if w >= h else 0.0
        quality = str(vf.get("quality") or "").lower()
        quality_reward = {"uhd": 5.0, "hd": 10.0, "sd": 0.0}.get(quality, 0.0)
        score = fit_score + landscape_reward + quality_reward
        if score > best_score:
            best_score, best = score, link
    return best


def _search(requests, headers, query, per_page, orientation, page=1):
    params = {"query": query, "per_page": per_page, "page": page}
    if orientation:
        params["orientation"] = orientation
    try:
        resp = requests.get(PEXELS_VIDEO_SEARCH, headers=headers, params=params, timeout=30)
    except Exception as exc:
        log.warning("Pexels request error for '%s' (%s).", query, exc)
        return None, False

    if resp.status_code == 200:
        try:
            return resp.json().get("videos", []), False
        except Exception as exc:
            log.warning("Could not parse Pexels JSON for '%s' (%s).", query, exc)
            return [], False

    body = ""
    try:
        body = resp.text[:_MAX_BODY_LOG]
    except Exception:
        pass
    log.error("Pexels search failed: HTTP %s %s | query=%r | body=%s",
              resp.status_code, getattr(resp, "reason", ""), query, body)
    if resp.status_code in (401, 403):
        log.error("Pexels API key invalid/forbidden (HTTP %s). Stopping.", resp.status_code)
        return None, True
    if resp.status_code == 429:
        log.warning("Pexels rate limited (429). Backing off 3s.")
        time.sleep(3)
    return [], False


def fetch_clips(keywords, min_clips=None):
    """Return a list of local mp4 paths of LANDSCAPE footage for the story.

    Uses random page offsets and clears old cached clips each run so footage
    stays fresh and varied between episodes.
    """
    key = _api_key()
    if not key:
        return []
    requests = _requests()
    if requests is None:
        return []

    if min_clips is None:
        min_clips = get_cfg("pexels.min_clips", 22)
    per_page = get_cfg("pexels.per_query", 20)
    orientation = get_cfg("pexels.orientation", "landscape")
    default_keywords = get_cfg("pexels.default_keywords", [])

    headers = {"Authorization": key}
    keywords = [k for k in (keywords or []) if k] or list(default_keywords)

    os.makedirs(CLIPS_DIR, exist_ok=True)
    try:
        for fname in os.listdir(CLIPS_DIR):
            if fname.startswith("pexels_") and fname.endswith(".mp4"):
                try:
                    os.remove(os.path.join(CLIPS_DIR, fname))
                except Exception:
                    pass
    except Exception as exc:
        log.warning("Could not clear clip cache (%s); continuing.", exc)

    collected, seen_ids = [], set()
    passes = [
        ("themed + landscape", keywords, orientation),
        ("themed + any orientation", keywords, None),
        ("default keywords + landscape", default_keywords, orientation),
    ]

    for label, kw_list, orient in passes:
        if len(collected) >= min_clips:
            break
        if not kw_list:
            continue
        log.info("Pexels video pass: %s", label)
        for query in kw_list:
            if len(collected) >= min_clips:
                break
            page = random.randint(1, 6)
            videos, stop_all = _search(requests, headers, query, per_page, orient, page=page)
            if stop_all:
                return collected
            for entry in videos or []:
                if len(collected) >= min_clips:
                    break
                vid_id = entry.get("id")
                if vid_id in seen_ids:
                    continue
                link = _pick_landscape_file(entry.get("video_files", []))
                if not link:
                    continue
                dest = os.path.join(CLIPS_DIR, "pexels_%s.mp4" % vid_id)
                if _download(link, dest, requests):
                    seen_ids.add(vid_id)
                    collected.append(dest)
                    log.info("Got clip %d/%d (page=%d): %s",
                             len(collected), min_clips, page, os.path.basename(dest))

    if not collected:
        log.warning("No Pexels videos collected after all passes.")
    else:
        log.info("Collected %d Pexels clip(s).", len(collected))
    return collected



def fetch_scene_clips(queries, max_clips=None):
    """Fetch ONE landscape clip per scene query, IN ORDER, so the footage
    follows the story beat-by-beat (boy -> river -> old woman -> village ...).
    This is what makes the visuals track the storyline like the reels do.

    Returns an ordered list of local mp4 paths (skips a scene if nothing found).
    """
    key = _api_key()
    if not key:
        return []
    requests = _requests()
    if requests is None:
        return []

    orientation = get_cfg("pexels.orientation", "landscape")
    per_page = get_cfg("pexels.per_query", 20)
    headers = {"Authorization": key}
    queries = [q for q in (queries or []) if q and str(q).strip()]
    if max_clips:
        queries = queries[: int(max_clips)]
    if not queries:
        return []

    os.makedirs(CLIPS_DIR, exist_ok=True)
    # Clear old cached clips so every run is fresh.
    try:
        for fname in os.listdir(CLIPS_DIR):
            if fname.startswith("pexels_") and fname.endswith(".mp4"):
                try:
                    os.remove(os.path.join(CLIPS_DIR, fname))
                except Exception:
                    pass
    except Exception:
        pass

    collected, seen = [], set()
    for idx, query in enumerate(queries):
        got = False
        for orient in (orientation, None):  # themed+landscape, then any orientation
            page = random.randint(1, 3)
            videos, stop_all = _search(requests, headers, str(query), per_page, orient, page=page)
            if stop_all:
                return collected
            for entry in videos or []:
                vid_id = entry.get("id")
                if vid_id in seen:
                    continue
                link = _pick_landscape_file(entry.get("video_files", []))
                if not link:
                    continue
                dest = os.path.join(CLIPS_DIR, "pexels_%s.mp4" % vid_id)
                if _download(link, dest, requests):
                    seen.add(vid_id)
                    collected.append(dest)
                    got = True
                    log.info("Scene %d clip: %r -> %s", idx + 1, str(query)[:40], os.path.basename(dest))
                    break
            if got:
                break
        if not got:
            log.warning("No footage for scene %d: %r", idx + 1, str(query)[:40])
    log.info("Collected %d scene-matched clip(s).", len(collected))
    return collected
