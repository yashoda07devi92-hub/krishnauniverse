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
  * The description welcomed viewers to "Krishna Universe" — a brand that does not
    match the channel they are actually watching.

This module fixes all four.
"""

import logging
import random
import re

from .config import get_cfg

log = logging.getLogger("krishna.seo")


# ==========================================================================
# Search anchors — what people actually search for in this niche
# ==========================================================================
SEARCH_ANCHORS = [
    "कृष्ण कथा",
    "श्रीकृष्ण की कथा",
    "महाभारत की कथा",
    "गीता उपदेश",
    "कृष्ण लीला",
    "भक्ति कथा",
    "हिंदी कथा",
    "पौराणिक कथा",
    "कान्हा की कहानी",
    "Krishna Story In Hindi",
    "श्रीकृष्ण लीला",
    "प्रेरणादायक कथा",
    "धार्मिक कथा",
    "कृष्ण कथा हिंदी में",
]

AUDIENCE_QUALIFIERS = [
    "हिंदी में",
    "पूरी कथा",
    "सम्पूर्ण कथा",
    "एक सीख के साथ",
    "परिवार के लिए",
    "बच्चों के लिए",
    "पूरी कथा हिंदी में",
    "एक गहरी सीख के साथ",
    "सुनिए और सोचिए",
    "श्रद्धा के साथ",
]

TITLE_PATTERNS = [
    "{core} | {anchor} {qualifier}",
    "{core} — {anchor}",
    "{anchor}: {core}",
    "{core} | {anchor}",
    "{anchor} {qualifier} | {core}",
    "{core} | {lesson} की सीख देने वाली कथा",
    "{core} — {anchor} {qualifier}",
    "{core} | {lesson} | {anchor}",
    "{anchor} | {core} — पूरी कथा",
    "{core} | ये कथा अंत तक सुनिए | {anchor}",
    "{core} — {lesson} की कथा {qualifier}",
    "{core} | {anchor} जो सोच बदल दे",
    "{anchor} — {core} ({lesson})",
    "{core} | सम्पूर्ण {anchor} {qualifier}",
    "{core} | {anchor} और उसकी गहरी सीख",
    "जानिए {core} | {anchor}",
]

TITLE_SOFT_LIMIT = 88
TITLE_HARD_LIMIT = 100


def _clean_core(core):
    core = str(core or "").strip()
    core = re.sub(r"#\w+", "", core)
    core = core.replace('"', "").strip()
    core = re.sub(r"\s+", " ", core)
    core = core.rstrip(".,;:-—|")
    return core or "श्रीकृष्ण की एक कथा"


# The concepts these kathas are actually about. The lesson label is matched
# against this list FIRST because a positional guess picks the wrong word: the
# moral "जो तुम्हें रोज़ पालता है, उसका आदर करो" yields the pronoun "तुम्हें",
# and a tag like "तुम्हें की कथा" is meaningless in either language and is
# searched for by nobody.
LESSON_CONCEPTS = [
    "अहंकार", "क्षमा", "प्रेम", "भक्ति", "धैर्य", "सत्य", "कर्म", "त्याग",
    "विश्वास", "मित्रता", "दोस्ती", "सेवा", "संयम", "ज़िम्मेदारी", "अपमान",
    "लोभ", "क्रोध", "मोह", "डर", "ज्ञान", "गुरु", "श्रद्धा", "आदर", "सम्मान",
    "दान", "वचन", "प्रतिज्ञा", "माँ", "धर्म", "न्याय", "शांति", "करुणा",
    "विनम्रता", "सच्चाई", "मेहनत", "बलिदान", "समर्पण", "संतोष",
]

# Pronouns and connectives that a positional pick keeps landing on.
_LESSON_STOP = {
    "है", "हैं", "कि", "को", "का", "की", "के", "में", "से", "और", "ही", "जो",
    "वो", "यह", "ये", "पर", "तो", "भी", "एक", "नहीं", "तुम", "तुम्हें",
    "तुम्हारा", "तुम्हारी", "आप", "हम", "मैं", "उसका", "उसकी", "उसके", "अपना",
    "अपनी", "अपने", "कोई", "सब", "इस", "उस", "हर", "बहुत", "कुछ", "जब", "तब",
    "अगर", "फिर", "लिए", "साथ", "बिना", "जाता", "जाती", "होता", "होती", "करो",
    "करता", "करती", "रहा", "रही", "गया", "गयी", "देता", "देती", "मत", "क्यों",
}


def _lesson_from_moral(moral):
    """Return a short, searchable concept label from the one-line Hindi moral.

    Two bugs preceded this. First, the original used
    re.findall(r"[A-Za-z]+", ...), which matches NOTHING in Devanagari, so every
    episode fell through to one identical label. Then a positional fallback
    picked the first non-stopword, which on real morals kept selecting pronouns.

    So: match a known concept anywhere in the moral, and only if none is present
    fall back to the LONGEST content word - concepts in Hindi are longer than
    the grammar around them ("अहंकार" vs "जो"), so length is a better signal
    than position.
    """
    text = str(moral or "").strip()
    text = re.sub(r"^इस कथा की सीख (यही है )?कि\s*", "", text)
    text = re.sub(r"^the moral of the story is( that)?\s*", "", text, flags=re.I)

    for concept in LESSON_CONCEPTS:
        if concept in text:
            return concept

    words = [w for w in re.findall(r"[\w\u0900-\u097F]+", text, re.UNICODE)
             if len(w) > 3 and w not in _LESSON_STOP]
    if not words:
        return "भक्ति"
    return max(words, key=len)


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
    "कथा का आरंभ", "एक समस्या", "कुछ बदलता है", "कठिन घड़ी",
    "एक मुश्किल फैसला", "कथा का मोड़", "आगे क्या हुआ",
    "सच सामने आया", "सब ठीक होता है", "कथा का अंत", "इस कथा की सीख",
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

    sentences = [s for s in re.split(r"(?<=[।.!?])\s+", str(text or "").strip()) if s]
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
    "{hook} आराम से बैठिए — ये कथा पूरे कुछ मिनट के लायक है।",
    "{hook} एक शांत {anchor_lc}, जो पूरा परिवार साथ बैठकर सुन सकता है।",
    "{hook} सीख के लिए अंत तक ज़रूर सुनिए।",
]

DESC_QUESTIONS = [
    "इस कथा का अंत आपको कैसा लगा? कमेंट में बताइए 👇",
    "आप इस कथा में किस पात्र की जगह होते? कमेंट कीजिए!",
    "क्या आपने अंदाज़ा लगा लिया था कि अंत क्या होगा? बताइए 👇",
    "इस कथा से आप अपने बच्चों को क्या सीख देना चाहेंगे? कमेंट कीजिए।",
    "अगर ये कथा दिल तक पहुँची तो एक 🙏 कमेंट कर दीजिए।",
    "कमेंट में जय श्री कृष्ण लिखिए 🙏",
    "अगली कथा किस लीला पर चाहिए? कमेंट में बताइए 👇",
    "आपकी सबसे पसंदीदा कृष्ण लीला कौन सी है? 👇",
    "आपकी सबसे पसंदीदा कृष्ण लीला कौन सी है? कमेंट कीजिए।",
    "इस कथा की सीख को अपने शब्दों में लिखिए 👇",
    "क्या आपने ये कथा पहले सुनी थी? बताइए।",
    "आप किस शहर से सुन रहे हैं? कमेंट में लिखिए।",
    "अगली कथा किस लीला पर चाहिए? बताइए 👇",
    "इस कथा का कौन सा हिस्सा सबसे ज़्यादा छू गया?",
    "कमेंट में राधे राधे लिखिए 🙏",
    "आपके परिवार में ये कथा कौन सुनाता था? 👇",
    "क्या ये सीख आज भी लागू होती है? कमेंट कीजिए।",
    "कमेंट में जय कन्हैया लाल की लिखिए 🙏",
    "आपको कान्हा की कौन सी बात सबसे प्यारी लगती है?",
    "अगर सहमत हैं तो एक ❤️ कमेंट कीजिए।",
]

DESC_CTAS = [
    "ऐसी ही कथाओं के लिए चैनल को Subscribe कीजिए।",
    "Subscribe कर लीजिए, ताकि अगली कथा अपने आप आप तक पहुँच जाए।",
    "रोज़ नई कथा — Subscribe कीजिए और घंटी दबा दीजिए।",
    "अगर कथा अच्छी लगी, तो एक Subscribe सबसे बड़ी मदद है।",
    "ये कथा अपने परिवार के साथ शेयर कीजिए।",
    "Like और Subscribe करके साथ बने रहिए।",
    "जय श्री कृष्ण। Subscribe करके साथ बने रहिए।",
    "अगर कथा दिल तक पहुँची तो Subscribe कीजिए।",
    "और गहरी कथाएँ आ रही हैं — Subscribe कर लीजिए।",
    "इस कथा को अपने बच्चों को भी सुनाइए।",
    "राधे राधे। Subscribe करके जुड़े रहिए।",
    "Subscribe कीजिए और घंटी दबा दीजिए, कोई कथा नहीं छूटेगी।",
    "अगर अंत तक सुना, तो एक Like ज़रूर कीजिए और Subscribe भी।",
    "हरे कृष्ण। ऐसी कथाओं के लिए चैनल से जुड़िए।",
    "ये कथा किसी अपने को Share कीजिए।",
    "जय कन्हैया लाल की। Subscribe करके परिवार का हिस्सा बनिए।",
    "अगली कथा और सुंदर है — Subscribe कर लीजिए।",
    "रोज़ एक कथा चाहिए तो Subscribe कीजिए।",
    "अगर मन को शांति मिली तो Subscribe कीजिए।",
    "Subscribe करके अगली कथा का इंतज़ार कीजिए।",
]

DESC_ABOUT_TEMPLATES = [
    "{channel} पर भगवान श्रीकृष्ण के जीवन की कथाएँ सरल हिंदी में सुनाई जाती हैं। "
    "हर कथा में एक साफ़ सीख होती है — सत्य, धैर्य, क्षमा, भक्ति — और वो कथा के "
    "साथ इतनी सहजता से आती है कि बच्चे भी अंत तक सुनते हैं।",
    "{channel} में आपका स्वागत है। यहाँ श्रीकृष्ण की बाल लीला से लेकर गीता के "
    "उपदेश तक, हर कथा शांत भाव और आसान भाषा में — ऐसी जिस पर बाद में बात की जा सके।",
    "{channel} रोज़ एक कथा लेकर आता है। रात को सोने से पहले, सफ़र में, या शांत "
    "दोपहर में — पूरे परिवार के साथ सुनने के लिए।",
]

WHO_ITS_FOR = [
    "किसके लिए: रात को सोने से पहले, परिवार के साथ, सफ़र में, और बच्चों की कथा-समय के लिए।",
    "4 से 10 साल के बच्चों के लिए, और उन बड़ों के लिए भी जिन्हें अच्छी कथा पसंद है।",
    "देखने से ज़्यादा सुनने के लिए बनाई गई है — लगाइए और शांति से सुनिए।",
]

PRODUCTION_NOTE = (
    "About this video: an original story written and narrated for this channel, "
    "illustrated with generated artwork and licensed royalty-free footage and music."
)

HASHTAG_CORE = ["#कृष्णकथा", "#श्रीकृष्ण", "#भक्ति"]
HASHTAG_ROTATE = [
    "#कृष्ण", "#krishna", "#कृष्णलीला", "#गीता", "#भगवद्गीता",
    "#महाभारत", "#mahabharat", "#राधेराधे", "#जयश्रीकृष्ण", "#हरेकृष्ण",
    "#हिंदीकहानी", "#पौराणिककथा", "#कथा", "#भक्तिकथा", "#सनातनधर्म",
    "#वृंदावन", "#राधाकृष्ण", "#जीवनसीख", "#प्रेरणा", "#अध्यात्म",
]


def build_hashtags(rng=None, count=8):
    rng = rng or random
    picked = list(HASHTAG_CORE[:2])
    picked.append(rng.choice(HASHTAG_CORE))
    picked.extend(rng.sample(HASHTAG_ROTATE, min(6, len(HASHTAG_ROTATE))))
    unique = list(dict.fromkeys(picked))
    return unique[: max(3, int(count))]


TAG_EVERGREEN = [
    "कृष्ण कथा", "krishna story in hindi", "श्रीकृष्ण कथा", "भक्ति कथा",
    "गीता उपदेश", "महाभारत कथा", "कृष्ण लीला", "hindi moral story",
    "पौराणिक कथा", "प्रेरणादायक कहानी", "krishna leela", "sanatan dharma",
    "कान्हा की कहानी", "hindi kahani", "धार्मिक कथा",
]

# YouTube enforces its 500-limit on snippet.tags against the UTF-8 ENCODING, not
# the character count, and it quotes any tag containing a space (costing 2 more
# bytes). On an English channel the difference is invisible - ASCII is 1 byte per
# character - but every Devanagari character is 3 bytes, so a set measuring a
# comfortable 385 "characters" is really 765 bytes. That is precisely how this
# channel's first real upload failed: reason=invalidTags, after the video had
# already rendered. Budget in bytes.
TAGS_BYTE_BUDGET = 440
TAG_MAX_BYTES = 90
TAG_MAX_LEN = 60


def _normalise_tag(tag):
    tag = re.sub(r"\s+", " ", str(tag or "").strip().lower()).strip(",")
    tag = tag[:TAG_MAX_LEN]
    # Trim by BYTES too - 60 Devanagari characters is 180 bytes.
    while len(tag.encode("utf-8")) > TAG_MAX_BYTES and tag:
        tag = tag[:-1]
    return tag.strip()


def build_tags(core_title="", moral="", keywords=None, rng=None, extra=None):
    rng = rng or random
    lesson = _lesson_from_moral(moral).lower()
    candidates = [_clean_core(core_title).lower()]
    if lesson:
        # Hindi patterns, not "{lesson} story". With a Hindi lesson word that
        # produced half-English tags like "क्षमा story", which nobody searches
        # for in either language.
        candidates += [lesson, f"{lesson} की कथा", f"{lesson} पर कथा"]
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
        # UTF-8 bytes, +1 separator, +2 where YouTube quotes the tag (any tag
        # containing a space). Characters would undercount Devanagari 3x.
        cost = len(tag.encode("utf-8")) + 1 + (2 if " " in tag else 0)
        if budget + cost > TAGS_BYTE_BUDGET:
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
