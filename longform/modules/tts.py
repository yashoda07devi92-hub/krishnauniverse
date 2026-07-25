"""
Text-to-speech for Krishna Universe Katha.

Long narrations (5-7 minutes) are synthesized in CHUNKS for reliability, then
concatenated into one mp3:

  1. The text is split into sentence-aware chunks (~600 chars each).
  2. Each chunk is synthesized with edge-tts FIRST (free, warm storyteller
     voice). On ANY error - including the HTTP 403 sometimes returned to CI
     runners - that chunk falls back to gTTS (American English).
  3. All chunk files are concatenated with moviepy into the final mp3.

If chunking/concatenation fails for any reason, we fall back to a single
whole-text synthesis pass so a voiceover is still produced.
"""

import asyncio
import logging
import os
import re
import tempfile

from .config import get_cfg, get_env

log = logging.getLogger("krishnakatha.tts")


def _voice():
    return get_env("TTS_VOICE", get_cfg("tts.voice", "en-US-AriaNeural"))


def _rate():
    return get_cfg("tts.rate", "-6%")


def _pitch():
    return get_cfg("tts.pitch", "+0Hz")


def _file_has_audio(path):
    try:
        return os.path.exists(path) and os.path.getsize(path) > 1024
    except Exception:
        return False


def _chunk_text(text, max_chars=600):
    """Split text into sentence-aware chunks no longer than max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    current = ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) + 1 <= max_chars:
            current = (current + " " + s).strip()
        else:
            if current:
                chunks.append(current)
            # A single sentence longer than max_chars is kept whole.
            current = s
    if current:
        chunks.append(current)
    return chunks or [text.strip()]


# --------------------------------------------------------------------------
# edge-tts
# --------------------------------------------------------------------------
async def _edge_tts_async(text, out_path, voice, rate, pitch):
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def _try_edge_tts(text, out_path):
    voice, rate, pitch = _voice(), _rate(), _pitch()
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
        try:
            asyncio.run(_edge_tts_async(text, out_path, voice, rate, pitch))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_edge_tts_async(text, out_path, voice, rate, pitch))
            finally:
                loop.close()
        if _file_has_audio(out_path):
            return True
        return False
    except Exception as exc:
        log.warning("edge-tts failed (%s); will try gTTS for this chunk.", exc)
        return False


# --------------------------------------------------------------------------
# gTTS fallback
# --------------------------------------------------------------------------
def _try_gtts(text, out_path):
    try:
        from gtts import gTTS
    except Exception as exc:
        log.error("gTTS is not available (%s).", exc)
        return False
    lang = get_cfg("tts.fallback_lang", "en")
    tld = get_cfg("tts.fallback_tld", "com")
    try:
        gTTS(text=text, lang=lang, tld=tld).save(out_path)
        return _file_has_audio(out_path)
    except Exception as exc:
        log.error("gTTS failed (%s).", exc)
        return False


def _synth_one(text, out_path):
    """Synthesize a single chunk: edge-tts first, gTTS fallback."""
    if _try_edge_tts(text, out_path):
        return True
    return _try_gtts(text, out_path)


def _concat_audio(parts, out_path):
    """Concatenate mp3 chunk files into one mp3 using moviepy."""
    from moviepy.editor import AudioFileClip, concatenate_audioclips

    clips = []
    try:
        for p in parts:
            clips.append(AudioFileClip(p))
        final = concatenate_audioclips(clips)
        final.write_audiofile(out_path, verbose=False, logger=None)
        final.close()
        return _file_has_audio(out_path)
    finally:
        for c in clips:
            try:
                c.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def synthesize(text, out_path):
    """Generate speech for `text` to `out_path` (mp3).

    Returns the output path on success, or None if synthesis failed.
    """
    if not text or not text.strip():
        log.error("No text supplied to TTS.")
        return None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    chunks = _chunk_text(text, int(get_cfg("tts.chunk_chars", 600)))
    log.info("Synthesizing %d narration chunk(s) (voice=%s).", len(chunks), _voice())

    tmpdir = tempfile.mkdtemp(prefix="mt_tts_")
    parts = []
    try:
        for i, chunk in enumerate(chunks):
            part_path = os.path.join(tmpdir, "part_%03d.mp3" % i)
            if _synth_one(chunk, part_path):
                parts.append(part_path)
            else:
                log.warning("Chunk %d/%d failed to synthesize.", i + 1, len(chunks))

        if not parts:
            log.error("No narration chunks were synthesized.")
            return None

        if len(parts) == 1:
            # Single chunk: just move it into place.
            import shutil
            shutil.move(parts[0], out_path)
            return out_path if _file_has_audio(out_path) else None

        try:
            if _concat_audio(parts, out_path):
                log.info("Concatenated %d chunks -> %s", len(parts), out_path)
                return out_path
        except Exception as exc:
            log.warning("Chunk concatenation failed (%s); trying single-pass.", exc)

        # Last resort: single whole-text synthesis.
        if _synth_one(text, out_path):
            return out_path
        return None
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
