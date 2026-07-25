"""
Video composition for Krishna Universe Katha.

Assembles a 5-7 minute LANDSCAPE 1920x1080 HD moral-story video:
  * Background built from a priority chain (Pexels LANDSCAPE video clips with
    scene-switching fast-ish cuts + crossfades -> calm animated gradient).
  * A subtle bright/clean color grade so footage looks crisp.
  * An INTRO title card overlay for the first few seconds (story title + hook).
  * Full-length readable CAPTIONS with a soft rounded backdrop pill so kids can
    follow the story clearly.
  * An OUTRO call-to-action overlay for the last few seconds.
  * Audio = narration voiceover + soft background music bed.

Heavy imports (moviepy/numpy) happen lazily inside functions so importing this
module never hard-fails in restricted environments.
"""

# ---------------------------------------------------------------------------
# Pillow >= 10 removed Image.ANTIALIAS which moviepy 1.0.3 relies on. Re-add the
# constants BEFORE moviepy is ever imported.
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
from . import pexels_video
from . import subtitles
from . import textrender

log = logging.getLogger("krishna.video")

W = get_cfg("video.width", 1920)
H = get_cfg("video.height", 1080)
FPS = get_cfg("video.fps", 30)


# ==========================================================================
# Background construction
# ==========================================================================
def _fit_cover(clip, target_w=None, target_h=None):
    """Resize+crop a clip so it covers the target frame (no letterboxing).

    target_w/target_h default to the output frame. The motion engine passes a
    deliberately LARGER target so there is spare image to pan across.
    """
    tw = int(target_w or W)
    th = int(target_h or H)
    from moviepy.video.fx.all import crop

    try:
        cw, ch = clip.size
    except Exception:
        return clip.resize((tw, th))

    scale = max(tw / float(cw), th / float(ch))
    new_w = int(cw * scale)
    new_h = int(ch * scale)
    new_w += new_w % 2
    new_h += new_h % 2
    clip = clip.resize((new_w, new_h))
    try:
        clip = crop(clip, width=tw, height=th, x_center=new_w / 2, y_center=new_h / 2)
    except Exception:
        clip = clip.resize((tw, th))
    return clip


def _concat_with_crossfade(segments, duration):
    """Concatenate clips with short crossfade transitions; defensive fallback."""
    from moviepy.editor import concatenate_videoclips

    if not segments:
        raise RuntimeError("No segments to concatenate.")

    xfade = float(get_cfg("transitions.crossfade_seconds", 0.4))
    if len(segments) > 1 and xfade > 0:
        try:
            try:
                from moviepy.video.compositing.transitions import crossfadein as _xfn
            except Exception:
                _xfn = None
            faded = [segments[0]]
            for seg in segments[1:]:
                try:
                    seg_dur = seg.duration or xfade
                except Exception:
                    seg_dur = xfade
                this_fade = min(xfade, max(0.05, seg_dur * 0.5))
                faded.append(_xfn(seg, this_fade) if _xfn else seg.crossfadein(this_fade))
            bg = concatenate_videoclips(faded, method="compose", padding=-xfade)
            return bg.set_duration(duration)
        except Exception as exc:
            log.warning("Crossfade concat failed (%s); using plain concat.", exc)

    return concatenate_videoclips(segments, method="compose").set_duration(duration)


def _video_background(clip_paths, duration, ordered=False):
    """Scene-switching background: cut each clip to a few seconds and chain them
    with crossfades until the full story duration is filled.

    ordered=True keeps the clips in scene order (no shuffle) so the footage
    follows the storyline beat-by-beat (boy -> dog -> river -> ...). ordered=
    False shuffles for generic variety.
    """
    from moviepy.editor import VideoFileClip

    cut = float(get_cfg("video.clip_cut_seconds", 7.0))
    xfade = float(get_cfg("transitions.crossfade_seconds", 0.4))
    order = list(clip_paths)
    if not ordered:
        random.shuffle(order)

    segments, total, idx, guard = [], 0.0, 0, 0
    max_segments = int(duration / max(1.5, cut)) + 8
    while order and guard < 400 and len(segments) < max_segments:
        effective = total - max(0, len(segments) - 1) * xfade
        if effective >= duration:
            break
        guard += 1
        path = order[idx % len(order)]
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
        seg = _fit_cover(vc.subclip(0, seg_dur))
        segments.append(seg)
        total += seg_dur
    if not segments:
        raise RuntimeError("No usable video segments.")
    return _concat_with_crossfade(segments, duration).set_duration(duration)


def _gradient_background(duration):
    """Calm animated dark-blue gradient (last resort, always works)."""
    import numpy as np
    from moviepy.editor import VideoClip, ColorClip

    top = np.array(get_cfg("palette.gradient_top", [25, 32, 64]), dtype=np.float64)
    bottom = np.array(get_cfg("palette.gradient_bottom", [10, 12, 28]), dtype=np.float64)
    try:
        ramp = np.linspace(0.0, 1.0, H, dtype=np.float64).reshape(H, 1, 1)
        base = top.reshape(1, 1, 3) * (1.0 - ramp) + bottom.reshape(1, 1, 3) * ramp

        def make_frame(t):
            phase = 0.5 + 0.5 * np.sin(2.0 * np.pi * t / 10.0)
            frame = base * (0.92 + 0.08 * phase)
            frame = np.clip(frame, 0, 255).astype("uint8")
            return np.broadcast_to(frame, (H, W, 3)).copy()

        clip = VideoClip(make_frame, duration=duration).set_fps(FPS)
        log.info("Background source: calm gradient (last resort).")
        return clip
    except Exception as exc:
        log.warning("Gradient generation failed (%s); using solid color.", exc)
        solid = get_cfg("palette.solid_fallback", [16, 20, 40])
        return ColorClip(size=(W, H), color=tuple(solid)).set_duration(duration)


# LONG-FORM MOVE SET - deliberately different from the Shorts one.
#
# A per-frame resize is by far the most expensive thing in the render, and a
# 6-8 minute katha is ~11,700 frames against a Short's ~900. Making every shot
# zoom (as the Shorts engine does) would push this job past its 90-minute
# timeout.
#
# So half of these are PURE TRANSLATIONS, which skip the resize entirely, and
# half carry a zoom. Alternating them still reads as camera work - the failure
# mode was never "not enough zoom", it was every frame being completely static
# (ai_images.motion defaulted to false, so the katha was a crossfaded photo
# sequence).
_MOVES = (
    "pan_left", "push_in",
    "tilt_down", "diag_dr_out",
    "pan_right", "pull_out",
    "tilt_up", "diag_ul_in",
)


def _ease(f):
    """Ease-in-out. A linear move starts and stops abruptly, which looks
    mechanical; real camera moves accelerate and settle."""
    return f * f * (3.0 - 2.0 * f)


def _motion_from_image(path, duration, move=None):
    """Animate a still with a combined pan + zoom. Returns a WxH clip.

    HOW IT WORKS
    ------------
    ai_images already delivers the frame at the OVERSCANNED size, so there are
    spare pixels outside the visible area and nothing needs upscaling here. The
    clip is translated inside a WxH composite while being scaled, so pixels move
    across the frame AND the framing tightens or opens at the same time.

    The move is eased rather than linear, and every move carries a zoom, so no
    segment sits still.
    """
    from moviepy.editor import CompositeVideoClip, ImageClip

    if move is None:
        move = random.choice(_MOVES)

    over = float(get_cfg("motion.overscan", 1.18))
    zoom = float(get_cfg("motion.zoom_amount", 0.16))
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

    slack_x = max(0, ow - W)
    slack_y = max(0, oh - H)
    cx = -slack_x / 2.0
    cy = -slack_y / 2.0

    def frac(t):
        return _ease(min(1.0, max(0.0, (t / duration) if duration else 0.0)))

    # Direction of travel for this move, as a fraction of the available slack.
    dx, dy = 0.0, 0.0
    if "pan_left" in move or "diag_ul" in move:
        dx = -1.0
    elif "pan_right" in move or "diag_dr" in move:
        dx = 1.0
    if "tilt_up" in move or "diag_ul" in move:
        dy = -1.0
    elif "tilt_down" in move or "diag_dr" in move:
        dy = 1.0

    zooming_in = move.endswith("_in") or move == "push_in"
    # A move with no _in/_out suffix is a pure translation: skip moviepy's
    # per-frame resize, which is the single most expensive operation here.
    has_zoom = move.endswith("_in") or move.endswith("_out")

    try:
        def scale(t):
            f = frac(t)
            return 1.0 + zoom * f if zooming_in else (1.0 + zoom) - zoom * f

        def pos(t):
            f = frac(t)
            return (cx + dx * (slack_x / 2.0) * f,
                    cy + dy * (slack_y / 2.0) * f)

        seg = base.resize(scale) if has_zoom else base
        # A pure zoom stays centred; anything with travel uses the position fn.
        seg = seg.set_position(("center", "center")) if (dx == 0.0 and dy == 0.0) \
            else seg.set_position(pos)
        return CompositeVideoClip([seg], size=(W, H)).set_duration(duration)
    except Exception as exc:
        log.warning("Motion move %r failed for %s (%s); using static frame.",
                    move, path, exc)
        try:
            return _fit_cover(ImageClip(path).set_duration(duration))
        except Exception:
            return None


def _images_background(image_paths, duration):
    """Ken-Burns slideshow background from AI scene images, crossfaded, filling
    the full story duration (images shown in order, looped if needed)."""
    if not image_paths:
        raise RuntimeError("No images for background.")
    xfade = float(get_cfg("transitions.crossfade_seconds", 0.4))
    per = max(2.0, min(float(get_cfg("video.scene_cut_seconds", 4.0)),
                       duration / max(1, len(image_paths))))
    clips, total, idx, guard = [], 0.0, 0, 0
    while guard < 400:
        effective = total - max(0, len(clips) - 1) * xfade
        if effective >= duration:
            break
        guard += 1
        path = image_paths[idx % len(image_paths)]
        idx += 1
        seg_dur = min(per, duration - effective)
        if seg_dur <= 0:
            break
        seg = _motion_from_image(path, seg_dur, move=_MOVES[(idx - 1) % len(_MOVES)])
        if seg is None:
            continue
        clips.append(seg)
        total += seg_dur
    if not clips:
        raise RuntimeError("No motion clips built.")
    return _concat_with_crossfade(clips, duration).set_duration(duration)


def _mixed_background(image_paths, clip_paths, duration):
    """Interleave AI character images (static) with scene footage clips, IN
    ORDER, crossfaded - so the character appears through the video AND the
    visuals stay varied/non-repeating even when only a few AI images succeed.
    """
    from moviepy.editor import VideoFileClip, ImageClip

    cut = float(get_cfg("video.clip_cut_seconds", 3.0))
    # Build an interleaved, ordered asset list: img, clip, img, clip ...
    assets = []  # (kind, path)
    imgs = list(image_paths or [])
    clips = list(clip_paths or [])
    i = j = 0
    while i < len(imgs) or j < len(clips):
        if i < len(imgs):
            assets.append(("img", imgs[i])); i += 1
        if j < len(clips):
            assets.append(("clip", clips[j])); j += 1
    if not assets:
        raise RuntimeError("No mixed assets.")

    segments, total, idx, guard = [], 0.0, 0, 0
    max_segments = int(duration / max(1.5, cut)) + 10
    while guard < 600 and len(segments) < max_segments:
        xfade = float(get_cfg("transitions.crossfade_seconds", 0.4))
        if total - max(0, len(segments) - 1) * xfade >= duration:
            break
        guard += 1
        kind, path = assets[idx % len(assets)]
        idx += 1
        try:
            if kind == "img":
                seg_dur = float(get_cfg("video.scene_cut_seconds", 4.0))
                seg = _motion_from_image(path, seg_dur,
                                        move=_MOVES[(idx - 1) % len(_MOVES)])
                if seg is None:
                    continue
            else:
                vc = VideoFileClip(path, audio=False)
                seg_dur = min(cut, vc.duration or cut)
                if seg_dur <= 0:
                    vc.close(); continue
                seg = _fit_cover(vc.subclip(0, seg_dur))
            segments.append(seg)
            # Add the ACTUAL segment length, not `cut`. A real clip shorter than
            # `cut` used to be counted as a full `cut`, so the loop believed it
            # had covered more time than it had and the background came out
            # SHORT of the narration - leaving the tail of the story over a
            # stretched or looped final shot.
            total += seg_dur
        except Exception as exc:
            log.warning("Mixed segment failed (%s); skipping.", exc)
            continue
    if not segments:
        raise RuntimeError("No mixed segments built.")
    return _concat_with_crossfade(segments, duration).set_duration(duration)


def _build_background(keywords, duration, image_paths=None, clip_paths=None):
    # (0) BOTH AI character images + scene footage -> mixed (best free result:
    # character shows through the video, footage keeps it varied/non-repeating).
    if image_paths and clip_paths:
        log.info("Background source: MIXED AI images (%d) + scene footage (%d).",
                 len(image_paths), len(clip_paths))
        try:
            return _mixed_background(image_paths, clip_paths, duration)
        except Exception as exc:
            log.warning("Mixed background failed (%s); trying images only.", exc)
    # (0a) Only AI scene images.
    if image_paths:
        log.info("Background source: AI scene images (%d).", len(image_paths))
        try:
            return _images_background(image_paths, duration)
        except Exception as exc:
            log.warning("AI-image background failed (%s); trying scene footage.", exc)
    # (0b) Only scene-matched footage IN ORDER.
    if clip_paths:
        log.info("Background source: scene-matched footage IN ORDER (%d).", len(clip_paths))
        try:
            return _video_background(clip_paths, duration, ordered=True)
        except Exception as exc:
            log.warning("Scene footage build failed (%s); trying keyword footage.", exc)
    # (1) Pexels stock VIDEO clips (keyword-based, shuffled).
    try:
        clips = pexels_video.fetch_clips(keywords)
        if clips:
            log.info("Background source: Pexels VIDEO clips (%d).", len(clips))
            try:
                return _video_background(clips, duration)
            except Exception as exc:
                log.warning("Video background build failed (%s); using gradient.", exc)
    except Exception as exc:
        log.warning("Pexels video fetch error (%s); using gradient.", exc)
    # (2) Calm gradient (always works).
    return _gradient_background(duration)


# ==========================================================================
# Color grade
# ==========================================================================
def _apply_color_grade(clip):
    try:
        from moviepy.video.fx.all import colorx, lum_contrast
    except Exception as exc:
        log.warning("Color grade fx unavailable (%s); ungraded background.", exc)
        return clip
    saturation = float(get_cfg("grade.saturation", 1.1))
    brightness = float(get_cfg("grade.brightness", 6))
    contrast = float(get_cfg("grade.contrast", 0.08))
    graded = clip
    try:
        graded = colorx(graded, saturation)
    except Exception as exc:
        log.warning("colorx failed (%s); skipping.", exc)
    try:
        graded = lum_contrast(graded, lum=brightness, contrast=contrast)
    except Exception as exc:
        log.warning("lum_contrast failed (%s); skipping.", exc)
    return graded


# ==========================================================================
# Text helpers
# ==========================================================================
def _make_text_clip(txt, fontsize, color, stroke_color, stroke_width, font, max_w,
                    duration=1.0):
    """Render text via Pillow instead of moviepy's TextClip.

    WHY NOT TextClip: it shells out to ImageMagick, which fails for Hindi twice
    over. The configured DejaVu font contains no Devanagari glyphs, so every word
    renders as an empty box; and ImageMagick's label/caption operators do not run
    a complex-text shaper, so matras and conjuncts land in the wrong places even
    with a correct font. Neither raises an error - it silently renders garbage.
    modules/textrender uses Pillow, whose wheels bundle libraqm and therefore
    shape Devanagari correctly.

    `font` is accepted and ignored so existing call sites need no changes.
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
    try:
        s = str(value).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return default
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return default


def _make_backdrop(tw, th, start, seg_dur, y_top, opacity, color, rounded=True):
    """Build a semi-transparent rounded pill sized to the text. Defensive."""
    try:
        import numpy as np
        from moviepy.editor import ColorClip, ImageClip

        if opacity <= 0:
            return None
        pad_x = max(28, int(tw * 0.05))
        pad_y = max(16, int(th * 0.25))
        w = int(tw + 2 * pad_x)
        h = int(th + 2 * pad_y)
        if w <= 2 or h <= 2:
            return None
        alpha = np.ones((h, w), dtype=np.float64) * opacity
        if rounded:
            radius = int(min(h // 2, 40))
            if radius > 0:
                yy, xx = np.ogrid[0:h, 0:w]
                dx = np.minimum(xx, w - 1 - xx)
                dy = np.minimum(yy, h - 1 - yy)
                in_corner = (dx < radius) & (dy < radius)
                dist = np.sqrt((radius - dx) ** 2 + (radius - dy) ** 2)
                alpha[in_corner & (dist > radius)] = 0.0
        mask = ImageClip(alpha, ismask=True).set_duration(seg_dur)
        return (
            ColorClip(size=(w, h), color=color)
            .set_duration(seg_dur).set_mask(mask)
            .set_start(start).set_position(("center", int(y_top - pad_y)))
        )
    except Exception as exc:
        log.warning("Backdrop build failed (%s); text only.", exc)
        return None


# ==========================================================================
# Captions (full length)
# ==========================================================================
def _build_film_grain(duration):
    """A faint moving grain layer over the whole reel.

    WHY: generated frames are unnaturally CLEAN - no sensor noise, no texture -
    and that cleanliness is a large part of why animated stills read as a
    slideshow rather than as footage. A little moving grain gives every frame
    something that changes even when the camera move is slow, and it is the
    cheapest cinematic cue available.

    Deliberately generated at a fraction of the frame size and scaled up, so the
    grain is soft rather than a pixel-level fizz, and so it costs almost nothing.
    """
    if not get_cfg("grain.enabled", True):
        return []
    try:
        import numpy as np
        from moviepy.editor import VideoClip

        strength = float(get_cfg("grain.opacity", 0.07))
        if strength <= 0:
            return []
        small_w = max(8, W // 6)
        small_h = max(8, H // 6)
        rng = np.random.default_rng(random.randint(1, 1_000_000))
        # A handful of pre-rendered plates cycled over time: regenerating noise
        # every frame is slow, and a fixed plate would look like a dirty lens.
        plates = [rng.normal(128, 34, (small_h, small_w)).clip(0, 255).astype("uint8")
                  for _ in range(6)]

        def make_frame(t):
            plate = plates[int(t * 12) % len(plates)]
            return np.dstack([plate] * 3)

        grain = VideoClip(make_frame, duration=duration)
        grain = grain.resize((W, H)).set_opacity(strength)
        log.info("Film grain layer at %.0f%% opacity.", strength * 100)
        return [grain]
    except Exception as exc:
        log.warning("Film grain failed (%s); skipping.", exc)
        return []


def _build_caption_clips(text, duration, skip_before=0.0):
    if not get_cfg("captions.enabled", True):
        return []
    groups = subtitles.build_caption_groups(text, duration)
    if not groups:
        return []

    fontsize = get_cfg("captions.fontsize", 56)
    color = get_cfg("captions.color", "white")
    stroke_color = get_cfg("captions.stroke_color", "black")
    stroke_width = get_cfg("captions.stroke_width", 4)
    font = get_cfg("captions.font", "DejaVu-Sans-Bold")
    y_ratio = get_cfg("captions.position_y_ratio", 0.82)
    bg_opacity = float(get_cfg("captions.bg_opacity", 0.4))
    bg_color = _hex_to_rgb(get_cfg("captions.bg_color", "#000000"))
    max_w = int(W * 0.86)
    y_top = int(H * y_ratio)

    clips = []

    # ONE persistent semi-transparent band behind all captions (instead of a
    # separate rounded ColorClip+numpy-mask per caption). This is the key
    # memory fix: the old per-caption backdrops created hundreds of clips +
    # mask arrays and exhausted the runner's RAM mid-render.
    if bg_opacity > 0:
        try:
            from moviepy.editor import ColorClip
            band_h = int(fontsize * 2.6)
            band_start = max(0.0, skip_before)
            band = (
                ColorClip(size=(int(W * 0.92), band_h), color=bg_color)
                .set_opacity(bg_opacity)
                .set_start(band_start)
                .set_duration(max(0.2, duration - band_start))
                .set_position(("center", int(y_top - band_h * 0.28)))
            )
            clips.append(band)
        except Exception as exc:
            log.warning("Caption band failed (%s); text only.", exc)

    for g in groups:
        if g["start"] < skip_before:
            continue
        seg_dur = max(0.2, g["end"] - g["start"])
        tc = _make_text_clip(g["text"], fontsize, color, stroke_color, stroke_width,
                             font, max_w, duration=seg_dur)
        if tc is None:
            continue
        try:
            tc = tc.set_start(g["start"]).set_position(("center", y_top))
        except Exception as exc:
            log.warning("Could not place caption (%s).", exc)
            continue
        clips.append(tc)
    log.info("Built %d caption layer(s) (1 band + text).", len(clips))
    return clips


# ==========================================================================
# Intro / Outro overlays
# ==========================================================================
def _build_intro_clips(title, hook):
    """Big title + hook for the first few seconds."""
    if not get_cfg("intro.enabled", True) or not title:
        return 0.0, []
    dur = float(get_cfg("intro.duration_seconds", 4.0))
    fontsize = int(get_cfg("intro.fontsize", 90))
    overlays = []

    # Dim band so title reads on footage.
    try:
        from moviepy.editor import ColorClip
        band = (
            ColorClip(size=(W, H), color=(0, 0, 0))
            .set_duration(dur).set_opacity(0.45).set_start(0)
        )
        overlays.append(band)
    except Exception as exc:
        log.warning("Intro band failed (%s).", exc)

    # No .upper(): Devanagari has no letter case, so it was a silent no-op that
    # made the code read as though it were shouting.
    title_clip = _make_text_clip(title, fontsize, "#FFD54A", "black", 4,
                                 get_cfg("captions.font", "DejaVu-Sans-Bold"),
                                 int(W * 0.85), duration=dur)
    if title_clip is not None:
        try:
            title_clip = (
                title_clip.set_start(0).set_duration(dur)
                .set_position(("center", int(H * 0.34)))
            )
            overlays.append(title_clip)
        except Exception as exc:
            log.warning("Intro title placement failed (%s).", exc)

    if hook:
        hook_clip = _make_text_clip(hook, int(fontsize * 0.5), "white", "black", 2,
                                    get_cfg("captions.font", "DejaVu-Sans-Bold"),
                                    int(W * 0.8), duration=dur)
        if hook_clip is not None:
            try:
                hook_clip = (
                    hook_clip.set_start(0).set_duration(dur)
                    .set_position(("center", int(H * 0.55)))
                )
                overlays.append(hook_clip)
            except Exception as exc:
                log.warning("Intro hook placement failed (%s).", exc)
    return dur, overlays


def _build_outro_clips(duration):
    """Channel CTA card for the last few seconds."""
    if not get_cfg("outro.enabled", True):
        return []
    dur = float(get_cfg("outro.duration_seconds", 5.0))
    start = max(0.0, duration - dur)
    fontsize = int(get_cfg("outro.fontsize", 64))
    cta = get_cfg("channel.cta", "Subscribe for a new moral story every day!")
    channel = get_cfg("channel.name", "Krishna Universe")
    overlays = []
    try:
        from moviepy.editor import ColorClip
        band = (
            ColorClip(size=(W, H), color=(0, 0, 0))
            .set_duration(dur).set_opacity(0.55).set_start(start)
        )
        overlays.append(band)
    except Exception as exc:
        log.warning("Outro band failed (%s).", exc)

    name_clip = _make_text_clip(channel, int(fontsize * 1.2), "#FFD54A", "black", 4,
                                get_cfg("captions.font", "DejaVu-Sans-Bold"),
                                int(W * 0.85), duration=dur)
    if name_clip is not None:
        try:
            overlays.append(name_clip.set_start(start).set_duration(dur)
                            .set_position(("center", int(H * 0.36))))
        except Exception:
            pass
    cta_clip = _make_text_clip(cta, fontsize, "white", "black", 3,
                               get_cfg("captions.font", "DejaVu-Sans-Bold"),
                               int(W * 0.8), duration=dur)
    if cta_clip is not None:
        try:
            overlays.append(cta_clip.set_start(start).set_duration(dur)
                            .set_position(("center", int(H * 0.55))))
        except Exception:
            pass
    return overlays


# ==========================================================================
# Audio
# ==========================================================================
def _find_music_track():
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
        log.info("Selected music: %s (of %d)", os.path.basename(chosen), len(tracks))
        return chosen
    except Exception:
        return None


def _synth_soft_pad(duration, fps=44100):
    """Generate a soft ambient pad as a music fallback (calm, low volume)."""
    try:
        import numpy as np
        from moviepy.audio.AudioClip import AudioArrayClip

        duration = float(max(1.0, duration))
        n = int(duration * fps)
        t = np.linspace(0.0, duration, n, endpoint=False)
        # Gentle major chord (C-E-G) with slow tremolo.
        chord = [130.81, 164.81, 196.00]
        wave = np.zeros(n)
        for f in chord:
            wave += np.sin(2 * np.pi * f * t)
        wave /= len(chord)
        tremolo = 0.85 + 0.15 * np.sin(2 * np.pi * t / 6.0)
        wave *= tremolo
        peak = float(np.max(np.abs(wave))) or 1.0
        wave /= peak
        fade = min(int(2.0 * fps), n // 6)
        if fade > 0:
            wave[:fade] *= np.linspace(0.0, 1.0, fade)
            wave[-fade:] *= np.linspace(1.0, 0.0, fade)
        stereo = np.column_stack([wave, wave]).astype(np.float32)
        return AudioArrayClip(stereo, fps=fps).set_duration(duration)
    except Exception as exc:
        log.warning("Soft pad synthesis failed (%s).", exc)
        return None


def _build_audio(voice_path, duration):
    from moviepy.editor import AudioFileClip, CompositeAudioClip
    from moviepy.audio.fx.all import audio_loop, volumex

    if not voice_path or not os.path.exists(voice_path):
        log.error("Voiceover file missing (%s).", voice_path)
        return None
    try:
        voice = AudioFileClip(voice_path)
    except Exception as exc:
        log.error("Could not open voiceover (%s).", exc)
        return None

    tracks = [voice]
    if get_cfg("music.enabled", True):
        music_path = _find_music_track()
        bed = None
        if music_path:
            try:
                vol = float(get_cfg("music.volume", 0.12))
                music = volumex(AudioFileClip(music_path), vol)
                try:
                    music = audio_loop(music, duration=voice.duration)
                except Exception:
                    music = music.set_duration(min(music.duration, voice.duration))
                bed = music
                log.info("Music bed: real track at %.0f%% vol.", vol * 100)
            except Exception as exc:
                log.warning("Could not mix music (%s).", exc)
        if bed is None and get_cfg("music.synth_fallback", True):
            synth = _synth_soft_pad(voice.duration)
            if synth is not None:
                vol = float(get_cfg("music.synth_volume", 0.08))
                bed = volumex(synth, vol)
                log.info("Music bed: synth pad at %.0f%% vol.", vol * 100)
        if bed is not None:
            tracks.append(bed)

    if len(tracks) == 1:
        return voice
    try:
        return CompositeAudioClip(tracks).set_duration(voice.duration)
    except Exception as exc:
        log.warning("Audio mix failed (%s); voiceover only.", exc)
        return voice


# ==========================================================================
# Public API
# ==========================================================================
def compose_video(voice_path, text, keywords, title=None, hook_text=None, out_path=None, image_paths=None, clip_paths=None):
    """Compose the full long-form video and write it to disk. Returns the path.

    Background priority: AI scene images -> scene-matched footage (in order) ->
    keyword footage -> gradient.
    """
    from moviepy.editor import AudioFileClip, CompositeVideoClip

    if not voice_path or not os.path.exists(voice_path):
        raise FileNotFoundError("Voiceover not found: %s" % voice_path)
    probe = AudioFileClip(voice_path)
    duration = float(probe.duration or get_cfg("video.target_duration_seconds", 360))
    probe.close()

    # Clamp to configured bounds (don't hard-cut narration shorter than it is,
    # but warn if it overshoots the max).
    min_d = float(get_cfg("video.min_duration_seconds", 300))
    max_d = float(get_cfg("video.max_duration_seconds", 460))
    if duration < min_d:
        log.warning("Narration is %.0fs (< target min %.0fs).", duration, min_d)
    if duration > max_d:
        log.warning("Narration is %.0fs (> max %.0fs); video will match voice.", duration, max_d)
    log.info("Story video duration: %.1fs (%.1f min).", duration, duration / 60.0)

    # 1) Background + grade.
    background = _build_background(keywords, duration, image_paths=image_paths, clip_paths=clip_paths).set_duration(duration)
    if get_cfg("grade.enabled", True):
        background = _apply_color_grade(background).set_duration(duration)

    layers = [background]

    # 2) Intro overlay (title + hook).
    intro_dur, intro_overlays = _build_intro_clips(title, hook_text)

    # 3) Captions for the whole story (skip during the intro card window).
    caption_clips = _build_caption_clips(text, duration, skip_before=intro_dur)
    # Cinematic texture under the text layers, over the footage.
    layers.extend(_build_film_grain(duration))
    layers.extend(caption_clips)

    # 4) Intro + outro overlays on top.
    layers.extend(intro_overlays)
    layers.extend(_build_outro_clips(duration))

    video = CompositeVideoClip(layers, size=(W, H)).set_duration(duration)

    # 5) Audio.
    audio = _build_audio(voice_path, duration)
    if audio is not None:
        video = video.set_audio(audio)

    # 6) Write.
    if out_path is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, "moraltale_%d.mp4" % random.randint(1000, 9999))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    log.info("Rendering long-form video -> %s", out_path)
    write_kwargs = dict(
        fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="192k",
        threads=4, preset=get_cfg("video.preset", "medium"), verbose=False, logger=None,
    )
    ffmpeg_params = ["-pix_fmt", "yuv420p"]
    crf = get_cfg("video.crf", 20)
    if crf is not None:
        ffmpeg_params += ["-crf", str(int(crf))]
    write_kwargs["ffmpeg_params"] = ffmpeg_params

    try:
        video.write_videofile(out_path, **write_kwargs)
    except Exception as exc:
        log.warning("HQ write failed (%s); retrying with safe defaults.", exc)
        video.write_videofile(
            out_path, fps=FPS, codec="libx264", audio_codec="aac", threads=4,
            preset="medium", ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "20"],
            verbose=False, logger=None,
        )
    try:
        video.close()
    except Exception:
        pass
    log.info("Video written: %s", out_path)
    return out_path
