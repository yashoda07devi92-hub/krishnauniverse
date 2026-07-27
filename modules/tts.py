"""
Text-to-speech for Krishna Universe (Hindi narration).

Strategy:
  1. Try edge-tts FIRST (free, and the only engine here that sounds like a
     person reading rather than a phone reading).
  2. On ANY error - including the HTTP 403 commonly returned to GitHub Actions
     runners - fall back to gTTS (Hindi, noticeably flatter).
  3. Polish the result with ffmpeg so the level is broadcast-consistent.

Both engines write the SAME output mp3 path. The engine actually used is logged.

WHY THIS FILE IS MORE THAN A ONE-LINE API CALL
----------------------------------------------
The owner's report on the first published reels was: the voice breaks up in
places, it obviously sounds like AI, and parts of it cannot be made out. Three
different causes, none of them fixable by choosing a different voice:

1. TRUNCATION. edge-tts streams audio chunks over a websocket and, when a chunk
   is lost, it saves a SHORT FILE AND RAISES NOTHING. The old code only checked
   `getsize > 1024`, which a truncated file passes easily - so a narration that
   lost its last eight seconds was accepted, and the composer then padded the
   timeline with silence. That is the "voice breaks off" symptom, and it is a
   real bug rather than a limitation. `_synthesize_verified` now measures the
   rendered duration and rejects anything materially shorter than the script
   implies.

2. PUNCTUATION. edge-tts exposes no SSML, so the ONLY prosody controls are the
   words and the punctuation. The scripts were full of em dashes, which the
   engine reads as a hard stop mid-clause, and the text often had no terminal
   danda, which makes the engine clip the final word. Both read as "breaking
   up". `_normalise_for_speech` fixes the text before it is ever sent.

3. LEVEL. Raw TTS output is quiet, thin and inconsistent from run to run, and it
   was competing with a music bed. Quiet narration under music is exactly why
   Hindi consonant clusters became unintelligible. `_polish_audio` high-passes
   the rumble, compresses gently and normalises to -16 LUFS, which is what makes
   a voice sound "produced" instead of "generated".

gTTS and edge-tts are imported lazily so importing this module never hard-fails.
"""

import asyncio
import logging
import os
import random
import re
import shutil
import subprocess

from .config import get_cfg, get_env
from . import history

log = logging.getLogger("krishna.tts")


def _voice():
    """Pick the narrator voice for this run.

    An explicit TTS_VOICE env var always wins (useful for pinning a voice while
    debugging). Otherwise a voice is drawn from tts.voice_pool through history so
    it actually rotates instead of landing on the same one several days running.
    """
    forced = get_env("TTS_VOICE")
    if forced:
        return forced
    pool = get_cfg("tts.voice_pool", []) or []
    if pool:
        return history.pick("voices", list(pool))
    return get_cfg("tts.voice", "hi-IN-MadhurNeural")


def _rate():
    """Slightly vary the speaking rate so pacing is not identical every time."""
    pool = get_cfg("tts.rate_pool", []) or []
    if pool:
        return random.choice(list(pool))
    return get_cfg("tts.rate", "-8%")


def _pitch():
    return get_cfg("tts.pitch", "+0Hz")


# --------------------------------------------------------------------------
# Text preparation
# --------------------------------------------------------------------------
# Characters that must never reach the engine. Each one produced a specific
# audible defect rather than being merely untidy.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),
    (0x1F000, 0x1F2FF),
    (0x2600, 0x27BF),
    (0xFE00, 0xFE0F),
    (0x2190, 0x21FF),
)


def _is_emoji(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _normalise_for_speech(text):
    """Rewrite the script into something a TTS engine reads cleanly.

    edge-tts accepts no SSML, so punctuation IS the prosody API. Every rule here
    corresponds to a defect heard in a published reel:

      * EM DASHES. The scripts lean on "कान्हा ने कहा — गुस्सा जलती लकड़ी है"
        because it reads well on a page. The engine treats an em dash as a hard
        break, so the sentence audibly snapped in half. Replaced with a comma,
        which produces the short natural pause that was intended.
      * NO TERMINAL PUNCTUATION. edge-tts clips the tail of the final word when
        the text does not end in a sentence mark, which sounds like the audio
        cut out. A danda is appended if missing.
      * EMOJI / HASHTAGS / MARKDOWN. Read aloud literally or as dead air. The
        prompt forbids them, but a model ignores that occasionally and the cost
        of being wrong is a ruined upload.
      * QUOTE MARKS. Devanagari quotes sometimes render as a swallowed syllable.
        Dropped; the pause from the surrounding comma carries the reported
        speech instead.
      * DOUBLE SPACES / STRAY COMMAS. Produce uneven, stuttery pacing.
    """
    s = str(text or "")

    s = "".join(" " if _is_emoji(ch) else ch for ch in s)
    s = re.sub(r"[*_`#>|\[\]{}<>]", " ", s)          # markdown / stray syntax
    s = s.replace("\u200b", "").replace("\u200d", "")  # zero-width joiners
    s = re.sub(r"[\"'“”‘’„«»]", "", s)                # quote marks
    s = re.sub(r"[—–―]+", ",", s)                     # THE em-dash fix
    s = re.sub(r"\.{2,}", ",", s)                     # ellipses
    s = re.sub(r"\s-\s", ", ", s)                     # spaced hyphen as dash
    s = s.replace("(", ", ").replace(")", ", ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n+", " ", s)

    # Tidy the punctuation itself: no space before, exactly one after, and never
    # two marks in a row (",  ।" reads as an unexplained long gap).
    s = re.sub(r"\s+([,।.!?])", r"\1", s)
    s = re.sub(r"([,।.!?])(?=[^\s])", r"\1 ", s)
    s = re.sub(r",\s*(?=[,।.!?])", "", s)
    s = re.sub(r"([।.!?])\s*(?=[।.!?])", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,")

    if s and s[-1] not in "।.!?":
        s += "।"
    return s


WORDS_PER_MINUTE = 140.0


def _expected_seconds(text, rate="-10%"):
    """Roughly how long `text` should take to speak at `rate`.

    Only used as a floor for the truncation check, so an approximation is
    enough - but it has to account for the rate, since a -12% read of the same
    script is ~14% longer and would otherwise look suspiciously long rather than
    correct.
    """
    words = len(str(text or "").split())
    seconds = (words / WORDS_PER_MINUTE) * 60.0
    try:
        pct = float(str(rate).strip().replace("%", ""))
        seconds *= 1.0 / (1.0 + pct / 100.0)
    except Exception:
        pass
    return seconds


def _probe_duration(path):
    """Duration of an audio file in seconds, or None if it cannot be measured."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float((out.stdout or "").strip())
    except Exception:
        return None


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


def _edge_once(text, out_path, voice, rate, pitch):
    """One edge-tts attempt. Returns True only if a file was written."""
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
            loop.run_until_complete(_edge_tts_async(text, out_path, voice, rate, pitch))
        finally:
            loop.close()
    return _file_has_audio(out_path)


def _try_edge_tts(text, out_path):
    """Synthesize with edge-tts, rejecting truncated renders.

    THE TRUNCATION CHECK IS THE POINT OF THIS FUNCTION.
    edge-tts receives audio as a websocket stream. When a chunk is dropped it
    writes what it has and returns successfully, so the only evidence is that the
    file is too SHORT for the script it was given. Without this check the reel
    ships with the narration cut off part way through - which is precisely the
    defect reported on the published videos - and nothing in the log says so.

    A fresh attempt genuinely helps: the stream is re-established, so a dropped
    chunk is not reproducible the way a bad input would be.
    """
    voice = _voice()
    pitch = _pitch()
    attempts = max(1, int(get_cfg("tts.attempts", 3)))
    tolerance = float(get_cfg("tts.min_duration_ratio", 0.8))

    best_path = None
    best_duration = 0.0
    scratch = out_path + ".try.mp3"

    for attempt in range(1, attempts + 1):
        rate = _rate()
        expected = _expected_seconds(text, rate)
        try:
            log.info("Synthesizing voiceover with edge-tts (voice=%s, rate=%s, attempt %d/%d).",
                     voice, rate, attempt, attempts)
            if not _edge_once(text, scratch, voice, rate, pitch):
                log.warning("edge-tts attempt %d produced no usable file.", attempt)
                continue

            actual = _probe_duration(scratch)
            if actual is None:
                # No ffprobe: accept it rather than throwing away good audio, but
                # say so, because the truncation guard is not active.
                log.warning("ffprobe unavailable; cannot verify narration length. "
                            "Accepting the render unchecked.")
                os.replace(scratch, out_path)
                return True

            if actual >= expected * tolerance:
                log.info("edge-tts OK: %.1fs rendered vs ~%.1fs expected.", actual, expected)
                os.replace(scratch, out_path)
                return True

            log.warning(
                "edge-tts render is TRUNCATED: %.1fs rendered but the script needs "
                "~%.1fs (%.0f%% of expected, floor is %.0f%%). Retrying.",
                actual, expected, 100.0 * actual / max(expected, 0.01), tolerance * 100,
            )
            if actual > best_duration:
                best_duration = actual
                best_path = out_path + ".best.mp3"
                try:
                    os.replace(scratch, best_path)
                except Exception:
                    best_path = None
        except Exception as exc:
            log.warning("edge-tts attempt %d failed (%s).", attempt, exc)

    # Every attempt came back short. The longest one still beats gTTS on quality,
    # and the composer clamps the timeline anyway, so use it rather than dropping
    # to the flatter engine - but log it loudly, because it means the narration
    # really is incomplete.
    if best_path and os.path.exists(best_path):
        log.warning("All %d edge-tts attempts were short; using the longest (%.1fs). "
                    "The narration may be incomplete.", attempts, best_duration)
        try:
            os.replace(best_path, out_path)
            return True
        except Exception:
            pass
    for tmp in (scratch, best_path):
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
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

    lang = get_cfg("tts.fallback_lang", "hi")
    tld = get_cfg("tts.fallback_tld", "co.in")
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
# Audio polish
# --------------------------------------------------------------------------
def _polish_audio(path):
    """Make the narration sound produced rather than generated.

    Raw TTS output is thin, quiet and inconsistent between runs, and it was being
    mixed under a music bed. Quiet, uneven narration beneath music is why the
    Hindi became hard to follow - the consonant clusters that carry meaning are
    the first thing lost.

    The chain, in order and for a reason:
      highpass=f=80    removes sub-bass rumble the voice does not use. It carries
                       no speech but does eat headroom, so removing it lets the
                       words sit louder for the same peak level.
      equalizer 3 kHz  a small lift where Hindi consonant definition lives. This
                       is the single biggest gain in "I can make out the words".
      acompressor      evens out the loud/soft swings between sentences, so no
                       phrase drops under the music.
      loudnorm         two-pass-style normalisation to -16 LUFS, the level
                       YouTube targets. Without it every reel arrives at a
                       different volume, which alone reads as amateur.

    Best-effort: if ffmpeg is missing or the filter chain fails, the unpolished
    file is kept and the reel still ships.
    """
    if not get_cfg("tts.polish_enabled", True):
        return False
    if not shutil.which("ffmpeg"):
        log.info("ffmpeg not available; skipping audio polish.")
        return False

    target_lufs = float(get_cfg("tts.target_lufs", -16.0))
    chain = (
        "highpass=f=80,"
        "equalizer=f=3000:width_type=h:width=1800:g=2.5,"
        "acompressor=threshold=-18dB:ratio=3:attack=8:release=180,"
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
    )
    tmp = path + ".polish.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", path,
             "-af", chain, "-ar", "44100", "-b:a", "192k", tmp],
            capture_output=True, timeout=300, check=True,
        )
        if _file_has_audio(tmp):
            before = _probe_duration(path)
            after = _probe_duration(tmp)
            # A polish pass must never change the LENGTH. If it did, the audio
            # and the visual timeline would drift apart, which is worse than an
            # unpolished voice.
            if before and after and abs(after - before) > 0.35:
                log.warning("Polish changed duration %.2fs -> %.2fs; discarding it.",
                            before, after)
                os.remove(tmp)
                return False
            os.replace(tmp, path)
            log.info("Voiceover polished (high-pass, presence lift, compression, "
                     "%.0f LUFS).", target_lufs)
            return True
        log.warning("Audio polish produced nothing usable; keeping the original.")
    except Exception as exc:
        log.warning("Audio polish failed (%s); keeping the original.", exc)
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
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

    spoken = _normalise_for_speech(text)
    if spoken != " ".join(str(text).split()):
        log.info("Script normalised for speech (%d -> %d chars).",
                 len(str(text)), len(spoken))
    if not spoken.strip():
        log.error("Script contained nothing speakable after normalisation.")
        return None

    if _try_edge_tts(spoken, out_path):
        _polish_audio(out_path)
        return out_path
    if _try_gtts(spoken, out_path):
        _polish_audio(out_path)
        return out_path

    log.error("All TTS engines failed; no voiceover produced.")
    return None
