"""
Auto thumbnail generator for Krishna Universe Katha.

Builds a 1280x720 thumbnail with a bold, readable title (the spoken hook /
story title) over a dark gradient, using Pillow only (no moviepy). If a
background frame image is supplied it is used and darkened; otherwise a clean
storytime gradient is drawn.

Returns the thumbnail path, or None on failure (upload still works without it).
"""

import logging
import os
import textwrap

from .config import IMAGES_DIR, get_cfg
from . import textrender

log = logging.getLogger("krishna.thumbnail")


def _load_font(size):
    """Load a Devanagari-capable font at `size`.

    The candidate list this replaced was DejaVu and Arial only. Neither contains
    a single Devanagari glyph, so the Hindi title on every long-form thumbnail
    would have rendered as a row of empty boxes - silently, because PIL raises
    nothing for a missing glyph. Resolution is delegated to textrender so the
    thumbnail and the on-screen captions can never disagree about which font
    exists.

    ImageFont.load_default() is deliberately NOT used as a fallback: it is a tiny
    bitmap Latin font, so it would produce an unreadable thumbnail rather than a
    clean image with no title.
    """
    from PIL import ImageFont

    path = textrender.find_font()
    if not path:
        log.warning("No font available; thumbnail will have no title text.")
        return None
    try:
        return ImageFont.truetype(path, size)
    except Exception as exc:
        log.warning("Could not load thumbnail font %s (%s).", path, exc)
        return None


def _text_size(draw, text, font):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        try:
            return draw.textsize(text, font=font)
        except Exception:
            return (len(text) * 10, 20)


def generate_thumbnail(title, hook="", out_path=None):
    """Create a 1280x720 thumbnail. Returns the path or None."""
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        log.warning("Pillow unavailable (%s); skipping thumbnail.", exc)
        return None

    W, H = 1280, 720
    if out_path is None:
        out_path = os.path.join(str(IMAGES_DIR), "thumbnail.jpg")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    try:
        # Vertical dark-blue gradient background.
        img = Image.new("RGB", (W, H), (16, 20, 40))
        top = (28, 38, 78)
        bottom = (8, 10, 22)
        px = img.load()
        for y in range(H):
            f = y / float(H - 1)
            r = int(top[0] * (1 - f) + bottom[0] * f)
            g = int(top[1] * (1 - f) + bottom[1] * f)
            b = int(top[2] * (1 - f) + bottom[2] * f)
            for x in range(W):
                px[x, y] = (r, g, b)

        draw = ImageDraw.Draw(img)

        # Title (big, gold).
        title = (title or "A Moral Story").strip()
        font_big = _load_font(96)
        # No .upper(): Devanagari has no letter case. width lowered 16 -> 13
        # because Devanagari clusters are wider on screen than Latin
        # characters, and 16 overflowed the thumbnail at this font size.
        wrapped = textwrap.fill(title, width=13)
        gold = (255, 213, 74)
        # Draw with a simple black outline for readability.
        y = 140
        for line in wrapped.split("\n"):
            tw, th = _text_size(draw, line, font_big)
            x = (W - tw) // 2
            for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-3, -3), (3, 3)]:
                draw.text((x + dx, y + dy), line, font=font_big, fill=(0, 0, 0))
            draw.text((x, y), line, font=font_big, fill=gold)
            y += th + 18

        # Small channel tag at the bottom.
        channel = get_cfg("channel.name", "Krishna Universe")
        font_small = _load_font(44)
        tw, th = _text_size(draw, channel, font_small)
        draw.text(((W - tw) // 2, H - 90), channel, font=font_small, fill=(255, 255, 255))

        img.save(out_path, "JPEG", quality=90)
        log.info("Thumbnail written: %s", out_path)
        return out_path
    except Exception as exc:
        log.warning("Thumbnail generation failed (%s).", exc)
        return None
