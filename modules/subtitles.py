"""
Timing-based caption generation for Krishna Universe.

We deliberately do NOT use openai-whisper (its wheel fails to build on modern
pip, and it is heavy). Instead we estimate word timings from the total audio
duration and the word count, distributing time proportionally to word length.
Captions are grouped into small "word-by-word style" chunks.

This module returns plain data (caption segments). The actual TextClip
rendering happens in video_composer.py so this module has no heavy
dependencies.
"""

import logging
import re

from .config import get_cfg

log = logging.getLogger("krishna.subtitles")


def _clean_words(text):
    # Split into words, keeping basic punctuation attached.
    words = re.findall(r"\S+", text.strip())
    return [w for w in words if w]


def estimate_word_timings(text, total_duration):
    """Return a list of (word, start, end) using length-weighted distribution.

    Longer words and words ending sentences get slightly more time, which keeps
    the captions feeling natural without needing forced alignment.
    """
    words = _clean_words(text)
    if not words or total_duration <= 0:
        return []

    # Weight each word by character count (min 1), plus a pause bonus after
    # sentence-ending punctuation.
    weights = []
    for w in words:
        weight = max(1, len(w))
        if w.endswith((".", "!", "?")):
            weight += 3  # small pause after a sentence
        elif w.endswith((",", ";", ":")):
            weight += 1
        weights.append(weight)

    total_weight = float(sum(weights)) or 1.0
    timings = []
    cursor = 0.0
    for w, weight in zip(words, weights):
        dur = total_duration * (weight / total_weight)
        start = cursor
        end = min(total_duration, cursor + dur)
        timings.append((w, start, end))
        cursor = end
    # Make sure the last word ends exactly at total_duration.
    if timings:
        last_w, last_start, _ = timings[-1]
        timings[-1] = (last_w, last_start, total_duration)
    return timings


def build_caption_groups(text, total_duration, words_per_group=None):
    """Group word timings into small caption chunks.

    Returns a list of dicts: {"text": str, "start": float, "end": float}.
    """
    if words_per_group is None:
        words_per_group = get_cfg("captions.words_per_group", 3)
    words_per_group = max(1, int(words_per_group))

    timings = estimate_word_timings(text, total_duration)
    if not timings:
        return []

    groups = []
    for i in range(0, len(timings), words_per_group):
        chunk = timings[i : i + words_per_group]
        if not chunk:
            continue
        words = [c[0] for c in chunk]
        start = chunk[0][1]
        end = chunk[-1][2]
        groups.append(
            {
                "text": " ".join(words),
                "start": round(start, 3),
                "end": round(end, 3),
            }
        )
    log.info("Built %d caption group(s) from %d words.", len(groups), len(timings))
    return groups
