"""
SEO / metadata engine for the long-form storytelling pipeline.

WHY THE LONG-FORM PIPELINE MATTERS MOST
---------------------------------------
There are two routes into the YouTube Partner Program:

  * Shorts route : 1,000 subscribers + 10,000,000 valid public Shorts views
                   within 90 days.
  * Long-form    : 1,000 subscribers + 4,000 valid public watch HOURS
                   within 365 days.

At the channel's current scale the Shorts route is arithmetically out of reach
(10M views in 90 days is roughly 111,000 views per day). The long-form route is
the reachable one, because watch hours accumulate from DURATION, not from view
count: a 6-minute story watched half-way through banks 3 minutes per view, so
~80,000 views spread over the year clears 4,000 hours. That makes long-form
metadata the highest-leverage SEO surface in this repo.

WHAT WAS WRONG BEFORE
---------------------
  * Every description was the same 4 blocks with only the hook/moral swapped,
    and ended with the identical 5-hashtag string from config.json.
  * The title was the raw Gemini title with no search anchor at all, so a video
    called "The Boy And The Broken Bridge" matched no query anyone types.
  * No chapters, so YouTube got no structural signal and viewers had no way to
    re-enter the video (chapters are one of the few description elements that
    demonstrably lift session watch time).
  * The description welcomed viewers to "KrishnaKatha" — a brand that does not
    match the channel they are actually watching.

This module fixes all four.
"""

import logging
import random
import re

from .config import get_cfg

log = logging.getLogger("krishnakatha.seo")


# ==========================================================================
# Search anchors — what people actually search for in this niche
# ==========================================================================
SEARCH_ANCHORS = [
    "Moral Story",
    "Bedtime Story",
    "Story With A Moral",
    "Moral Stories In English",
    "Short Story For Kids",
    "Bedtime Story For Kids",
    "English Story",
    "Story For Children",
    "Moral Stories",
    "Storytime",
    "Good Night Story",
    "Story With A Lesson",
    "Family Story",
    "Kids Moral Story",
]

AUDIENCE_QUALIFIERS = [
    "For Kids",
    "For Children",
    "In English",
    "Bedtime Story",
    "Family Story",
    "Read Aloud",
]

TITLE_PATTERNS = [
    "{core} | {anchor} {qualifier}",
    "{core} - {anchor}",
    "{anchor}: {core}",
    "{core} | {anchor}",
    "{core} 🌙 {anchor} {qualifier}",
    "{anchor} {qualifier} | {core}",
    "{core} | A Story About {lesson}",
    "{core} - {anchor} {qualifier}",
    "{core} | {lesson} {anchor}",
    "{core} ✨ {anchor}",
    "{anchor} About {lesson} | {core}",
    "{core} | {anchor} You'll Remember",
    "{core} - A {lesson} Story {qualifier}",
    "{core} | Heartwarming {anchor}",
    "{anchor} - {core} ({lesson})",
    "{core} 🌟 {anchor} {qualifier}",
]

TITLE_SOFT_LIMIT = 88
TITLE_HARD_LIMIT = 100


def _clean_core(core):
    core = str(core or "").strip()
    core = re.sub(r"#\w+", "", core)
    core = core.replace('"', "").strip()
    core = re.sub(r"\s+", " ", core)
    core = core.rstrip(".,;:-—|")
    return core or "A Story Worth Hearing"


def _lesson_from_moral(moral):
    """Pull a 1-3 word lesson label out of the one-sentence moral."""
    text = str(moral or "").strip()
    text = re.sub(r"^the moral of the story is( that)?\s*", "", text, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 3]
    if not words:
        return "Kindness"
    return " ".join(w.capitalize() for w in words[:2])


def build_title(core_title, moral="", rng=None):
    rng = rng or random
    core = _clean_core(core_title)
    title = rng.choice(TITLE_PATTERNS).format(
        core=core,
        anchor=rng.choice(SEARCH_ANCHORS),
        qualifier=rng.choice(AUDIENCE_QUALIFIERS),
        lesson=_lesson_from_moral(moral),
    )
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > TITLE_SOFT_LIMIT:
        title = f"{core} | {rng.choice(SEARCH_ANCHORS)}"
    if len(title) > TITLE_SOFT_LIMIT:
        title = core
    return title[:TITLE_HARD_LIMIT]


# ==========================================================================
# Chapters
# ==========================================================================
# YouTube's rules: the list must start at 00:00, contain at least 3 entries, and
# every chapter must be at least 10 seconds long — otherwise the whole block is
# silently ignored. All three are enforced below.
#
# Timing method: the narration is one continuous read with no inserted pauses,
# so splitting it by cumulative word count against the real voiceover duration
# lands within a couple of seconds. The intro card in this pipeline is an
# OVERLAY (the audio still starts at t=0), so no offset correction is needed.

MIN_CHAPTER_SECONDS = 11
CHAPTER_LABELS = [
    "The Beginning", "A Small Problem", "Something Changes", "The Hard Part",
    "A Difficult Choice", "The Turning Point", "What Happened Next",
    "The Truth Comes Out", "Putting It Right", "The Ending", "The Moral",
]


def _fmt_ts(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_chapters(text, duration_seconds, count=6, rng=None):
    """Return a list of "0:00 Label" strings, or [] if chapters aren't viable."""
    rng = rng or random
    try:
        duration = float(duration_seconds or 0)
    except Exception:
        duration = 0.0
    # Need room for at least 3 legal chapters.
    if duration < MIN_CHAPTER_SECONDS * 3:
        return []

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if s]
    if len(sentences) < 6:
        return []

    max_by_duration = int(duration // MIN_CHAPTER_SECONDS)
    count = max(3, min(int(count), max_by_duration, len(CHAPTER_LABELS)))

    # Word-proportional boundaries.
    counts = [len(s.split()) for s in sentences]
    total_words = float(sum(counts)) or 1.0
    per_chapter = total_words / count

    chapters = []
    cumulative = 0.0
    next_boundary = 0.0
    label_pool = CHAPTER_LABELS[:-1]
    for i in range(count):
        start_seconds = (next_boundary / total_words) * duration
        # Enforce the 10s minimum by pushing later chapters forward if needed.
        if chapters and start_seconds < chapters[-1][0] + MIN_CHAPTER_SECONDS:
            start_seconds = chapters[-1][0] + MIN_CHAPTER_SECONDS
        if start_seconds > duration - MIN_CHAPTER_SECONDS:
            break
        if i == 0:
            label = "Story Starts"
            start_seconds = 0.0
        elif i == count - 1:
            label = "The Moral"
        else:
            label = label_pool[min(i, len(label_pool) - 1)]
        chapters.append((start_seconds, label))
        next_boundary += per_chapter
        cumulative = start_seconds

    if len(chapters) < 3:
        return []
    return [f"{_fmt_ts(t)} {label}" for t, label in chapters]


# ==========================================================================
# Description
# ==========================================================================
DESC_OPENERS = [
    "{hook}",
    "{hook} Settle in — this one is worth the few minutes.",
    "{hook} A gentle {anchor_lc} the whole family can listen to together.",
    "{hook} Stay till the end for the lesson.",
]

DESC_QUESTIONS = [
    "What did you think of the ending? Tell us in the comments 👇",
    "Which character would you have been? Comment below!",
    "Did you guess how it would end? Let us know 👇",
    "What lesson would you want your children to take from this? Comment below.",
    "If this story reached you, leave a ❤️ so we know which ones to tell more of.",
]

DESC_CTAS = [
    "Subscribe for a brand-new story every single day.",
    "Hit subscribe so tomorrow's story finds you automatically.",
    "New story daily — subscribe and turn on the bell so you never miss one.",
    "If you enjoyed this, subscribing is the one thing that helps most.",
]

DESC_ABOUT_TEMPLATES = [
    "{channel} tells gentle, heart-touching stories for the whole family. Every "
    "episode carries one clear lesson — honesty, kindness, courage, patience — "
    "wrapped in a story children actually want to sit through.",
    "Welcome to {channel}. These are calm, screen-time-you-feel-good-about "
    "stories: simple language, real emotion, and a moral you can talk about "
    "together afterwards.",
    "{channel} publishes one narrated story a day for families. Perfect for "
    "bedtime, car rides, quiet afternoons, or classroom listening time.",
]

WHO_ITS_FOR = [
    "Best for: bedtime listening, family screen time, road trips, and classrooms.",
    "Great for children aged 4-10, and for any adult who still likes a good story.",
    "Made to be listened to as much as watched — put it on and just listen.",
]

PRODUCTION_NOTE = (
    "About this video: an original story written and narrated for this channel, "
    "illustrated with generated artwork and licensed royalty-free footage and music."
)

HASHTAG_CORE = ["#moralstories", "#bedtimestories", "#storiesforkids"]
HASHTAG_ROTATE = [
    "#moralstory", "#storytime", "#kidsstories", "#englishstories",
    "#shortstories", "#storiesinenglish", "#familytime", "#bedtimestory",
    "#moralofthestory", "#childrensstories", "#goodnightstories", "#lifelessons",
]


def build_hashtags(rng=None, count=8):
    rng = rng or random
    picked = list(HASHTAG_CORE[:2])
    picked.append(rng.choice(HASHTAG_CORE))
    picked.extend(rng.sample(HASHTAG_ROTATE, min(6, len(HASHTAG_ROTATE))))
    unique = list(dict.fromkeys(picked))
    return unique[: max(3, int(count))]


TAG_EVERGREEN = [
    "moral stories", "bedtime stories", "stories for kids", "moral story",
    "short story with moral", "moral of the story", "english moral story",
    "story for children", "storytime", "kids stories in english",
    "bedtime story for children", "good moral stories",
]

TAGS_CHAR_BUDGET = 480
TAG_MAX_LEN = 60


def _normalise_tag(tag):
    tag = re.sub(r"\s+", " ", str(tag or "").strip().lower()).strip(",")
    return tag[:TAG_MAX_LEN]


def build_tags(core_title="", moral="", keywords=None, rng=None, extra=None):
    rng = rng or random
    lesson = _lesson_from_moral(moral).lower()
    candidates = [_clean_core(core_title).lower()]
    if lesson:
        candidates += [f"{lesson} story", f"story about {lesson}", lesson]
    ever = list(TAG_EVERGREEN)
    rng.shuffle(ever)
    candidates += ever
    candidates += list(keywords or [])
    candidates += list(extra or [])

    tags, used, budget = [], set(), 0
    for raw in candidates:
        tag = _normalise_tag(raw)
        if not tag or tag in used:
            continue
        cost = len(tag) + 1
        if budget + cost > TAGS_CHAR_BUDGET:
            continue
        tags.append(tag)
        used.add(tag)
        budget += cost
    return tags


def build_description(story, duration_seconds=None, hashtags=None, rng=None):
    """Compose the full long-form description, chapters included."""
    rng = rng or random
    channel = get_cfg("channel.name", "Krishna Universe")
    anchor = rng.choice(SEARCH_ANCHORS)
    hook = (getattr(story, "hook", "") or "").strip()
    moral = (getattr(story, "moral", "") or "").strip()

    opener = rng.choice(DESC_OPENERS).format(
        hook=hook, anchor_lc=anchor.lower()
    ).strip()

    parts = [opener]

    if moral:
        # Strip the narrator's spoken lead-in so the line does not read
        # "Lesson in this story: The moral of the story is that...".
        clean_moral = re.sub(
            r"^the moral of (the|this) story is( that)?\s*", "", moral, flags=re.I
        ).strip()
        clean_moral = (clean_moral[:1].upper() + clean_moral[1:]) if clean_moral else moral
        parts.append(f"Lesson in this story: {clean_moral}")

    chapters = build_chapters(
        getattr(story, "text", ""), duration_seconds,
        count=int(get_cfg("seo.chapter_count", 6)), rng=rng,
    )
    if chapters:
        parts.append("Chapters:\n" + "\n".join(chapters))
        log.info("Built %d chapters for the description.", len(chapters))
    else:
        log.info("Chapters skipped (duration/text too short to be valid).")

    parts.append(rng.choice(DESC_QUESTIONS))
    parts.append(rng.choice(DESC_CTAS))
    parts.append(rng.choice(DESC_ABOUT_TEMPLATES).format(channel=channel))
    parts.append(rng.choice(WHO_ITS_FOR))

    kw = [_normalise_tag(k) for k in (getattr(story, "keywords", None) or [])]
    if kw:
        parts.append("Themes: " + ", ".join(kw[:6]) + ".")

    parts.append(PRODUCTION_NOTE)

    channel_url = get_cfg("seo.channel_url", None)
    if channel_url:
        parts.append(f"More stories: {channel_url}")

    body = "\n\n".join(p for p in parts if p)
    tags_line = " ".join(hashtags or build_hashtags(rng=rng))
    return f"{body}\n\n{tags_line}".strip()[:4900]


# ==========================================================================
# One-call entry point
# ==========================================================================
def build_metadata(story, duration_seconds=None, rng=None):
    rng = rng or random
    hashtags = build_hashtags(rng=rng, count=int(get_cfg("seo.hashtag_count", 8)))
    title = build_title(story.title, moral=getattr(story, "moral", ""), rng=rng)
    description = build_description(
        story, duration_seconds=duration_seconds, hashtags=hashtags, rng=rng
    )
    tags = build_tags(
        core_title=story.title,
        moral=getattr(story, "moral", ""),
        keywords=getattr(story, "keywords", None),
        rng=rng,
        extra=get_cfg("youtube.default_tags", []),
    )
    meta = {
        "youtube_title": title,
        "youtube_description": description,
        "youtube_tags": tags,
        "hashtags": hashtags,
    }
    log.info("SEO: title=%r | %d tags | %d hashtags", title, len(tags), len(hashtags))
    return meta
