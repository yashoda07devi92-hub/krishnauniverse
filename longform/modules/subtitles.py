"""
Timing-based caption generation for Krishna Universe Katha.

We do NOT use forced alignment (whisper). Instead we estimate word timings from
the total audio duration and word count, distributing time proportionally to
word length with small pauses after punctuation. Captions are grouped into
readable chunks. Rendering happens in video_composer.py.
"""

import logging
import re

from .config import get_cfg

log = logging.getLogger("krishnakatha.subtitles")


def _clean_words(text):
    words = re.findall(r"\S+", text.strip())
    return [w for w in words if w]


def estimate_word_timings(text, total_duration):
    words = _clean_words(text)
    if not words or total_duration <= 0:
        return []
    weights = []
    for w in words:
        weight = max(1, len(w))
        if w.endswith((".", "!", "?")):
            weight += 3
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
    if timings:
        last_w, last_start, _ = timings[-1]
        timings[-1] = (last_w, last_start, total_duration)
    return timings


def build_caption_groups(text, total_duration, words_per_group=None):
    """Group word timings into readable caption chunks.

    Returns a list of dicts: {"text": str, "start": float, "end": float}.
    """
    if words_per_group is None:
        words_per_group = get_cfg("captions.words_per_group", 6)
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
        groups.append(
            {
                "text": " ".join(words),
                "start": round(chunk[0][1], 3),
                "end": round(chunk[-1][2], 3),
            }
        )
    log.info("Built %d caption group(s) from %d words.", len(groups), len(timings))
    return groups
