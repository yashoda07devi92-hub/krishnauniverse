"""
Shorts thumbnail generation for Krishna Universe.

WHY IT MATTERS
--------------
A Short's thumbnail is not shown inside the Shorts player, so it is easy to
assume it does not matter. It does - it is what a viewer sees on the channel's
video grid, in the subscriptions feed, in search results and in the "Shorts from
this channel" shelf. Those are precisely the surfaces where someone who just
enjoyed one video decides whether to subscribe.

WHY THIS WAS REWRITTEN
----------------------
The first version grabbed a frame out of the finished MP4. That put every lossy
step in the pipeline into the one image that decides whether anyone clicks:

    generated still  ->  upscaled to overscan (motion.overscan)
                     ->  cropped mid-pan (the softest instant of the shot)
                     ->  warm grade applied
                     ->  moving grain layer applied (correct for video, pure
                         noise in a static JPEG)
                     ->  x264 encode at crf 16
                     ->  extracted, re-sharpened, re-encoded as JPEG q88

Sharpening the end of that chain does not recover detail, it amplifies what the
encoder left behind - which is exactly why the whole grid read as though it had
been "painted over". The owner's words: "बैनर की क्वालिटी बहुत गंदी है."

So the frame grab is now the LAST resort, not the first choice. In order:

    1. a purpose-built hero image, generated for the thumbnail alone
       (ai_images.generate_thumbnail_image) - zero lossy steps;
    2. the sharpest of the run's SOURCE scene images, straight from
       IMAGES_DIR at JPEG q95 with no chroma subsampling - pre-grain,
       pre-grade, pre-encode;
    3. a frame from the video, as before, so a thumbnail always exists.

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
# Source selection
# --------------------------------------------------------------------------
def _sharpness(path):
    """Rough edge energy of an image. Higher = more detail.

    Used to choose between the run's scene images. A cheap proxy is enough: the
    candidates are all the same size, from the same model, in the same style, so
    only their relative detail matters. Measured on a downscaled copy because the
    absolute number is irrelevant and a full-size FIND_EDGES on seven 1274x2266
    frames is pure waste.
    """
    try:
        from PIL import Image, ImageFilter, ImageStat

        with Image.open(path) as img:
            small = img.convert("L").resize((256, 455), Image.BILINEAR)
            edges = small.filter(ImageFilter.FIND_EDGES)
            return float(ImageStat.Stat(edges).stddev[0])
    except Exception:
        return 0.0


def _best_scene_image():
    """The sharpest SOURCE scene frame for this run, or None.

    Skips the first and last frame when there are enough to choose from: scene 1
    is covered by the opening hook overlay in the video and scene N by the CTA
    overlay, so those are the two the viewer has already seen with text on top.
    """
    try:
        from . import ai_images
    except Exception:
        return None
    paths = [p for p in ai_images.scene_image_paths() if os.path.exists(p)]
    if not paths:
        return None
    candidates = paths[1:-1] if len(paths) >= 4 else paths
    best = max(candidates, key=_sharpness)
    log.info("Thumbnail source: sharpest of %d source scene image(s) -> %s",
             len(candidates), os.path.basename(best))
    return best


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

    LAST RESORT ONLY - see the module docstring. A third of the way in is chosen
    because the opening seconds are the hook overlay (big text over a punch-zoom)
    and the closing seconds are the CTA overlay; the middle is where the scene is
    on screen unobstructed.
    """
    duration = _probe_duration(video_path)
    seek = 1.5
    if duration and duration > 3:
        seek = round(duration * random.uniform(0.28, 0.42), 2)

    if shutil.which("ffmpeg"):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(seek),
                 "-i", video_path, "-frames:v", "1", "-q:v", "1", out_png],
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


def _resolve_source(video_path, out_path, hero_prompt=""):
    """Pick the best available source image. Returns (path, temp_path_or_None)."""
    source = str(get_cfg("thumbnail.source", "hero") or "hero").lower()

    if source == "hero" and str(hero_prompt or "").strip():
        try:
            from . import ai_images

            hero_path = os.path.splitext(out_path)[0] + "-hero.jpg"
            got = ai_images.generate_thumbnail_image(hero_prompt, hero_path)
            if got and os.path.exists(got):
                log.info("Thumbnail source: purpose-built hero image.")
                return got, got
        except Exception as exc:
            log.warning("Hero thumbnail image failed (%s); trying scene images.", exc)

    if source in ("hero", "scene"):
        scene = _best_scene_image()
        if scene:
            return scene, None

    frame_png = os.path.splitext(out_path)[0] + "-frame.png"
    frame = _extract_frame(video_path, frame_png)
    if frame:
        log.info("Thumbnail source: video frame (last resort - expect softer detail).")
        return frame, frame_png
    return None, frame_png


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


def _wrap(draw, text, font, max_w, max_lines):
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
    return lines[:max_lines]


def _fit_font(draw, text, max_w, max_lines, start_size):
    """Shrink the type until the headline fits in `max_lines` lines.

    Without this, a headline one word too long silently lost that word to the
    `[:max_lines]` slice - so a thumbnail could read "गुस्सा पहले किसे" and stop,
    which is worse than no caption at all. Now the text always fits; only the
    size gives.
    """
    size = int(start_size)
    while size >= int(start_size * 0.6):
        font = _find_font(size)
        if font is None:
            return None, []
        lines = _wrap(draw, text, font, max_w, max_lines + 1)
        if len(lines) <= max_lines:
            return font, lines
        size = int(size * 0.92)
    font = _find_font(size)
    if font is None:
        return None, []
    return font, _wrap(draw, text, font, max_w, max_lines)


def _scrim(height, opacity=0.82):
    """A bottom-up transparent-to-black gradient the text sits on.

    Replaces the flat 50%-grey rectangle the old version drew. A hard-edged band
    across a 9:16 tile looks like a UI element pasted on the picture; a gradient
    reads as part of the image while giving the same guaranteed contrast, which is
    how every professional thumbnail handles overlaid type.
    """
    from PIL import Image

    band = Image.new("L", (1, height))
    for y in range(height):
        t = y / float(max(1, height - 1))
        band.putpixel((0, y), int(255 * opacity * (t ** 1.55)))
    return band.resize((THUMB_W, height), Image.BILINEAR)


def generate_thumbnail(video_path, headline="", out_path=None, hero_prompt=""):
    """Build a 1080x1920 thumbnail for the channel grid.

    `hero_prompt` is the reel's opening scene description (English). When present,
    a dedicated image is generated for the thumbnail instead of a frame being
    pulled out of the encoded video - see the module docstring.

    Returns the output path, or None on any failure (never raises).
    """
    if not get_cfg("thumbnail.enabled", True):
        return None

    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    except Exception as exc:
        log.warning("Pillow unavailable (%s); skipping thumbnail.", exc)
        return None

    if not out_path:
        if not video_path:
            log.warning("Cannot build thumbnail; no output path given.")
            return None
        out_path = os.path.splitext(video_path)[0] + ".jpg"

    source, temp_path = _resolve_source(video_path, out_path, hero_prompt)
    if not source:
        log.warning("No usable thumbnail source; skipping thumbnail.")
        return None

    try:
        img = Image.open(source).convert("RGB")
        img = _fit_cover(img)

        # Deliberately gentle now. The old values (saturation 1.22 on top of the
        # video's own 1.18 grade, plus an unsharp mask over encoder artefacts)
        # were compensating for a mushy source. The source is clean, so the
        # correction that was fighting it would now just push skin tones orange
        # and halo every edge.
        sat = float(get_cfg("thumbnail.saturation", 1.08))
        con = float(get_cfg("thumbnail.contrast", 1.06))
        bri = float(get_cfg("thumbnail.brightness", 1.02))
        if sat != 1.0:
            img = ImageEnhance.Color(img).enhance(sat)
        if con != 1.0:
            img = ImageEnhance.Contrast(img).enhance(con)
        if bri != 1.0:
            img = ImageEnhance.Brightness(img).enhance(bri)
        amount = int(get_cfg("thumbnail.sharpen_percent", 60))
        if amount > 0:
            img = img.filter(ImageFilter.UnsharpMask(
                radius=1.4, percent=amount, threshold=4))

        text = " ".join(str(headline or "").split())
        max_words = int(get_cfg("thumbnail.max_words", 5))
        if text and bool(get_cfg("thumbnail.text_enabled", True)):
            text = " ".join(text.split()[:max_words])
            draw = ImageDraw.Draw(img, "RGBA")
            max_w = int(THUMB_W * 0.86)
            max_lines = int(get_cfg("thumbnail.max_lines", 2))
            font, lines = _fit_font(
                draw, text, max_w, max_lines,
                int(get_cfg("thumbnail.fontsize", 104)),
            )
            if font is not None and lines:
                line_h = int(getattr(font, "size", 104) * 1.16)
                block_h = line_h * len(lines)
                accent_h = 10
                pad = int(line_h * 0.42)

                # Bottom-anchored so the block never floats over the subject's
                # face, and so its position does not shift with line count.
                bottom_margin = int(THUMB_H * 0.055)
                y = THUMB_H - bottom_margin - block_h

                scrim_h = min(THUMB_H, block_h + pad * 2 + bottom_margin + accent_h + 40)
                scrim = _scrim(scrim_h, float(get_cfg("thumbnail.scrim_opacity", 0.82)))
                black = Image.new("RGB", (THUMB_W, scrim_h), (0, 0, 0))
                img.paste(black, (0, THUMB_H - scrim_h), scrim)

                # Re-bind: pasting created new pixel data behind the old handle.
                draw = ImageDraw.Draw(img, "RGBA")

                accent = textrender.parse_color(
                    get_cfg("thumbnail.accent_color", "#FFC44C"))
                stroke_w = int(get_cfg("thumbnail.stroke_width", 6))
                for line in lines:
                    try:
                        tw = draw.textlength(line, font=font)
                    except Exception:
                        tw = len(line) * font.size * 0.55
                    x = (THUMB_W - tw) / 2
                    draw.text(
                        (x, y), line, font=font, fill=(255, 255, 255, 255),
                        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 240),
                    )
                    y += line_h

                # A short gold rule under the headline. One deliberate graphic
                # element is what makes a set of tiles read as a channel rather
                # than as eight unrelated pictures.
                bar_w = int(THUMB_W * 0.22)
                bar_x = (THUMB_W - bar_w) // 2
                bar_y = y + int(line_h * 0.10)
                if bar_y + accent_h < THUMB_H:
                    draw.rectangle(
                        [bar_x, bar_y, bar_x + bar_w, bar_y + accent_h],
                        fill=tuple(accent[:3]) + (255,),
                    )

        # YouTube's ceiling is 2 MB. A 1080x1920 JPEG at quality 94 lands around
        # 500 KB, so the extra quality over the previous 88 is free - and 88 was
        # adding its own blocking to an image that had already been through x264.
        quality = int(get_cfg("thumbnail.jpeg_quality", 94))
        img.save(out_path, "JPEG", quality=quality, optimize=True, subsampling=0)

        size_kb = os.path.getsize(out_path) / 1024.0
        if size_kb > 1900:
            img.save(out_path, "JPEG", quality=85, optimize=True)
            size_kb = os.path.getsize(out_path) / 1024.0
            log.info("Thumbnail re-encoded to stay under YouTube's 2 MB limit.")
        log.info("Thumbnail written: %s (%.0f KB)", out_path, size_kb)
        return out_path
    except Exception as exc:
        log.warning("Thumbnail composition failed (%s).", exc)
        return None
    finally:
        # Only ever remove a temp file this module created. The scene images are
        # shared with the composer and must survive.
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
