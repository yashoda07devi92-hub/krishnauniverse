"""
Devanagari-safe text rendering for the long-form Krishna Universe pipeline.

WHY THIS MODULE EXISTS
----------------------
The parent pipeline drew every on-screen word with moviepy's TextClip, which
shells out to ImageMagick. That works for English but breaks for Hindi in two
separate ways:

  1. FONT. The bundled font was DejaVu-Sans-Bold. DejaVu has no Devanagari
     glyphs at all, so "कान्हा" renders as a row of empty boxes (tofu).

  2. SHAPING. Even with a Devanagari font installed, ImageMagick's `label:` and
     `caption:` operators do not run a complex-text shaper unless it was built
     against Pango. Without shaping, matras and conjuncts are laid out as
     independent glyphs: "कृष्ण" comes out as "क ृ ष ् ण" and the i-matra in
     "शिक्षा" lands on the wrong side of the consonant. It looks like garbage
     to a Hindi reader even though no error is raised.

So all text is rendered here with Pillow instead. Pillow's official wheels
bundle libraqm, which does full HarfBuzz shaping, so matras, conjuncts and
half-letters come out correct. The rendered RGBA bitmap is handed to moviepy as
an ImageClip, which the composer then animates exactly as before.

Everything is defensive: if no Devanagari font can be found, or Pillow is
missing, the caller gets None and the video renders without that text layer
rather than failing.
"""

import logging
import os

log = logging.getLogger("krishna.textrender")

# Ordered by preference. Noto Sans Devanagari is what the workflow installs
# (fonts-noto-devanagari); the rest are common fallbacks on other distros.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-SemiBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/Sarai/Sarai.ttf",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/samyak/Samyak-Devanagari.ttf",
    "/usr/share/fonts/truetype/fonts-deva-extra/chandas1-2.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # last resort, no Devanagari
)

_resolved_font = None


def find_font():
    """Return a path to a Devanagari-capable TTF, or None.

    KRISHNA_FONT env var wins so a font can be pinned without a code change.
    """
    global _resolved_font
    if _resolved_font is not None:
        return _resolved_font or None

    forced = os.environ.get("KRISHNA_FONT", "").strip()
    if forced and os.path.exists(forced):
        _resolved_font = forced
        log.info("Using pinned font: %s", forced)
        return forced

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            _resolved_font = path
            if "DejaVu" in path:
                log.warning(
                    "No Devanagari font found - falling back to %s, which CANNOT "
                    "draw Hindi. On-screen Hindi will show as empty boxes. Install "
                    "fonts-noto-devanagari.", path,
                )
            else:
                log.info("Devanagari font: %s", path)
            return path

    _resolved_font = ""
    log.error("No usable font found on this system; on-screen text disabled.")
    return None


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except Exception as exc:
        log.error("Pillow is required for text rendering (%s).", exc)
        return None, None, None


def _wrap(draw, text, font, max_width):
    """Greedy word wrap measured with the real shaped font metrics.

    Measuring with the actual font (rather than a character count) matters for
    Devanagari, where a conjunct like "क्ष" is one visual cluster but three
    codepoints, so character counting badly misjudges the line width.
    """
    words = str(text).split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        try:
            width = draw.textbbox((0, 0), trial, font=font)[2]
        except Exception:
            width = len(trial) * font.size * 0.5
        if width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_rgba(text, fontsize=76, color=(255, 255, 255), stroke_color=(0, 0, 0),
                stroke_width=5, max_width=900, line_spacing=1.18, align="center"):
    """Render `text` to an RGBA numpy array, or None on any failure."""
    if not text or not str(text).strip():
        return None

    Image, ImageDraw, ImageFont = _pil()
    if Image is None:
        return None

    font_path = find_font()
    if not font_path:
        return None

    try:
        import numpy as np
    except Exception as exc:
        log.error("numpy is required for text rendering (%s).", exc)
        return None

    try:
        font = ImageFont.truetype(font_path, int(fontsize))
    except Exception as exc:
        log.warning("Could not load font %s at %spx (%s).", font_path, fontsize, exc)
        return None

    try:
        # Scratch canvas purely for measuring.
        probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        lines = _wrap(probe, text, font, max_width)
        if not lines:
            return None

        pad = int(stroke_width) * 3 + 12
        line_h = int(fontsize * line_spacing)

        widths = []
        for line in lines:
            try:
                widths.append(probe.textbbox((0, 0), line, font=font)[2])
            except Exception:
                widths.append(int(len(line) * fontsize * 0.5))
        canvas_w = max(widths) + pad * 2
        # Devanagari matras sit above the line and some conjuncts hang below, so
        # the box gets generous vertical padding to avoid clipping them.
        canvas_h = line_h * len(lines) + pad * 2

        img = Image.new("RGBA", (max(2, canvas_w), max(2, canvas_h)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for i, line in enumerate(lines):
            y = pad + i * line_h
            if align == "center":
                x = canvas_w // 2
                anchor = "ma"
            elif align == "right":
                x = canvas_w - pad
                anchor = "ra"
            else:
                x = pad
                anchor = "la"
            try:
                draw.text(
                    (x, y), line, font=font, fill=tuple(color), anchor=anchor,
                    stroke_width=int(stroke_width), stroke_fill=tuple(stroke_color),
                )
            except TypeError:
                # Very old Pillow without stroke/anchor support: draw plainly.
                draw.text((pad, y), line, font=font, fill=tuple(color))

        return np.array(img)
    except Exception as exc:
        log.warning("Text render failed for %r (%s).", str(text)[:40], exc)
        return None


def make_clip(text, duration, fontsize=76, color=(255, 255, 255),
              stroke_color=(0, 0, 0), stroke_width=5, max_width=900,
              align="center"):
    """Render `text` and return a moviepy ImageClip of `duration`, or None.

    `duration` is taken up front rather than left to the caller because the
    transparency mask has to be built with a matching duration; setting it
    afterwards on a masked ImageClip does not reliably propagate to the mask.
    """
    arr = render_rgba(
        text, fontsize=fontsize, color=color, stroke_color=stroke_color,
        stroke_width=stroke_width, max_width=max_width, align=align,
    )
    if arr is None:
        return None
    try:
        from moviepy.editor import ImageClip

        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3] / 255.0
        mask = ImageClip(alpha, ismask=True).set_duration(duration)
        return ImageClip(rgb).set_duration(duration).set_mask(mask)
    except Exception as exc:
        log.warning("Could not build text clip (%s).", exc)
        return None


def parse_color(value, default=(255, 255, 255)):
    """Accept '#RRGGBB', 'white'/'black', or an (r,g,b) tuple."""
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            return tuple(int(v) for v in value[:3])
        except Exception:
            return default
    named = {
        "white": (255, 255, 255), "black": (0, 0, 0), "yellow": (255, 214, 92),
        "gold": (255, 196, 76), "saffron": (255, 153, 51), "orange": (255, 140, 40),
        "red": (220, 60, 60), "cream": (255, 246, 224),
    }
    s = str(value).strip().lower()
    if s in named:
        return named[s]
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except Exception:
            return default
    return default
