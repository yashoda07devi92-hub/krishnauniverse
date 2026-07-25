"""
Video composition for Krishna Universe.

Assembles a 60s vertical 1080x1920 reel:
  * Background built from a priority chain (Pexels video -> Pexels photos
    Ken-Burns -> warm animated gradient). Random/irrelevant keyless stock
    images are deliberately NOT used.
  * A subtle BRIGHT, VIVID, PUNCHY grade (gentle saturation + slight
    brightness/contrast lift; vignette nearly off; no warm haze).
  * Short crossfade transitions between background segments for smooth motion.
  * A first-5-seconds animated HOOK overlay (scale "pop" + background "punch"
    zoom + subtle flash) that stops the scroll.
  * Word-by-word style timing-based captions with a soft rounded backdrop pill
    for the rest.
  * Audio = voiceover (+ optional low-volume background music).

Heavy imports (moviepy/numpy) happen lazily inside functions so that importing
this module never hard-fails in restricted environments.
"""

# ---------------------------------------------------------------------------
# Pillow >= 10 removed Image.ANTIALIAS which moviepy 1.0.3 relies on. Re-add
# the constants at import time BEFORE moviepy is ever imported.
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

import logging
import os
import random

from .config import MUSIC_DIR, OUTPUT_DIR, get_cfg
from . import ai_images
from . import images as images_mod
from . import pexels_video
from . import subtitles
from . import textrender

log = logging.getLogger("krishna.video")

# Defaults (overridable via config.json).
W = get_cfg("video.width", 1080)
H = get_cfg("video.height", 1920)
FPS = get_cfg("video.fps", 30)


# ==========================================================================
# Background construction
# ==========================================================================
def _fit_cover(clip, target_w=None, target_h=None):
    """Resize+crop a clip so it covers the target frame (no letterboxing).

    target_w/target_h default to the output frame. The motion engine passes a
    deliberately LARGER target so there is spare image to pan across.
    """
    from moviepy.video.fx.all import crop

    tw = int(target_w or W)
    th = int(target_h or H)

    try:
        cw, ch = clip.size
    except Exception:
        return clip.resize((tw, th))

    scale = max(tw / float(cw), th / float(ch))
    new_w = int(cw * scale)
    new_h = int(ch * scale)
    # Force EVEN dimensions. Odd width/height encoded as yuv420p (chroma
    # subsampling) is a classic cause of coloured / "rainbow" fringing along
    # the edges, so we round each side up to the nearest even number.
    new_w += new_w % 2
    new_h += new_h % 2
    clip = clip.resize((new_w, new_h))
    try:
        clip = crop(clip, width=tw, height=th, x_center=new_w / 2, y_center=new_h / 2)
    except Exception:
        clip = clip.resize((tw, th))
    return clip


def _concat_with_crossfade(segments, duration):
    """Concatenate clips with short crossfade transitions for a premium feel.

    Uses moviepy's crossfadein + a compose concatenation with negative padding
    so successive segments overlap by `crossfade_seconds`. Fully defensive: on
    ANY error it falls back to plain concatenation so the reel always renders.
    """
    from moviepy.editor import concatenate_videoclips

    if not segments:
        raise RuntimeError("No segments to concatenate.")

    xfade = float(get_cfg("transitions.crossfade_seconds", 0.35))

    if len(segments) > 1 and xfade > 0:
        try:
            # IMPORTANT: crossfadein lives in compositing.transitions, NOT in
            # fx.all (importing it from fx.all silently failed before, so every
            # reel used hard jump-cuts instead of smooth transitions).
            try:
                from moviepy.video.compositing.transitions import crossfadein as _xfn
            except Exception:
                _xfn = None

            faded = [segments[0]]
            for seg in segments[1:]:
                # Don't let the crossfade exceed the segment length.
                try:
                    seg_dur = seg.duration or xfade
                except Exception:
                    seg_dur = xfade
                this_fade = min(xfade, max(0.05, seg_dur * 0.5))
                if _xfn is not None:
                    faded.append(_xfn(seg, this_fade))
                else:
                    faded.append(seg.crossfadein(this_fade))
            bg = concatenate_videoclips(faded, method="compose", padding=-xfade)
            bg = bg.set_duration(duration)
            log.info("Applied %.2fs crossfade transitions between %d segment(s).", xfade, len(segments))
            return bg
        except Exception as exc:
            log.warning("Crossfade concat failed (%s); using plain concatenation.", exc)

    bg = concatenate_videoclips(segments, method="compose").set_duration(duration)
    return bg


# The camera moves available to the motion engine. A single slow centre zoom -
# what the parent pipeline used for every image - is exactly what reads as a
# slideshow: the eye recognises the same move repeating and stops believing the
# frame is real. Rotating through translations and zooms, with a different one
# per scene, is what mythology channels use to make stills feel filmed.
_MOVES = (
    "push_in", "pull_out",
    "pan_left", "pan_right",
    "tilt_up", "tilt_down",
    "diag_ul", "diag_dr",
    "pan_zoom_left", "pan_zoom_right",
)


def _motion_from_image(path, duration, move=None):
    """Animate a still with a real camera move. Returns a WxH clip.

    HOW IT WORKS
    ------------
    The image is first fitted to an OVERSCANNED frame (default 1.28x), which
    leaves spare pixels outside the visible area. The clip is then translated
    inside a WxH composite, so pixels genuinely move across the frame rather
    than just scaling about the centre.

    Pure translations (pan/tilt/diagonal) deliberately skip moviepy's per-frame
    `resize`, which resamples the full 1382x2458 image on every one of ~54 frames
    and is by far the most expensive thing in the render. Only the zoom moves pay
    that cost, so most segments are cheap.
    """
    from moviepy.editor import CompositeVideoClip, ImageClip

    if move is None:
        move = random.choice(_MOVES)

    over = float(get_cfg("motion.overscan", 1.28))
    zoom = float(get_cfg("motion.zoom_amount", 0.10))
    ow = int(W * over)
    oh = int(H * over)
    ow += ow % 2
    oh += oh % 2

    try:
        base = ImageClip(path).set_duration(duration)
        base = _fit_cover(base, ow, oh)
    except Exception as exc:
        log.warning("Could not load scene image %s (%s).", path, exc)
        return None

    # Travel room: how far the oversized image can slide before an edge shows.
    slack_x = max(0, ow - W)
    slack_y = max(0, oh - H)
    cx = -slack_x / 2.0
    cy = -slack_y / 2.0

    def frac(t):
        return min(1.0, max(0.0, (t / duration) if duration else 0.0))

    try:
        if move in ("push_in", "pull_out"):
            # Scale about the centre. Needs per-frame resize.
            def scale(t):
                f = frac(t)
                if move == "push_in":
                    return 1.0 + zoom * f
                return (1.0 + zoom) - zoom * f

            seg = base.resize(scale).set_position(("center", "center"))
            return CompositeVideoClip([seg], size=(W, H)).set_duration(duration)

        if move in ("pan_zoom_left", "pan_zoom_right"):
            direction = -1.0 if move == "pan_zoom_left" else 1.0

            def scale2(t):
                return 1.0 + zoom * frac(t)

            def pos2(t):
                f = frac(t)
                x = cx + direction * (slack_x / 2.0) * f
                return (x, cy)

            seg = base.resize(scale2).set_position(pos2)
            return CompositeVideoClip([seg], size=(W, H)).set_duration(duration)

        # Pure translations - no resize, so these are the cheap ones.
        def pos(t):
            f = frac(t)
            if move == "pan_left":
                return (cx - (slack_x / 2.0) * f, cy)
            if move == "pan_right":
                return (cx + (slack_x / 2.0) * f, cy)
            if move == "tilt_up":
                return (cx, cy - (slack_y / 2.0) * f)
            if move == "tilt_down":
                return (cx, cy + (slack_y / 2.0) * f)
            if move == "diag_ul":
                return (cx - (slack_x / 2.0) * f, cy - (slack_y / 2.0) * f)
            if move == "diag_dr":
                return (cx + (slack_x / 2.0) * f, cy + (slack_y / 2.0) * f)
            return (cx, cy)

        seg = base.set_position(pos)
        return CompositeVideoClip([seg], size=(W, H)).set_duration(duration)
    except Exception as exc:
        log.warning("Motion move %r failed for %s (%s); using static frame.", move, path, exc)
        try:
            return _fit_cover(ImageClip(path).set_duration(duration))
        except Exception:
            return None


def _video_background(clip_paths, duration):
    """Concatenate / loop Pexels video clips with FAST CUTS to fill `duration`.

    Segments are joined with short crossfades for smooth, polished motion.
    """
    from moviepy.editor import VideoFileClip

    cut = get_cfg("video.clip_cut_seconds", 3.0)
    xfade = float(get_cfg("transitions.crossfade_seconds", 0.35))
    segments = []
    total = 0.0
    idx = 0
    guard = 0
    while clip_paths and guard < 200:
        # Account for crossfade overlap shrinking the composed length.
        effective = total - max(0, len(segments) - 1) * xfade
        if effective >= duration:
            break
        guard += 1
        path = clip_paths[idx % len(clip_paths)]
        idx += 1
        try:
            vc = VideoFileClip(path, audio=False)
        except Exception as exc:
            log.warning("Could not open clip %s (%s); skipping.", path, exc)
            continue
        seg_dur = min(cut, vc.duration or cut)
        if seg_dur <= 0:
            vc.close()
            continue
        seg = vc.subclip(0, seg_dur)
        seg = _fit_cover(seg)
        segments.append(seg)
        total += seg_dur
    if not segments:
        raise RuntimeError("No usable video segments.")
    bg = _concat_with_crossfade(segments, duration)
    bg = bg.set_duration(duration)
    return bg


def _images_background(image_paths, duration):
    """Animated background built from stills, each with its own camera move."""
    if not image_paths:
        raise RuntimeError("No images for background.")
    xfade = float(get_cfg("transitions.crossfade_seconds", 0.25))
    cut = float(get_cfg("video.scene_cut_seconds", 2.6))
    per = max(1.4, min(cut, duration / max(1, len(image_paths))))

    # Shuffle the move order so consecutive scenes never share a direction.
    moves = list(_MOVES)
    random.shuffle(moves)

    clips = []
    total = 0.0
    idx = 0
    guard = 0
    while guard < 200:
        effective = total - max(0, len(clips) - 1) * xfade
        if effective >= duration:
            break
        guard += 1
        path = image_paths[idx % len(image_paths)]
        seg_dur = min(per, duration - effective)
        if seg_dur <= 0.4:
            break
        seg = _motion_from_image(path, seg_dur, move=moves[idx % len(moves)])
        idx += 1
        if seg is None:
            continue
        clips.append(seg)
        total += seg_dur
    if not clips:
        raise RuntimeError("No motion clips built.")
    log.info("Scene background: %d animated frame(s), ~%.1fs each.", len(clips), per)
    return _concat_with_crossfade(clips, duration).set_duration(duration)


def _mixed_background(image_paths, clip_paths, duration):
    """Interleave AI scene frames with REAL atmosphere footage.

    This is the single most important function for the "should look like real
    video, not a slideshow" requirement. Generated frames carry the story, but
    they are still images however well they are animated. Dropping a genuine
    moving shot - river water, a peacock, rain on leaves - every few seconds
    gives the eye real motion to anchor on, and the animated frames around it
    read as filmed rather than as a photo montage.

    Pattern is `motion.real_every` AI frames, then one real clip, repeating.
    Falls back to whichever source is available if the other is empty.
    """
    from moviepy.editor import VideoFileClip

    if not image_paths and not clip_paths:
        raise RuntimeError("No sources for mixed background.")
    if not clip_paths:
        return _images_background(image_paths, duration)
    if not image_paths:
        return _video_background(clip_paths, duration)

    xfade = float(get_cfg("transitions.crossfade_seconds", 0.25))
    scene_cut = float(get_cfg("video.scene_cut_seconds", 2.6))
    real_cut = float(get_cfg("video.clip_cut_seconds", 1.6))
    every = max(1, int(get_cfg("motion.real_every", 2)))

    moves = list(_MOVES)
    random.shuffle(moves)

    segments = []
    total = 0.0
    img_i = 0
    clip_i = 0
    placed_since_real = 0
    guard = 0

    while guard < 300:
        effective = total - max(0, len(segments) - 1) * xfade
        remaining = duration - effective
        if remaining <= 0.4:
            break
        guard += 1

        use_real = placed_since_real >= every
        if use_real:
            path = clip_paths[clip_i % len(clip_paths)]
            clip_i += 1
            seg_dur = min(real_cut, remaining)
            try:
                vc = VideoFileClip(path, audio=False)
                seg_dur = min(seg_dur, vc.duration or seg_dur)
                if seg_dur <= 0.3:
                    vc.close()
                    placed_since_real = 0
                    continue
                seg = _fit_cover(vc.subclip(0, seg_dur))
                segments.append(seg)
                total += seg_dur
                placed_since_real = 0
                continue
            except Exception as exc:
                log.warning("Could not use atmosphere clip %s (%s).", path, exc)
                placed_since_real = 0
                continue

        path = image_paths[img_i % len(image_paths)]
        seg_dur = min(scene_cut, remaining)
        seg = _motion_from_image(path, seg_dur, move=moves[img_i % len(moves)])
        img_i += 1
        if seg is None:
            continue
        segments.append(seg)
        total += seg_dur
        placed_since_real += 1

    if not segments:
        raise RuntimeError("Mixed background produced no segments.")
    log.info(
        "Mixed background: %d segment(s) - %d AI scene frame(s) + %d real atmosphere shot(s).",
        len(segments), img_i, clip_i,
    )
    return _concat_with_crossfade(segments, duration).set_duration(duration)


def _warm_gradient_background(duration):
    """Animated WARM gradient (golden/peach/cream). Vectorized numpy.

    Falls back to a solid warm ColorClip on any error.
    """
    import numpy as np
    from moviepy.editor import VideoClip, ColorClip

    top = np.array(get_cfg("palette.gradient_top", [255, 224, 178]), dtype=np.float64)
    bottom = np.array(get_cfg("palette.gradient_bottom", [255, 183, 153]), dtype=np.float64)
    accent = np.array(get_cfg("palette.gradient_accent", [255, 245, 224]), dtype=np.float64)

    try:
        # Vertical gradient ramp (H,1,3) broadcast across width.
        ramp = np.linspace(0.0, 1.0, H, dtype=np.float64).reshape(H, 1, 1)
        base = top.reshape(1, 1, 3) * (1.0 - ramp) + bottom.reshape(1, 1, 3) * ramp

        def make_frame(t):
            # Gentle breathing shift toward the accent colour.
            phase = 0.5 + 0.5 * np.sin(2.0 * np.pi * t / 8.0)
            frame = base * (1.0 - 0.18 * phase) + accent.reshape(1, 1, 3) * (0.18 * phase)
            frame = np.clip(frame, 0, 255).astype("uint8")
            # Broadcast across the full width.
            return np.broadcast_to(frame, (H, W, 3)).copy()

        clip = VideoClip(make_frame, duration=duration)
        clip = clip.set_fps(FPS)
        log.info("Background source: warm animated gradient (last resort).")
        return clip
    except Exception as exc:
        log.warning("Gradient generation failed (%s); using solid warm color.", exc)
        solid = get_cfg("palette.solid_fallback", [255, 209, 168])
        return ColorClip(size=(W, H), color=tuple(solid)).set_duration(duration)


def _build_background(keywords, duration, scene_prompts=None):
    """Background priority chain, rebuilt for a mythology channel.

    Chain:
      (1) AI scene frames + real atmosphere footage, interleaved  <- the goal
      (2) AI scene frames alone, each with its own camera move
      (3) Real atmosphere footage alone
      (4) Pexels photos, animated
      (5) Warm gradient (always works)

    The parent pipeline led with a Pexels VIDEO search on the story keywords.
    That is inverted here: searching stock video for "krishna lifting govardhan"
    returns nothing relevant, so generated scenes lead and real footage is
    demoted to atmosphere.
    """
    scenes = []
    if scene_prompts:
        try:
            scenes = ai_images.generate_scene_images(scene_prompts)
        except Exception as exc:
            log.warning("Scene image generation errored (%s).", exc)
            scenes = []

    atmosphere = []
    try:
        atmosphere = pexels_video.fetch_pexels_videos(keywords) or []
    except Exception as exc:
        log.warning("Atmosphere footage fetch error (%s).", exc)

    # (1) The intended path: story frames with real motion cut between them.
    if scenes and atmosphere:
        log.info("Background source: %d AI scene(s) MIXED with %d atmosphere clip(s).",
                 len(scenes), len(atmosphere))
        try:
            return _mixed_background(scenes, atmosphere, duration)
        except Exception as exc:
            log.warning("Mixed background failed (%s); trying scenes only.", exc)

    # (2) Scenes only.
    if scenes:
        log.info("Background source: %d AI scene frame(s), animated.", len(scenes))
        try:
            return _images_background(scenes, duration)
        except Exception as exc:
            log.warning("Scene background failed (%s); trying atmosphere footage.", exc)

    # (3) Atmosphere footage only. The story will not be depicted, but the video
    # still looks like a devotional reel rather than a coloured rectangle.
    if atmosphere:
        log.warning("No AI scenes available; falling back to atmosphere footage only.")
        try:
            return _video_background(atmosphere, duration)
        except Exception as exc:
            log.warning("Atmosphere video background failed (%s); trying photos.", exc)

    # (4) Pexels photos, animated with the same motion engine.
    try:
        photos = images_mod.fetch_pexels_photos(keywords)
        if photos:
            log.warning("Falling back to Pexels PHOTOS (%d), animated.", len(photos))
            try:
                return _images_background(photos, duration)
            except Exception as exc:
                log.warning("Photo background build failed (%s); using gradient.", exc)
    except Exception as exc:
        log.warning("Pexels photo fetch error (%s); using gradient.", exc)

    # (5) Gradient last resort.
    return _warm_gradient_background(duration)


# ==========================================================================
# Color grade — BRIGHT, VIVID, PUNCHY (no faded haze)
# ==========================================================================
def _apply_color_grade(clip):
    """Apply a SUBTLE bright/punchy grade directly to the background so cute
    colors pop: a gentle saturation/brightness multiply (colorx) plus a slight
    brightness + contrast lift (lum_contrast). This replaces the old faded
    warm-wash + heavy-vignette look. Fully defensive: returns the clip
    unchanged on any error so the reel always renders.
    """
    try:
        from moviepy.video.fx.all import colorx, lum_contrast
    except Exception as exc:
        log.warning("Color grade fx unavailable (%s); using ungraded background.", exc)
        return clip

    saturation = float(get_cfg("grade.saturation", 1.12))
    brightness = float(get_cfg("grade.brightness", 8))
    contrast = float(get_cfg("grade.contrast", 0.10))

    graded = clip
    try:
        # Mild multiply lifts brightness and makes colours pop (not oversaturated).
        graded = colorx(graded, saturation)
    except Exception as exc:
        log.warning("colorx grade failed (%s); skipping that step.", exc)
    try:
        # Slight brightness + contrast lift for crisp, clean footage.
        graded = lum_contrast(graded, lum=brightness, contrast=contrast)
    except Exception as exc:
        log.warning("lum_contrast grade failed (%s); skipping that step.", exc)

    log.info(
        "Applied bright/punchy grade (saturation=%.2f, brightness=%.0f, contrast=%.2f).",
        saturation, brightness, contrast,
    )
    return graded


def _build_cinematic_grade(duration):
    """Disabled on purpose: returns NO overlay layers.

    The old version added a warm tint and a radial VIGNETTE (a black overlay
    with an OVAL alpha mask). That vignette was the source of the reported
    "oval / egg-shaped frame" plus the coloured "rainbow glitch" fringing along
    the mask boundary. To guarantee a 100% clean, full RECTANGULAR frame with
    NO mask and NO colour fringing, we add no finishing overlays at all.
    """
    return []


# ==========================================================================
# Captions
# ==========================================================================
def _make_text_clip(txt, fontsize, color, stroke_color, stroke_width, font, max_w,
                    duration=1.0):
    """Render text via Pillow instead of moviepy's TextClip.

    WHY NOT TextClip
    ----------------
    TextClip shells out to ImageMagick, which fails for Hindi in two ways at
    once: the configured DejaVu font has no Devanagari glyphs (every word comes
    out as empty boxes), and ImageMagick's label/caption operators do not run a
    complex-text shaper, so matras and conjuncts land in the wrong places even
    with a correct font installed. Neither raises an error - it just renders
    garbage. modules/textrender uses Pillow, whose wheels bundle libraqm and
    therefore shape Devanagari properly.

    `font` is accepted and ignored so existing call sites need no changes; the
    real font is resolved by textrender.find_font().
    """
    return textrender.make_clip(
        txt,
        duration=duration,
        fontsize=int(fontsize),
        color=textrender.parse_color(color, (255, 255, 255)),
        stroke_color=textrender.parse_color(stroke_color, (0, 0, 0)),
        stroke_width=int(stroke_width or 0),
        max_width=int(max_w),
    )


def _hex_to_rgb(value, default=(0, 0, 0)):
    """Parse a '#RRGGBB' hex color into an (r, g, b) tuple. Defensive."""
    try:
        s = str(value).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return default
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return default


def _make_caption_backdrop(tw, th, start, seg_dur, y_top):
    """Build a semi-transparent (optionally rounded) dark pill sized to the
    caption text so it reads cleanly on bright footage. Returns a positioned
    clip or None on any error.
    """
    try:
        import numpy as np
        from moviepy.editor import ColorClip, ImageClip

        opacity = float(get_cfg("captions.bg_opacity", 0.35))
        if opacity <= 0:
            return None
        color = _hex_to_rgb(get_cfg("captions.bg_color", "#000000"))
        rounded = bool(get_cfg("captions.rounded", True))

        pad_x = max(24, int(tw * 0.06))
        pad_y = max(16, int(th * 0.22))
        w = int(tw + 2 * pad_x)
        h = int(th + 2 * pad_y)
        if w <= 2 or h <= 2:
            return None

        alpha = np.ones((h, w), dtype=np.float64) * opacity
        if rounded:
            radius = int(min(h // 2, 48))
            if radius > 0:
                yy, xx = np.ogrid[0:h, 0:w]
                dx = np.minimum(xx, w - 1 - xx)
                dy = np.minimum(yy, h - 1 - yy)
                in_corner = (dx < radius) & (dy < radius)
                dist = np.sqrt((radius - dx) ** 2 + (radius - dy) ** 2)
                alpha[in_corner & (dist > radius)] = 0.0

        mask = ImageClip(alpha, ismask=True).set_duration(seg_dur)
        bg = (
            ColorClip(size=(w, h), color=color)
            .set_duration(seg_dur)
            .set_mask(mask)
            .set_start(start)
            .set_position(("center", int(y_top - pad_y)))
        )
        return bg
    except Exception as exc:
        log.warning("Caption backdrop failed (%s); showing text only.", exc)
        return None


def _build_caption_clips(text, duration):
    """Return a list of positioned caption clips (backdrops + text; may be empty)."""
    if not get_cfg("captions.enabled", True):
        return []

    groups = subtitles.build_caption_groups(text, duration)
    if not groups:
        return []

    fontsize = get_cfg("captions.fontsize", 90)
    color = get_cfg("captions.color", "white")
    stroke_color = get_cfg("captions.stroke_color", "black")
    stroke_width = get_cfg("captions.stroke_width", 4)
    font = get_cfg("captions.font", "DejaVu-Sans-Bold")
    y_ratio = get_cfg("captions.position_y_ratio", 0.72)
    max_w = int(W * 0.9)

    # Emotional power-words to highlight in a warm accent color.
    power_words = {"love", "sweet", "adorable", "family", "rescue", "heart",
                   "joy", "cute", "gentle", "precious"}
    accent = get_cfg("captions.accent_color", "#FFD27F")

    clips = []
    for g in groups:
        words = g["text"].split()
        is_power = any(w.strip(".,!?;:").lower() in power_words for w in words)
        use_color = accent if is_power else color
        seg_dur = max(0.2, g["end"] - g["start"])
        # NOTE: no .upper() anywhere in this file any more. Devanagari has no
        # letter case, so str.upper() was a silent no-op on Hindi text - but it
        # also meant the code read as if it were shouting, which it never was.
        tc = _make_text_clip(
            g["text"], fontsize, use_color, stroke_color, stroke_width, font, max_w,
            duration=seg_dur,
        )
        if tc is None:
            continue
        y_top = int(H * y_ratio)
        try:
            tc = tc.set_start(g["start"])
            tc = tc.set_position(("center", y_top))
        except Exception as exc:
            log.warning("Could not place caption '%s' (%s).", g["text"], exc)
            continue

        # Add a backdrop pill BEHIND this caption (appended first so text is on top).
        try:
            tw, th = tc.size
            backdrop = _make_caption_backdrop(tw, th, g["start"], seg_dur, y_top)
            if backdrop is not None:
                clips.append(backdrop)
        except Exception as exc:
            log.warning("Caption backdrop sizing failed (%s); skipping backdrop.", exc)

        clips.append(tc)
    log.info("Built %d caption layer(s) (incl. backdrops).", len(clips))
    return clips


# ==========================================================================
# Mid-video FLASH phrases
# ==========================================================================
def _build_flash_clips(flashes, duration, start_after=0.0):
    """Flash a few very short phrases during the middle of the reel.

    WHY THIS EXISTS
    ---------------
    Rolling word-by-word captions are switched OFF on this channel on purpose:
    at 84px with a dark backdrop pill they covered the animal, which is the only
    thing the viewer came for. But turning them off left a muted viewer with
    nothing to read after the 2.5s opening hook, and a large share of Shorts
    plays start muted.

    So instead of a permanent subtitle track, three phrases of two or three
    words each appear for a little over a second, spaced across the middle of
    the video, in the UPPER third where the subject is not, with no backdrop
    panel and a soft fade. Something to read, nothing obscured.

    The phrases come from modules/pools.FLASH_PHRASES via the no-repeat history,
    so a week of uploads does not carry the same three words.

    Returns [] if disabled, if there is nothing to show, or on any render error.
    """
    if not get_cfg("flash_text.enabled", True):
        return []
    phrases = [str(p).strip() for p in (flashes or []) if str(p).strip()]
    if not phrases:
        return []

    show_for = float(get_cfg("flash_text.duration_seconds", 1.3))
    fade = float(get_cfg("flash_text.fade_seconds", 0.25))
    fontsize = int(get_cfg("flash_text.fontsize", 76))
    color = get_cfg("flash_text.color", "white")
    stroke_color = get_cfg("flash_text.stroke_color", "black")
    stroke_width = int(get_cfg("flash_text.stroke_width", 5))
    font = get_cfg("flash_text.font", "DejaVu-Sans-Bold")
    y_ratio = float(get_cfg("flash_text.position_y_ratio", 0.14))
    tail_guard = float(get_cfg("flash_text.end_before_seconds", 2.5))

    # Window available for flashes: after the hook, before the closing seconds.
    window_start = max(float(start_after) + 0.6, 0.6)
    window_end = duration - tail_guard
    if window_end - window_start < show_for:
        log.info("Reel too short for flash phrases; skipping.")
        return []

    phrases = phrases[: max(1, int(get_cfg("flash_text.count", 3)))]
    slots = len(phrases)
    span = (window_end - window_start) / float(slots)

    clips = []
    for i, phrase in enumerate(phrases):
        # Centre each phrase inside its own slice so they never overlap.
        start = window_start + span * i + max(0.0, (span - show_for) / 2.0)
        seg = min(show_for, window_end - start)
        if seg <= 0.3:
            continue
        tc = _make_text_clip(
            phrase, fontsize, color, stroke_color, stroke_width,
            font, int(W * 0.86), duration=seg,
        )
        if tc is None:
            continue
        try:
            tc = tc.set_start(start)
            tc = tc.set_position(("center", int(H * y_ratio)))
            # Soft fade so it reads as a gentle accent, not a hard cut.
            if fade > 0 and seg > fade * 2:
                tc = tc.crossfadein(fade).crossfadeout(fade)
            clips.append(tc)
        except Exception as exc:
            log.warning("Could not place flash phrase %r (%s).", phrase, exc)
            continue

    log.info("Built %d flash phrase(s): %s", len(clips), " | ".join(phrases))
    return clips


# ==========================================================================
# First-5-seconds HOOK overlay
# ==========================================================================
def _build_hook_clips(hook_text, background):
    """Return (overlay_clips, punched_background).

    Produces a big animated hook text with a scale "pop" entrance, a subtle
    flash, an optional semi-transparent backdrop band, and applies a brief
    background "punch" zoom for the hook window. Returns ([], background) if
    disabled or rendering fails.
    """
    if not get_cfg("hook.enabled", True) or not hook_text:
        return [], background

    hook_dur = float(get_cfg("hook.duration_seconds", 5.0))
    fontsize = get_cfg("hook.fontsize", 150)
    color = get_cfg("hook.color", "white")
    stroke_color = get_cfg("hook.stroke_color", "black")
    stroke_width = get_cfg("hook.stroke_width", 6)
    font = get_cfg("hook.font", "DejaVu-Sans-Bold")
    overshoot = float(get_cfg("hook.pop_overshoot", 1.18))
    pop_in = float(get_cfg("hook.pop_in_seconds", 0.45))
    punch_zoom = float(get_cfg("hook.punch_zoom", 1.12))
    flash_opacity = float(get_cfg("hook.flash_opacity", 0.35))
    backdrop_opacity = float(get_cfg("hook.backdrop_opacity", 0.35))

    overlays = []
    punched_bg = background

    # --- Background "punch" zoom for the hook window ---
    try:
        def punch_scale(t):
            if t >= hook_dur:
                return 1.0
            frac = t / hook_dur
            # Start zoomed in, settle back to 1.0 by the end of the hook.
            return 1.0 + (punch_zoom - 1.0) * (1.0 - frac)

        punched_bg = background.resize(punch_scale).set_position(("center", "center"))
    except Exception as exc:
        log.warning("Hook background punch failed (%s); keeping plain background.", exc)
        punched_bg = background

    # --- Subtle white flash at the very start ---
    try:
        from moviepy.editor import ColorClip

        flash = (
            ColorClip(size=(W, H), color=(255, 255, 255))
            .set_duration(min(0.35, hook_dur))
            .set_opacity(flash_opacity)
            .set_start(0)
        )
        overlays.append(flash)
    except Exception as exc:
        log.warning("Hook flash failed (%s); skipping flash.", exc)

    # --- Semi-transparent dark backdrop band so text pops off footage ---
    if backdrop_opacity > 0:
        try:
            from moviepy.editor import ColorClip

            band_h = int(H * 0.28)
            backdrop = (
                ColorClip(size=(W, band_h), color=(0, 0, 0))
                .set_duration(hook_dur)
                .set_opacity(backdrop_opacity)
                .set_start(0)
                .set_position(("center", "center"))
            )
            overlays.append(backdrop)
        except Exception as exc:
            log.warning("Hook backdrop band failed (%s); skipping.", exc)

    # --- Big animated hook text with pop entrance ---
    hook_clip = _make_text_clip(
        hook_text,
        fontsize,
        color,
        stroke_color,
        stroke_width,
        font,
        int(W * 0.92),
        duration=hook_dur,
    )
    if hook_clip is not None:
        try:
            def pop(t):
                if t >= pop_in:
                    return 1.0
                frac = t / pop_in if pop_in else 1.0
                # Ease toward an overshoot then settle (simple ease-out + overshoot).
                return overshoot - (overshoot - 1.0) * (1.0 - frac)

            hook_clip = (
                hook_clip.set_start(0)
                .resize(pop)
                .set_position(("center", "center"))
            )
            overlays.append(hook_clip)
        except Exception as exc:
            log.warning("Hook text animation failed (%s); skipping hook text.", exc)
    else:
        log.warning("Hook text could not be rendered; continuing without it.")

    return overlays, punched_bg


# ==========================================================================
# Audio
# ==========================================================================
def _find_music_track():
    """Return path to a RANDOMLY selected music file in assets/music.

    Random selection ensures a different track plays each run (variety).
    Returns None if no tracks are available.
    """
    try:
        tracks = []
        for name in os.listdir(MUSIC_DIR):
            if name == ".gitkeep":
                continue
            if name.lower().endswith((".mp3", ".m4a", ".wav", ".ogg", ".aac")):
                tracks.append(os.path.join(MUSIC_DIR, name))
        if not tracks:
            return None
        chosen = random.choice(tracks)
        log.info("Selected music track: %s (from %d available)", os.path.basename(chosen), len(tracks))
        return chosen
    except Exception:
        return None


def _synth_background_music(duration, fps=44100):
    """Generate a DEVOTIONAL Indian music bed - 4 rotating styles.

    WHY THIS WAS REWRITTEN
    ----------------------
    The version this replaces generated "uplifting anthem" beds - a bright major
    "la la laa" melody, a celebratory 4-beat march, a viral pop hook and an
    Olympic-style swell. That suited the cute-pets channel it was written for.
    Under a Hindi Krishna katha it is actively wrong: a triumphant pop hook
    playing under the story of Gandhari's curse reads as disrespectful, and it is
    the kind of mismatch a viewer notices in the first two seconds even if they
    cannot name it.

    All four styles below are built on a sustained tanpura-style drone (Sa + Pa)
    with a slow bansuri-like melody drawn from a pentatonic raga scale. There is
    no percussion on the downbeat and no rising "anthem" figure, because the
    narration - not the music - is meant to carry the video.

      Style 0 - Bansuri over drone      (Raag Bhoopali: Sa Re Ga Pa Dha)
      Style 1 - Temple morning          (drone + soft distant bell strikes)
      Style 2 - Sandhya aarti           (deeper drone, slow sustained melody)
      Style 3 - Meditative drone        (almost no melody, gentle swells)

    Drop real .mp3 files in assets/music to override this entirely.
    """
    try:
        import numpy as np
        from moviepy.audio.AudioClip import AudioArrayClip

        duration = float(max(1.0, duration))
        n = int(duration * fps)
        t = np.linspace(0.0, duration, n, endpoint=False)
        style = random.randint(0, 3)
        log.info("Devotional music style: %d", style)

        # Sa = C3 (low, so it sits under a male narration voice rather than
        # fighting it). Ratios are just intonation, which is how a tanpura is
        # actually tuned - equal temperament sounds subtly "off" for this.
        SA = 130.81
        RE = SA * 9 / 8
        GA = SA * 5 / 4
        MA = SA * 4 / 3
        PA = SA * 3 / 2
        DHA = SA * 5 / 3
        SA_HI = SA * 2

        def drone(amount=0.30):
            """Tanpura-ish: Sa + Pa + Sa-octave, very slowly beating."""
            d = np.zeros(n)
            for freq, gain in ((SA, 1.0), (PA, 0.55), (SA_HI, 0.35)):
                # Two detuned voices per note give the slow shimmer a real
                # tanpura has; a single sine sounds like a test tone.
                d += gain * np.sin(2 * np.pi * freq * t)
                d += gain * 0.7 * np.sin(2 * np.pi * (freq * 1.0015) * t)
            # Gentle swell so the bed breathes instead of sitting flat.
            d *= 0.85 + 0.15 * np.sin(2 * np.pi * t / 7.0)
            return amount * d / 3.0

        def melody(notes, note_dur, gain=0.30, breath=2.5):
            """Slow flute-like line: soft attack, long decay, no hard onset."""
            idx = (t / note_dur).astype(int) % len(notes)
            freq = np.array([notes[i] for i in idx])
            phase = (t / note_dur) % 1.0
            # Soft attack (a flute does not start instantly) + slow decay.
            attack = np.clip(phase / 0.18, 0.0, 1.0)
            decay = np.exp(-breath * phase)
            env = attack * decay
            # A touch of second harmonic gives it a wooden, airy timbre.
            w = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
            return gain * env * w

        def bells(period=6.0, gain=0.16):
            """Distant temple bell every `period` seconds."""
            phase = t % period
            env = np.exp(-2.2 * phase)
            b = np.sin(2 * np.pi * 1046.50 * t) + 0.6 * np.sin(2 * np.pi * 1567.98 * t)
            return gain * env * b

        if style == 0:
            # Raag Bhoopali (Sa Re Ga Pa Dha) - the classic evening pentatonic.
            wave = drone(0.30) + melody(
                [SA, RE, GA, PA, DHA, PA, GA, RE], 0.85, gain=0.30
            )
        elif style == 1:
            wave = drone(0.28) + melody([GA, PA, DHA, SA_HI, DHA, PA], 1.0, gain=0.24)
            wave += bells(period=6.5)
        elif style == 2:
            # Slower, lower, more solemn - for the heavier leelas.
            wave = drone(0.34) + melody([SA, GA, MA, PA, MA, GA], 1.35, gain=0.22, breath=1.6)
        else:
            # Nearly pure drone. The quietest option, and the safest bed under a
            # narration that is doing all the work.
            wave = drone(0.38) + melody([SA, PA, SA_HI], 3.0, gain=0.12, breath=1.0)

        # Normalise, then fade in/out so the bed never clicks at a cut.
        peak = float(np.max(np.abs(wave))) or 1.0
        wave = wave / peak * 0.9
        fade_in = min(int(1.2 * fps), n // 4)
        fade_out = min(int(1.5 * fps), n // 4)
        if fade_in > 0:
            wave[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
        if fade_out > 0:
            wave[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

        stereo = np.column_stack([wave, wave]).astype(np.float32)
        clip = AudioArrayClip(stereo, fps=fps).set_duration(duration)
        log.info("Synthesized %.1fs devotional music (style %d).", duration, style)
        return clip

    except Exception as exc:
        log.warning("Music synthesis failed (%s); silent audio.", exc)
        return None


def _synth_hook_sting(duration=2.5, fps=44100):
    """Short devotional accent for the hook window (first ~2.5s).

    WHY THIS WAS REWRITTEN
    ----------------------
    The previous sting was a rising "whoosh + chime" or a "low punch + sparkle" -
    a trailer-style impact. Over the opening of a Krishna katha that sounds like
    a gaming montage. Replaced with two accents that belong to this niche:

      Flavour 0 - Temple bell (ghanti): a struck bell with its natural
                  inharmonic partials, ringing out over ~2s.
      Flavour 1 - Conch (shankh): a breathy sustained tone with a soft swell,
                  the sound that traditionally opens a recitation.

    Kept quiet and short - it marks the opening, it does not announce it.
    """
    try:
        import numpy as np
        from moviepy.audio.AudioClip import AudioArrayClip

        n = int(duration * fps)
        t = np.linspace(0.0, duration, n, endpoint=False)
        flavour = random.randint(0, 1)

        if flavour == 0:
            # Temple bell. A real bell's overtones are NOT integer multiples of
            # the fundamental - that inharmonicity is what makes it read as metal
            # rather than as a sine beep, so the ratios below are deliberate.
            fundamental = 523.25
            partials = ((1.0, 1.0, 3.0), (2.76, 0.5, 4.5), (5.40, 0.25, 6.0),
                        (8.93, 0.12, 8.0))
            wave = np.zeros(n)
            for ratio, gain, decay in partials:
                wave += gain * np.exp(-decay * t) * np.sin(2 * np.pi * fundamental * ratio * t)
            # Slow tremolo as the bell body rings.
            wave *= 1.0 + 0.05 * np.sin(2 * np.pi * 4.5 * t)
        else:
            # Conch: a low breathy tone that swells in, plus filtered noise for
            # the breath. Attack is slow on purpose - a shankh has no transient.
            base = 233.08
            swell = np.clip(t / 0.45, 0.0, 1.0) * np.exp(-1.1 * np.maximum(t - 0.45, 0))
            wave = swell * (
                np.sin(2 * np.pi * base * t)
                + 0.45 * np.sin(2 * np.pi * base * 2 * t)
                + 0.20 * np.sin(2 * np.pi * base * 3 * t)
            )
            # Breath noise, smoothed so it is air rather than hiss.
            rng_local = np.random.default_rng()
            noise = rng_local.normal(0.0, 1.0, n)
            kernel = np.ones(64) / 64.0
            noise = np.convolve(noise, kernel, mode="same")
            wave += 0.10 * swell * noise

        peak = float(np.max(np.abs(wave))) or 1.0
        wave = wave / peak
        fade = min(int(0.5 * fps), n // 3)
        if fade > 0:
            wave[-fade:] *= np.linspace(1.0, 0.0, fade)

        stereo = np.column_stack([wave, wave]).astype(np.float32)
        return AudioArrayClip(stereo, fps=fps).set_duration(duration)
    except Exception as exc:
        log.warning("Hook sting synthesis failed (%s); skipping.", exc)
        return None


def _build_music_only_audio(duration):
    """Build a music-only audio track: soft background bed + punchy hook sting.

    The hook sting plays at t=0 for ~2.5s (while the hook text is on screen),
    giving a satisfying 'arrival' accent. The background bed runs the full
    duration at a lower volume so it never feels overwhelming.
    """
    from moviepy.editor import CompositeAudioClip
    from moviepy.audio.fx.all import audio_loop, volumex

    tracks = []

    # --- Background music bed (soft) ---
    if get_cfg("music.enabled", True):
        music_path = _find_music_track()
        bed = None
        if music_path:
            try:
                from moviepy.editor import AudioFileClip
                vol = float(get_cfg("music.volume", 0.22))
                music = AudioFileClip(music_path)
                music = volumex(music, vol)
                try:
                    music = audio_loop(music, duration=duration)
                except Exception:
                    music = music.set_duration(min(music.duration, duration))
                bed = music.set_duration(duration)
                log.info("Music bed: real track at %.0f%% vol: %s", vol * 100, os.path.basename(music_path))
            except Exception as exc:
                log.warning("Could not load music file (%s); trying synth.", exc)

        if bed is None and get_cfg("music.synth_fallback", True):
            try:
                synth = _synth_background_music(duration)
                if synth is not None:
                    vol = float(get_cfg("music.synth_volume", 0.65))
                    bed = volumex(synth, vol).set_duration(duration)
                    log.info("Music bed: synth at %.0f%% vol.", vol * 100)
            except Exception as exc:
                log.warning("Synth music failed (%s).", exc)

        if bed is not None:
            tracks.append(bed)

    # --- Hook sting (punchy accent at t=0) ---
    if get_cfg("music.hook_sting_enabled", True):
        try:
            sting = _synth_hook_sting(duration=min(2.5, duration * 0.35))
            if sting is not None:
                vol = float(get_cfg("music.hook_sting_volume", 0.55))
                sting = volumex(sting, vol).set_start(0)
                tracks.append(sting)
                log.info("Hook sting added at t=0 (%.0f%% vol).", vol * 100)
        except Exception as exc:
            log.warning("Hook sting failed (%s); skipping.", exc)

    if not tracks:
        log.warning("No audio tracks built; silent reel.")
        return None
    if len(tracks) == 1:
        return tracks[0].set_duration(duration)
    try:
        return CompositeAudioClip(tracks).set_duration(duration)
    except Exception as exc:
        log.warning("Audio composite failed (%s); using bed only.", exc)
        return tracks[0].set_duration(duration)


def _build_audio(voice_path, duration):
    """Build the final audio track.

    Audio = voiceover (+ optional low-volume background music if a track exists
    in assets/music). Returns an AudioClip or None if the voiceover is missing.
    """
    from moviepy.editor import AudioFileClip, CompositeAudioClip
    from moviepy.audio.fx.all import audio_loop, volumex

    if not voice_path or not os.path.exists(voice_path):
        log.error("Voiceover file missing (%s); cannot build audio.", voice_path)
        return None

    try:
        voice = AudioFileClip(voice_path)
    except Exception as exc:
        log.error("Could not open voiceover (%s).", exc)
        return None

    tracks = [voice]

    if get_cfg("music.enabled", True):
        music_path = _find_music_track()
        if music_path:
            try:
                vol = float(get_cfg("music.volume", 0.13))
                music = AudioFileClip(music_path)
                music = volumex(music, vol)
                # Loop/trim music to match the voiceover duration.
                try:
                    music = audio_loop(music, duration=voice.duration)
                except Exception:
                    music = music.set_duration(min(music.duration, voice.duration))
                tracks.append(music)
                log.info("Mixed background music at %.0f%% volume: %s", vol * 100, os.path.basename(music_path))
            except Exception as exc:
                log.warning("Could not mix music (%s); voiceover only.", exc)
        elif get_cfg("music.synth_fallback", True):
            # No music file: synthesize a gentle ambient bed so the reel isn't
            # flat/silent. Quieter than a real track (it's a soft pad).
            try:
                synth = _synth_background_music(voice.duration)
                if synth is not None:
                    vol = float(get_cfg("music.synth_volume", 0.10))
                    tracks.append(volumex(synth, vol))
                    log.info("Mixed synthesized ambient music at %.0f%% volume.", vol * 100)
            except Exception as exc:
                log.warning("Could not mix synth music (%s); voiceover only.", exc)

    if len(tracks) == 1:
        return voice
    try:
        return CompositeAudioClip(tracks).set_duration(voice.duration)
    except Exception as exc:
        log.warning("Audio mix failed (%s); using voiceover only.", exc)
        return voice


# ==========================================================================
# Public API
# ==========================================================================
def compose_video(voice_path, text, keywords, hook_text=None, out_path=None,
                  flashes=None, scene_prompts=None):
    """Compose the full reel and write it to disk. Returns the output path.

    Parameters
    ----------
    voice_path    : str   Path to the Hindi narration mp3 (required).
    text          : str   The narration text (used only if captions are enabled).
    keywords      : list  ATMOSPHERE footage searches (river, peacock, diya...).
                          NOT the story subject - there is no stock footage of
                          Krishna, so the story is carried by scene_prompts.
    hook_text     : str   Short on-screen Hindi label for the first ~2.5s.
    flashes       : list  Short Hindi phrases flashed mid-video.
    scene_prompts : list  ENGLISH image prompts, one per story beat. These become
                          the generated frames that actually depict the leela.
    out_path      : str   Output mp4 path (optional; auto-named if omitted).
    """
    from moviepy.editor import AudioFileClip, CompositeVideoClip

    voice_enabled = get_cfg("video.voice_enabled", True)

    if voice_enabled:
        if not voice_path or not os.path.exists(voice_path):
            raise FileNotFoundError("Voiceover not found: %s" % voice_path)
        # Determine duration from the voiceover.
        probe = AudioFileClip(voice_path)
        duration = float(probe.duration or get_cfg("video.target_duration_seconds", 30))
        probe.close()
    else:
        log.info("Voice DISABLED — music-only montage mode.")
        # Duration comes from config (not voiceover length).
        duration = float(get_cfg("video.target_duration_seconds", 30))

    duration = max(float(get_cfg("video.min_duration_seconds", 20)), duration)
    duration = min(float(get_cfg("video.max_duration_seconds", 35)), duration)
    log.info("Target reel duration: %.2fs (voice_enabled=%s)", duration, voice_enabled)

    # 1) Background: generated leela scenes interleaved with real atmosphere.
    background = _build_background(keywords, duration, scene_prompts=scene_prompts)
    background = background.set_duration(duration)

    # 1b) Bright/punchy color grade directly on the background (kills the
    # faded look). Defensive: returns the background unchanged on failure.
    if get_cfg("grade.enabled", True):
        background = _apply_color_grade(background)
        background = background.set_duration(duration)

    # 2) Hook overlay (+ background punch) for the first ~5s.
    suppress_captions_during_hook = get_cfg("hook.suppress_captions", True)
    hook_dur = float(get_cfg("hook.duration_seconds", 5.0))
    hook_overlays, background = _build_hook_clips(hook_text, background)
    background = background.set_duration(duration)

    layers = [background]

    # 2b) Subtle finish (very light tint + far-corner vignette) on top of the
    # graded background, below captions/hook so text stays crisp and readable.
    if get_cfg("grade.enabled", True):
        layers.extend(_build_cinematic_grade(duration))

    # 3) Captions (optionally suppressed during the hook window).
    caption_clips = _build_caption_clips(text, duration)
    if hook_overlays and suppress_captions_during_hook:
        kept = []
        for c in caption_clips:
            try:
                if c.start is not None and c.start >= hook_dur:
                    kept.append(c)
            except Exception:
                kept.append(c)
        caption_clips = kept
    layers.extend(caption_clips)

    # 3b) Mid-video flash phrases. These are what replaced the rolling captions:
    # a muted viewer still gets something to read, but the subject stays clear.
    layers.extend(_build_flash_clips(flashes, duration, start_after=hook_dur))

    # 4) Hook overlays go on top.
    layers.extend(hook_overlays)

    video = CompositeVideoClip(layers, size=(W, H)).set_duration(duration)

    # 5) Audio — voice OR music-only depending on config.
    if voice_enabled:
        audio = _build_audio(voice_path, duration)
    else:
        audio = _build_music_only_audio(duration)
    if audio is not None:
        video = video.set_audio(audio)

    # 6) Write out.
    if out_path is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        stamp = random.randint(1000, 9999)
        out_path = os.path.join(OUTPUT_DIR, "krishna_%d.mp4" % stamp)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    log.info("Rendering reel -> %s", out_path)
    # High-quality encoding: ~6 Mbps bitrate, yuv420p for broad compatibility.
    write_kwargs = dict(
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        threads=4,
        preset=get_cfg("video.preset", "medium"),
        verbose=False,
        logger=None,
    )
    try:
        # Prefer CONSTANT-QUALITY (CRF) encoding: it allocates as many bits as
        # the footage needs so high-motion cute clips stay crisp instead of
        # going blocky/pixelated at a fixed low bitrate. CRF ~18-21 is visually
        # lossless-ish; lower = higher quality + bigger file.
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        crf = get_cfg("video.crf", 20)
        if crf is not None:
            ffmpeg_params += ["-crf", str(int(crf))]
            # With CRF active, do NOT also pass a target bitrate (it would
            # override constant-quality). Keep an optional high ceiling only.
            bitrate = get_cfg("video.bitrate", None)
            if bitrate:
                ffmpeg_params += ["-maxrate", str(bitrate), "-bufsize", "24000k"]
        else:
            bitrate = get_cfg("video.bitrate", "12000k")
            if bitrate:
                write_kwargs["bitrate"] = bitrate
        write_kwargs["ffmpeg_params"] = ffmpeg_params
    except Exception as exc:
        log.warning("Could not set HQ encoding params (%s); using defaults.", exc)

    try:
        video.write_videofile(out_path, **write_kwargs)
    except Exception as exc:
        log.warning("HQ write failed (%s); retrying with safe defaults.", exc)
        video.write_videofile(
            out_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            preset="medium",
            ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "18"],
            verbose=False,
            logger=None,
        )
    try:
        video.close()
    except Exception:
        pass
    log.info("Reel written: %s", out_path)
    return out_path
