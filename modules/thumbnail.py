"""
Shorts thumbnail generation for Krishna Universe.

WHY: a Short's thumbnail is not shown inside the Shorts player, so it is easy to
assume it does not matter. It does — it is what a viewer sees on the channel's
video grid, in the subscriptions feed, in search results and in the "Shorts from
this channel" shelf. Those are precisely the surfaces where someone who just
enjoyed one video decides whether to subscribe, and subscribers are the metric
this channel is short on (399, needs 1,000).

The channel currently ships no thumbnail at all for Shorts, so YouTube picks an
arbitrary frame — often a blurry mid-motion one. This module picks a good frame
deliberately, boosts it, and stamps a short readable headline on it.

Everything is best-effort: any failure returns None and the upload continues
without a custom thumbnail.
"""

import logging
import os
import random
import shutil
import subprocess

from .config import get_cfg
from . import textrender

log = logging.getLogger("krishna.thumbnail")

# 9:16 to match how Shorts are displayed on the channel grid.
THUMB_W = 1080
THUMB_H = 1920

def _find_font(size):
    """Load a Devanagari-capable font at `size`.

    The font list this replaced was DejaVu and Arial only. Neither contains a
    single Devanagari glyph, so the Hindi caption on every thumbnail would have
    rendered as a row of empty boxes - and silently, since PIL raises nothing
    when a glyph is missing. Resolution is delegated to textrender so the
    thumbnail and the on-screen text can never disagree about which font exists.

    ImageFont.load_default() is deliberately NOT used as a fallback: it is a tiny
    bitmap Latin font, so it would produce an unreadable thumbnail instead of a
    clean image with no caption.
    """
    from PIL import ImageFont

    path = textrender.find_font()
    if not path:
        log.warning("No font available; thumbnail will have no caption.")
        return None
    try:
        return ImageFont.truetype(path, size)
    except Exception as exc:
        log.warning("Could not load thumbnail font %s (%s).", path, exc)
        return None


# --------------------------------------------------------------------------
# Frame extraction
# --------------------------------------------------------------------------
def _probe_duration(video_path):
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30,
        )
        return float((out.stdout or "").strip())
    except Exception:
        return None


def _extract_frame(video_path, out_png):
    """Grab a frame from roughly a third of the way in.

    A third of the way in is chosen because the opening seconds are the hook
    overlay (big text over a punch-zoom) and the closing seconds are the CTA —
    the middle is where the actual cute subject is on screen and settled.
    """
    duration = _probe_duration(video_path)
    seek = 1.5
    if duration and duration > 3:
        seek = round(duration * random.uniform(0.28, 0.42), 2)

    if shutil.which("ffmpeg"):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(seek),
                 "-i", video_path, "-frames:v", "1", "-q:v", "2", out_png],
                capture_output=True, timeout=90, check=True,
            )
            if os.path.exists(out_png) and os.path.getsize(out_png) > 1024:
                return out_png
        except Exception as exc:
            log.warning("ffmpeg frame extraction failed (%s); trying moviepy.", exc)

    # Fallback: moviepy (already a dependency for rendering).
    try:
        from moviepy.editor import VideoFileClip

        clip = VideoFileClip(video_path, audio=False)
        try:
            t = min(seek, max(0.0, (clip.duration or 1.0) - 0.1))
            clip.save_frame(out_png, t=t)
        finally:
            clip.close()
        if os.path.exists(out_png) and os.path.getsize(out_png) > 1024:
            return out_png
    except Exception as exc:
        log.warning("moviepy frame extraction failed (%s).", exc)
    return None


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------
def _fit_cover(img):
    """Scale + centre-crop to exactly THUMB_W x THUMB_H."""
    from PIL import Image

    src_w, src_h = img.size
    scale = max(THUMB_W / float(src_w), THUMB_H / float(src_h))
    new = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    img = img.resize(new, Image.LANCZOS)
    left = (img.size[0] - THUMB_W) // 2
    top = (img.size[1] - THUMB_H) // 2
    return img.crop((left, top, left + THUMB_W, top + THUMB_H))


def _wrap(draw, text, font, max_w):
    words = str(text).split()
    lines = []
    current = ""
    for w in words:
        trial = (current + " " + w).strip()
        try:
            width = draw.textlength(trial, font=font)
        except Exception:
            width = len(trial) * font.size * 0.55
        if width <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines[:3]


def generate_thumbnail(video_path, headline="", out_path=None):
    """Build a 1080x1920 thumbnail from the rendered reel.

    Returns the output path, or None on any failure (never raises).
    """
    if not get_cfg("thumbnail.enabled", True):
        return None
    if not video_path or not os.path.exists(video_path):
        log.warning("Cannot build thumbnail; video missing: %s", video_path)
        return None

    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    except Exception as exc:
        log.warning("Pillow unavailable (%s); skipping thumbnail.", exc)
        return None

    if out_path is None:
        out_path = os.path.splitext(video_path)[0] + ".jpg"
    frame_png = os.path.splitext(out_path)[0] + "-frame.png"

    frame = _extract_frame(video_path, frame_png)
    if not frame:
        log.warning("No frame extracted; skipping thumbnail.")
        return None

    try:
        img = Image.open(frame).convert("RGB")
        img = _fit_cover(img)

        # Make it pop on a crowded grid: a touch more colour, contrast and
        # sharpness than the video itself carries.
        img = ImageEnhance.Color(img).enhance(float(get_cfg("thumbnail.saturation", 1.28)))
        img = ImageEnhance.Contrast(img).enhance(float(get_cfg("thumbnail.contrast", 1.12)))
        img = ImageEnhance.Brightness(img).enhance(float(get_cfg("thumbnail.brightness", 1.06)))
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=110, threshold=3))

        text = str(headline or "").strip()
        if text and bool(get_cfg("thumbnail.text_enabled", True)):
            # Keep it very short: grid tiles are small, long text is noise.
            # No .upper() - Devanagari has no letter case, so it was a silent
            # no-op that only made the code look like it was shouting.
            text = " ".join(text.split()[:4])
            draw = ImageDraw.Draw(img, "RGBA")
            font = _find_font(int(get_cfg("thumbnail.fontsize", 96)))
            if font is not None:
                max_w = int(THUMB_W * 0.86)
                lines = _wrap(draw, text, font, max_w)
                line_h = int(getattr(font, "size", 96) * 1.18)
                block_h = line_h * len(lines)
                # Lower third: keeps the subject's face (usually centred) clear.
                y = int(THUMB_H * 0.70)

                # Soft dark band for guaranteed contrast on bright footage.
                pad = int(line_h * 0.35)
                draw.rectangle(
                    [0, y - pad, THUMB_W, y + block_h + pad],
                    fill=(0, 0, 0, 130),
                )
                for line in lines:
                    try:
                        tw = draw.textlength(line, font=font)
                    except Exception:
                        tw = len(line) * font.size * 0.55
                    x = (THUMB_W - tw) / 2
                    draw.text(
                        (x, y), line, font=font, fill=(255, 255, 255, 255),
                        stroke_width=int(get_cfg("thumbnail.stroke_width", 7)),
                        stroke_fill=(0, 0, 0, 235),
                    )
                    y += line_h

        # YouTube's thumbnail ceiling is 2 MB; quality 88 on a 1080x1920 JPEG
        # lands well under it.
        img.save(out_path, "JPEG", quality=88, optimize=True)
        log.info("Thumbnail written: %s", out_path)
        return out_path
    except Exception as exc:
        log.warning("Thumbnail composition failed (%s).", exc)
        return None
    finally:
        try:
            if os.path.exists(frame_png):
                os.remove(frame_png)
        except Exception:
            pass
