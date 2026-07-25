"""
Devanagari-safe on-screen text rendering for Krishna Universe.

WHY THIS MODULE EXISTS
----------------------
The pipeline this was ported from drew every piece of on-screen text with
moviepy's `TextClip`, which shells out to ImageMagick's `label:` / `caption:`
using the font `DejaVu-Sans-Bold`. For an English channel that is fine. For a
Hindi channel it breaks in two separate ways, and both fail *silently* -- the
render still succeeds, it just looks wrong:

  1. DejaVu Sans contains no Devanagari glyphs at all. Every Hindi character
     comes out as an empty box (tofu). The hook, the flash phrases and the
     thumbnail headline would all be unreadable rectangles.

  2. Devanagari needs complex text shaping: matras reorder around the
     consonant, and consonant clusters form conjuncts (क + ् + ष -> क्ष).
     ImageMagick's plain `label:`/`caption:` renders glyph-by-glyph through
     FreeType with no shaping, so even with a Devanagari font loaded the
     matras land in the wrong place and conjuncts do not form. The text is
     legible-ish but visibly wrong to any Hindi reader.

So instead of ImageMagick we render text with Pillow, which uses libraqm (and
therefore HarfBuzz) for shaping when it is available -- and the official Pillow
wheels ship libraqm. The result is handed to moviepy as a plain image clip plus
an alpha mask.

This also removes the dependency on ImageMagick's policy.xml being patched,
which was a standing source of "captions silently missing" failures.

Everything is best-effort: if a font cannot be found or Pillow is unavailable,
`render()` returns None and the caller simply composes the video without that
text layer rather than failing the whole run.
"""

import logging
import os
import re

from .config import get_cfg, get_env

log = logging.getLogger("krishna.textrender")

# Ordered candidates. The Actions workflow installs fonts-noto-devanagari and
# fonts-lohit-deva, so the first two normally exist on CI.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-SemiBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/Sarai/Sarai.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

_font_path_cache = "unset"


def has_devanagari(text):
    """True if the string contains any Devanagari codepoint."""
    return bool(_DEVANAGARI.search(str(text or "")))


def font_path():
    """Locate a Devanagari-capable TTF once and remember it."""
    global _font_path_cache
    if _font_path_cache != "unset":
        return _font_path_cache

    candidates = []
    forced = get_env("KRISHNA_FONT_PATH")
    if forced:
        candidates.append(forced)
    configured = get_cfg("fonts.devanagari_path", None)
    if configured:
        candidates.append(configured)
    candidates.extend(_FONT_CANDIDATES)

    for path in candidates:
        try:
            if path and os.path.exists(path):
                _font_path_cache = path
                log.info("On-screen text font: %s", path)
                return path
        except Exception:
            continue

    log.error(
        "No Devanagari font found. Hindi on-screen text will be SKIPPED rather "
        "than rendered as empty boxes. Install fonts-noto-devanagari on the "
        "runner, or set KRISHNA_FONT_PATH."
    )
    _font_path_cache = None
    return None


def _load_font(size):
    from PIL import ImageFont

    path = font_path()
    if not path:
        return None
    try:
        # RAQM is what actually performs Devanagari shaping. Ask for it
        # explicitly so a Pillow build without it fails loudly here (and we log
        # it) instead of quietly producing mis-placed matras.
        try:
            return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            log.warning(
                "Pillow has no RAQM layout engine; Devanagari conjuncts/matras "
                "may be positioned incorrectly. Rendering anyway with BASIC."
            )
            return ImageFont.truetype(path, size)
    except Exception as exc:
        log.warning("Could not load font %s at %dpx (%s).", path, size, exc)
        return None


def _measure(draw, text, font, stroke_width):
    try:
        box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        return box[2] - box[0], box[3] - box[1], box[0], box[1]
    except Exception:
        try:
            w, h = draw.textsize(text, font=font)
            return w, h, 0, 0
        except Exception:
            return len(text) * int(font.size * 0.6), int(font.size * 1.3), 0, 0


def wrap(text, font, max_width, draw, stroke_width=0):
    """Greedy word wrap using real measured widths (not character counts)."""
    words = str(text).split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        w, _, _, _ = _measure(draw, trial, font, stroke_width)
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _parse_color(value, default=(255, 255, 255)):
    """Accept '#RRGGBB', 'white', 'black' or an (r,g,b) tuple."""
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(int(v) for v in value[:3])
    s = str(value or "").strip()
    named = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "gold": (255, 199, 66),
        "saffron": (255, 153, 51),
        "yellow": (255, 221, 87),
    }
    if s.lower() in named:
        return named[s.lower()]
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except Exception:
            pass
    return default


def render(text, fontsize=76, color="white", stroke_color="black",
           stroke_width=5, max_width=900, line_spacing=1.18, align="center"):
    """Render `text` to (rgb_array, alpha_array) float/uint8 numpy arrays.

    Returns None on any failure so the caller can carry on without the layer.
    The alpha channel is a 0..1 float array, which is exactly what moviepy
    wants for `ImageClip(..., ismask=True)`.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return None

    try:
        import numpy as np
        from PIL import Image, ImageDraw
    except Exception as exc:
        log.warning("Pillow/numpy unavailable for text rendering (%s).", exc)
        return None

    font = _load_font(int(fontsize))
    if font is None:
        return None

    stroke_width = max(0, int(stroke_width))
    fg = _parse_color(color, (255, 255, 255))
    sc = _parse_color(stroke_color, (0, 0, 0))

    try:
        probe = Image.new("RGBA", (8, 8))
        pdraw = ImageDraw.Draw(probe)
        lines = wrap(text, font, int(max_width), pdraw, stroke_width)
        if not lines:
            return None

        metrics = [_measure(pdraw, ln, font, stroke_width) for ln in lines]
        line_h = max(m[1] for m in metrics)
        step = int(line_h * float(line_spacing))
        width = max(m[0] for m in metrics) + 2 * stroke_width + 8
        height = step * (len(lines) - 1) + line_h + 2 * stroke_width + 8
        width = int(min(max(width, 8), max_width + 4 * stroke_width + 16))
        height = int(max(height, 8))

        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        y = stroke_width + 4
        for line, (lw, _lh, ox, oy) in zip(lines, metrics):
            if align == "left":
                x = stroke_width + 4
            elif align == "right":
                x = width - lw - stroke_width - 4
            else:
                x = (width - lw) // 2
            draw.text(
                (x - ox, y - oy),
                line,
                font=font,
                fill=fg + (255,),
                stroke_width=stroke_width,
                stroke_fill=sc + (255,),
            )
            y += step

        arr = np.array(canvas)
        rgb = arr[:, :, :3].astype("uint8")
        alpha = arr[:, :, 3].astype("float64") / 255.0
        return rgb, alpha
    except Exception as exc:
        log.warning("Text render failed for %r (%s).", text[:40], exc)
        return None


def make_clip(text, duration, fontsize=76, color="white", stroke_color="black",
              stroke_width=5, max_width=900, opacity=1.0):
    """Render text and wrap it in a moviepy ImageClip with a proper alpha mask.

    This is the drop-in replacement for `TextClip(...)` used across the
    composer. Returns None on failure.
    """
    out = render(
        text, fontsize=fontsize, color=color, stroke_color=stroke_color,
        stroke_width=stroke_width, max_width=max_width,
    )
    if out is None:
        return None
    rgb, alpha = out
    try:
        from moviepy.editor import ImageClip

        if opacity is not None and float(opacity) < 1.0:
            alpha = alpha * float(opacity)
        mask = ImageClip(alpha, ismask=True).set_duration(duration)
        clip = ImageClip(rgb).set_duration(duration).set_mask(mask)
        return clip
    except Exception as exc:
        log.warning("Could not build text ImageClip (%s).", exc)
        return None
