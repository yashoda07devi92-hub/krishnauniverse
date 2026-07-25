"""
Text-to-speech for Krishna Universe.

Strategy:
  1. Try edge-tts FIRST (free, high quality Hindi neural voices).
  2. On ANY error - including the HTTP 403 commonly returned to GitHub Actions
     runners - automatically fall back to gTTS (Hindi).

Voice choice note: the channel this was ported from rotated six voices to avoid
sounding mass-produced. A katha channel is different -- a returning listener
expects the same narrator, and that voice IS the brand. So tts.voice_pool here is
deliberately SMALL (a male katha-vachak lead plus one female voice) and the rate
varies instead. Enough variation to avoid a single identical synthetic track
across the library, not so much that the channel loses its voice.

Both engines write the SAME output mp3 path. The engine that was actually used
is logged. An edge-tts output file that ends up empty is treated as a failure
so we still fall back to gTTS.

gTTS is imported lazily so importing this module never hard-fails.
"""

import asyncio
import logging
import os
import random

from .config import get_cfg, get_env
from . import history

log = logging.getLogger("krishna.tts")


def _voice():
    """Pick the narrator voice for this run.

    An explicit TTS_VOICE env var always wins (useful for pinning a voice while
    debugging). Otherwise a voice is drawn from tts.voice_pool so the library
    does not consist of 100+ videos narrated by one identical synthetic voice --
    which reads as mass-produced to viewers and to YouTube alike.
    """
    forced = get_env("TTS_VOICE")
    if forced:
        return forced
    pool = get_cfg("tts.voice_pool", []) or []
    if pool:
        # Drawn through history so the voice actually rotates instead of landing
        # on the same one several days running by chance.
        return history.pick("voices", list(pool))
    return get_cfg("tts.voice", "en-US-AriaNeural")


def _rate():
    """Slightly vary the speaking rate too, so pacing is not identical either."""
    pool = get_cfg("tts.rate_pool", []) or []
    if pool:
        return random.choice(list(pool))
    return get_cfg("tts.rate", "-8%")


def _pitch():
    return get_cfg("tts.pitch", "+0Hz")


def _file_has_audio(path):
    """True if the file exists and is non-trivially sized."""
    try:
        return os.path.exists(path) and os.path.getsize(path) > 1024
    except Exception:
        return False


# --------------------------------------------------------------------------
# edge-tts
# --------------------------------------------------------------------------
async def _edge_tts_async(text, out_path, voice, rate, pitch):
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def _try_edge_tts(text, out_path):
    voice = _voice()
    rate = _rate()
    pitch = _pitch()
    try:
        log.info("Synthesizing voiceover with edge-tts (voice=%s, rate=%s).", voice, rate)
        # Remove any stale file first so an empty result is detectable.
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass

        try:
            asyncio.run(_edge_tts_async(text, out_path, voice, rate, pitch))
        except RuntimeError:
            # An event loop may already be running (rare in CLI use).
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    _edge_tts_async(text, out_path, voice, rate, pitch)
                )
            finally:
                loop.close()

        if _file_has_audio(out_path):
            log.info("edge-tts succeeded -> %s", out_path)
            return True
        log.warning("edge-tts produced an empty file; falling back to gTTS.")
        return False
    except Exception as exc:
        log.warning("edge-tts failed (%s); falling back to gTTS.", exc)
        return False


# --------------------------------------------------------------------------
# gTTS fallback
# --------------------------------------------------------------------------
def _try_gtts(text, out_path):
    try:
        from gtts import gTTS  # lazy import
    except Exception as exc:
        log.error("gTTS is not available (%s).", exc)
        return False

    lang = get_cfg("tts.fallback_lang", "en")
    tld = get_cfg("tts.fallback_tld", "com")
    try:
        log.info("Synthesizing voiceover with gTTS (lang=%s, tld=%s).", lang, tld)
        tts = gTTS(text=text, lang=lang, tld=tld)
        tts.save(out_path)
        if _file_has_audio(out_path):
            log.info("gTTS succeeded -> %s", out_path)
            return True
        log.error("gTTS produced an empty file.")
        return False
    except Exception as exc:
        log.error("gTTS failed (%s).", exc)
        return False


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def synthesize(text, out_path):
    """Generate speech for `text` to `out_path` (mp3).

    Returns the output path on success, or None if both engines failed.
    """
    if not text or not text.strip():
        log.error("No text supplied to TTS.")
        return None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    if _try_edge_tts(text, out_path):
        return out_path
    if _try_gtts(text, out_path):
        return out_path

    log.error("All TTS engines failed; no voiceover produced.")
    return None
