# -*- coding: utf-8 -*-
"""
Hindi SEO / metadata layer for Krishna Universe Shorts.

Builds a per-video title, description, tag set, hashtag set and pinned comment.

WHY THIS IS A MODULE AND NOT A FORMAT STRING
--------------------------------------------
The channel this pipeline was ported from had its metadata hard-coded in the
uploader: every upload got the same title suffix and the same hashtag block, so
100+ videos shared an identical metadata fingerprint. That is the pattern
YouTube's inauthentic-content policy describes as template-based, and it is also
simply invisible in search - a hundred videos all competing on the same string.

So every element is assembled per video from a rotating pool, drawn through
modules/history.py (no repeats until a pool is exhausted), and anchored on a
search phrase that matches what Hindi viewers actually type.

BILINGUAL ON PURPOSE
--------------------
Indian viewers search this niche in both scripts - "कृष्ण कथा" and "krishna
story in hindi" are both high-volume. Titles carry Devanagari (that is what the
audience reads in the feed) while tags carry both, because a romanised tag is
invisible to a Devanagari-only tag set and vice versa.
"""

import logging
import random
import re

from .config import get_cfg
from . import history

log = logging.getLogger("krishna.seo")


# ==========================================================================
# Leela category detection
# ==========================================================================
# Weighted token match. The narration's FIRST sentence is excluded before
# scoring: it is a randomly drawn hook from pools.HOOK_CANDIDATES and mentions
# whatever leela that hook happens to reference, which would mislabel the video.
# (The parent pipeline hit exactly this bug - kitten videos were being tagged
# with dog hashtags because of the hook sentence.)
_TOKEN_PATTERNS = {
    "bal_leela": (
        "माखन|मक्खन|यशोदा|नंद|गोकुल|पूतना|बचपन|बाल|ऊखल|दामोदर|तृणावर्त|"
        "शकटासुर|घुटनों|पालना|कारागार|देवकी|वसुदेव|कंस|जन्म|यमुना पार|"
        "makhan|yashoda|gokul|putana|bal|krishna janm"
    ),
    "vrindavan": (
        "वृंदावन|राधा|गोपी|बांसुरी|रास|गोवर्धन|कालिया|मोर|गाय|ग्वाल|"
        "यमुना|बरसाना|मुरली|प्रेम|सखा|दावानल|इंद्र|"
        "vrindavan|radha|gopi|bansuri|govardhan|kaliya|raas"
    ),
    "gita": (
        "गीता|उपदेश|अर्जुन|कर्म|कर्मयोग|आत्मा|निष्काम|स्थितप्रज्ञ|"
        "विश्वरूप|श्लोक|ज्ञान|योग|समत्व|मन को|संशय|"
        "gita|geeta|arjun|karma|updesh|shlok"
    ),
    "mahabharat": (
        "महाभारत|द्रौपदी|पांडव|कौरव|दुर्योधन|भीष्म|कर्ण|अभिमन्यु|बर्बरीक|"
        "चक्रव्यूह|कुरुक्षेत्र|सारथी|युद्ध|शकुनि|द्रोण|गांधारी|अश्वत्थामा|"
        "युधिष्ठिर|भीम|विदुर|हस्तिनापुर|"
        "mahabharat|draupadi|pandav|karna|barbarik|kurukshetra"
    ),
    "dwarka": (
        "द्वारका|रुक्मिणी|सत्यभामा|सुदामा|मथुरा|जरासंध|शिशुपाल|नरकासुर|"
        "स्यमंतक|उग्रसेन|संदीपनी|गुरुकुल|कुब्जा|अक्रूर|पारिजात|"
        "dwarka|rukmini|sudama|mathura|jarasandh"
    ),
    "bhakti": (
        "भक्ति|उद्धव|वैराग्य|शरण|समर्पण|नाम|कृपा|श्रद्धा|प्रार्थना|"
        "चौबीस गुरु|देह त्याग|प्रभास|जरा|क्षमा|"
        "bhakti|uddhav|sharan|kripa|vairagya"
    ),
}

_W_TITLE = 3
_W_KEYWORDS = 3
_W_BODY = 1
_PRESENCE_THRESHOLD = 2

DEFAULT_SUBJECT = "bhakti"


def _strip_hook_sentence(text):
    """Drop the first sentence - it is a randomly drawn hook, not story content.

    Splits on the Devanagari danda as well as western punctuation; splitting on
    '.' alone would leave a Hindi paragraph as a single sentence and strip the
    whole narration.
    """
    body = str(text or "").strip()
    parts = re.split(r"(?<=[।.!?])\s+", body, maxsplit=1)
    return parts[1] if len(parts) == 2 else body


def detect_subject(title="", text="", keywords=None):
    """Classify which part of Krishna's life this video is about.

    Weighted so the title and the footage keywords count for more than the body,
    because the body is long and mentions many names in passing.
    """
    kw_blob = " ".join(str(k) for k in (keywords or []))
    body = _strip_hook_sentence(text)

    scores = {}
    for name, pattern in _TOKEN_PATTERNS.items():
        rx = re.compile(pattern, re.IGNORECASE)
        score = (
            _W_TITLE * len(rx.findall(str(title or "")))
            + _W_KEYWORDS * len(rx.findall(kw_blob))
            + _W_BODY * len(rx.findall(body))
        )
        scores[name] = score

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < _PRESENCE_THRESHOLD:
        return DEFAULT_SUBJECT
    return best


# ==========================================================================
# Titles
# ==========================================================================
# The searchable phrase each title is anchored on. These are the terms Hindi
# viewers actually type; a title with none of them ranks for nothing.
SEARCH_ANCHORS = {
    "bal_leela": [
        "कृष्ण बाल लीला", "कान्हा की कहानी", "श्रीकृष्ण लीला", "कृष्ण जन्म कथा",
        "बाल कृष्ण कथा", "कान्हा की बाल लीला", "कृष्ण कथा हिंदी",
            "कान्हा की बचपन की कहानी", "बाल गोपाल कथा", "कृष्ण की बाल कथा",
    ],
    "vrindavan": [
        "वृंदावन की कथा", "राधा कृष्ण कथा", "कृष्ण लीला", "गोवर्धन कथा",
        "कान्हा की लीला", "राधा कृष्ण प्रेम कथा", "कृष्ण कथा",
            "वृंदावन लीला", "कृष्ण की लीला कथा", "ब्रज की कथा",
    ],
    "gita": [
        "गीता उपदेश", "भगवद गीता हिंदी", "गीता ज्ञान", "श्रीकृष्ण उपदेश",
        "गीता का सार", "कृष्ण अर्जुन संवाद", "गीता सीख",
            "गीता का उपदेश हिंदी", "श्रीमद्भगवद्गीता", "गीता अध्याय सार",
    ],
    "mahabharat": [
        "महाभारत कथा", "महाभारत की कहानी", "कृष्ण महाभारत", "महाभारत रहस्य",
        "महाभारत सीख", "महाभारत प्रसंग", "कृष्ण कथा महाभारत",
            "महाभारत का प्रसंग", "महाभारत हिंदी कथा", "महाभारत की सीख",
    ],
    "dwarka": [
        "श्रीकृष्ण कथा", "सुदामा चरित्र", "द्वारकाधीश कथा", "कृष्ण मथुरा कथा",
        "कृष्ण की कहानी", "रुक्मिणी विवाह कथा",
            "द्वारका की कथा", "कृष्ण द्वारका लीला", "श्रीकृष्ण जीवन कथा",
    ],
    # bhakti is DEFAULT_SUBJECT, so it is where the lesson-first reels land when
    # they name no specific leela. Its anchors are therefore weighted towards
    # what someone looking for a usable takeaway actually types, not towards
    # story titles.
    "bhakti": [
        "कृष्ण भक्ति कथा", "श्रीकृष्ण की सीख", "कान्हा की सीख", "कृष्ण उपदेश",
        "प्रेरणादायक कथा", "कृष्ण कथा हिंदी", "भक्ति कथा",
            "कृष्ण भक्ति की कथा", "श्रीकृष्ण महिमा", "भक्ति की सीख",
            "जीवन की सीख", "कृष्ण की अनमोल बातें", "श्रीकृष्ण के विचार",
            "जीवन बदलने वाली बात", "कान्हा की अनमोल सीख", "प्रेरणादायक विचार",
    ],
}

# 40 patterns. {core} is the story title, {anchor} the search phrase. A single
# fixed pattern is what made the parent channel's grid read as one video posted
# a hundred times.
TITLE_PATTERNS = [
    "{core} | {anchor}",
    "{anchor}: {core}",
    "{core} — {anchor}",
    "{core} | {anchor} #shorts",
    "{anchor} | {core}",
    "जब {core} | {anchor}",
    "{core}? | {anchor}",
    "सुनिए: {core} | {anchor}",
    "{core} की सीख | {anchor}",
    "{core} | एक सीख | {anchor}",
    "क्या आप जानते हैं? {core} | {anchor}",
    "{core} — ये सीख याद रखिए | {anchor}",
    "{core} | {anchor} | कृष्ण कथा",
    "एक कथा: {core} | {anchor}",
    "{core} | सबसे बड़ी सीख | {anchor}",
    "{anchor} — {core} की कहानी",
    "{core} | ये सुनकर सोच बदल जाएगी",
    "{core} | {anchor} | हिंदी कथा",
    "आज की कथा: {core} | {anchor}",
    "{core} | कान्हा की सीख | {anchor}",
    "{core} — {anchor} | Shorts",
    "{core} | {anchor} | प्रेरणा",
    "{core}! | {anchor}",
    "{anchor} | {core} | सीख",
    "{core} | अंत तक सुनिए | {anchor}",
    "{core} — क्यों? | {anchor}",
    "{core} | {anchor} | कथा और सीख",
    "जानिए {core} | {anchor}",
    "{core} | एक गहरी सीख | {anchor}",
    "{core} | {anchor} | भक्ति",
    "{core} की असली सीख | {anchor}",
    "{anchor}: {core} | सुनिए",
    "{core} | ये बात हर किसी को पता होनी चाहिए",
    "{core} | {anchor} | कृष्ण उपदेश",
    "{core} — {anchor} | हिंदी",
    "{core} | जीवन बदलने वाली सीख",
    "{anchor} | {core} — सुनिए",
    "{core} | {anchor} | आज की सीख",
    "{core} — सुनिए पूरी कथा | {anchor}",
    "{core} | {anchor} | Krishna Story",
    "{core} | {anchor} | सुनिए पूरी बात",
    "{anchor} | {core} | एक सीख",
    "{core} — इसका असली मतलब | {anchor}",
    "{core} | {anchor} | ज़रूर सुनिए",
    "क्यों? {core} | {anchor}",
    "{core} | {anchor} | भक्ति कथा",
    "{core} — ये किसी ने नहीं बताया | {anchor}",
    "{anchor} — {core} | सुनिए",
    "{core} | {anchor} | सीख भरी कथा",
    "{core} | एक-एक शब्द सुनिए | {anchor}",
    # SEEKH-FIRST PATTERNS. The list above is built around the word "कथा",
    # which is right for a retelling. The reels now lead with a takeaway the
    # viewer can use today (see gemini_script._PROMPT_TEMPLATE), and a title
    # promising a story while the video gives advice is a mismatch a viewer
    # punishes in the first two seconds. These promise the takeaway instead.
    "{core} | ये आज ही काम आएगा | {anchor}",
    "{core} — कान्हा की सीख | {anchor}",
    "अगर {core} | {anchor}",
    "{core} | बस इतना कीजिए | {anchor}",
    "{core}? कान्हा का जवाब | {anchor}",
    "{core} | 30 सेकंड में समझिए | {anchor}",
    "{core} — यही एक बात काफ़ी है | {anchor}",
    "{core} | आज से ये करके देखिए",
    "{core} | {anchor} | जीवन की सीख",
    "{core} — इसका असर आज दिखेगा | {anchor}",
    "{core} | ये गलती मत कीजिए | {anchor}",
    "{core} | कान्हा ने वजह भी बताई | {anchor}",
    "{core} — एक आदत, बड़ा फर्क | {anchor}",
    "{core} | {anchor} | रोज़ की सीख",
    "{core} | यही सबसे काम की बात है",
    "{core} — {anchor} | आज की बात",
    "{core} | {anchor} | कान्हा की कथा",
    "{core} | यही सबसे बड़ी बात है",
    "{anchor} | {core} — क्या हुआ था",
    "{core} — पूरी बात | {anchor}",
    "{core} | {anchor} | अद्भुत कथा",
    "{core} | सुनकर मन शांत हो जाएगा",
    "{anchor}: {core} — एक सीख",
    "{core} | {anchor} | अनसुनी कथा",
    "{core} — {anchor} | प्रेरणा",
]

# Phrases that are true of EVERY video on this channel, so they can be used to
# pad a description's first line without ever claiming the video is about a
# leela it does not tell. Deliberately separate from SEARCH_ANCHORS, whose
# entries name specific episodes.
GENERIC_ANCHORS = [
    "कृष्ण कथा", "कृष्ण कथा हिंदी", "श्रीकृष्ण की सीख", "कान्हा की कहानी",
    "कृष्ण लीला", "भक्ति कथा", "प्रेरणादायक कथा", "hindi krishna story",
]

TITLE_SOFT_LIMIT = 78
TITLE_HARD_LIMIT = 100


def _clean_core(core):
    """Strip legacy decoration so a title is never decorated twice."""
    s = " ".join(str(core or "").split())
    # Remove any trailing " | ..." / " — ..." the model may have added itself.
    s = re.sub(r"\s*[|—–]\s*[^|—–]*$", "", s) if s.count("|") + s.count("—") > 1 else s
    s = re.sub(r"#\S+", "", s).strip()
    return s.strip(" |—–:-") or "श्रीकृष्ण की एक सीख"


def build_title(core_title, text="", keywords=None, subject=None, rng=None):
    """Compose the published title: story core + a real search anchor."""
    rng = rng or random
    subject = subject or detect_subject(core_title, text, keywords)
    core = _clean_core(core_title)

    anchors = SEARCH_ANCHORS.get(subject) or SEARCH_ANCHORS[DEFAULT_SUBJECT]
    # PER-SUBJECT history key. A single shared "title_anchors" key put every
    # subject's anchors in one used-list, so a gita video would mark the whole
    # list dirty for the next vrindavan video, the small per-subject pool would
    # read as exhausted, and the draw would reset constantly - degrading to
    # near-random and colliding far more than the pool size implies. Keyed by
    # subject, each leela's anchors genuinely rotate without replacement.
    anchor = history.pick("title_anchors_" + subject, list(anchors)) or anchors[0]
    # Patterns are keyed per subject for the same reason. A single global pattern
    # pool cycles every 60 uploads, so a leela that comes up ~40 times across a
    # 90-day run kept landing on a pattern it had already used with the same
    # anchor. Keyed per subject, that leela's own videos walk the 60 patterns
    # nearly without repeating, which is what stops two tellings of the SAME
    # story from getting an identical title.
    pattern = (history.pick("title_patterns_" + subject, list(TITLE_PATTERNS))
               or TITLE_PATTERNS[0])

    title = pattern.format(core=core, anchor=anchor)
    title = " ".join(title.split())

    if len(title) > TITLE_SOFT_LIMIT:
        # Shorten the story core rather than dropping the anchor: the anchor is
        # the part that earns impressions.
        room = TITLE_SOFT_LIMIT - (len(title) - len(core))
        if room > 18:
            trimmed = core[:room].rstrip(" ,।-")
            title = " ".join(pattern.format(core=trimmed, anchor=anchor).split())
    if len(title) > TITLE_HARD_LIMIT:
        title = title[:TITLE_HARD_LIMIT].rstrip(" |—–:,")
    return title


# ==========================================================================
# Hashtags
# ==========================================================================
# Devanagari hashtags work on YouTube and are what this audience taps, but a
# few romanised ones are kept because search suggestions surface those too.
HASHTAG_CORE = ["#shorts", "#कृष्ण", "#krishna", "#भक्ति", "#कृष्णकथा"]

HASHTAG_SUBJECT = {
    "bal_leela": ["#बाललीला", "#कान्हा", "#गोकुल", "#कृष्णजन्म", "#ladduGopal"],
    "vrindavan": ["#वृंदावन", "#राधाकृष्ण", "#राधे", "#गोवर्धन", "#radhakrishna"],
    "gita": ["#गीता", "#भगवद्गीता", "#गीताज्ञान", "#bhagavadgita", "#गीतासार"],
    "mahabharat": ["#महाभारत", "#mahabharat", "#द्रौपदी", "#अर्जुन", "#कुरुक्षेत्र"],
    "dwarka": ["#द्वारकाधीश", "#सुदामा", "#मथुरा", "#रुक्मिणी", "#dwarka"],
    "bhakti": ["#भक्तिकथा", "#राधेराधे", "#जयश्रीकृष्ण", "#हरेकृष्ण", "#bhakti"],
}

HASHTAG_EMOTION = [
    "#प्रेरणा", "#सीख", "#जीवनसीख", "#motivation", "#प्रेरणादायक",
    "#अध्यात्म", "#सत्य", "#धर्म", "#शांति", "#विश्वास",
]

HASHTAG_DISCOVERY = [
    "#हिंदीकहानी", "#कथा", "#storytime", "#हिंदी", "#पौराणिककथा",
    "#sanatandharma", "#भारत", "#shortsfeed", "#shortsviral", "#ytshorts",
    "#हिंदीकथा", "#धर्म", "#krishnalove", "#radhekrishna", "#jaishreekrishna",
    "#हरेकृष्ण", "#मंदिर", "#आस्था", "#indianmythology", "#devotional",
]

# NOTE ON "PUT EVERY VIRAL HASHTAG ON IT"
# ---------------------------------------
# Two hard limits make maximising the COUNT counter-productive:
#
#   1. YouTube ignores ALL hashtags on a video that carries more than 15. So 30
#      hashtags does not mean triple the reach - it means ZERO working hashtags.
#      build_hashtags() is therefore capped at 14, which uses nearly the whole
#      usable budget with one slot of headroom.
#
#   2. Hashtags are a TARGETING signal, not a lottery ticket. Generic tags like
#      #viral or #funny on a Krishna katha tell YouTube to test the video against
#      an audience that did not come for devotional content. Those viewers swipe
#      immediately, the video's early retention drops, and that weak signal
#      follows it - so an irrelevant "viral" tag actively reduces reach instead of
#      adding to it. Broad-but-relevant discovery tags (#shortsviral, #ytshorts,
#      #devotional) are kept; pure bait like #viral, #funny and #memes is not.
#
# Reach on this niche comes from the hook, the first frame and retention, which is
# where the flash text, thumbnail and 24-move motion engine are aimed.


def build_hashtags(subject=None, rng=None, count=9):
    """Per-video hashtag set.

    Capped below 15 because YouTube ignores ALL hashtags on a video carrying
    more than 15 - an easy way to accidentally have none work at all.
    """
    rng = rng or random
    subject = subject or DEFAULT_SUBJECT
    count = max(3, min(int(count), 14))

    tags = list(HASHTAG_CORE[:3])
    subj = list(HASHTAG_SUBJECT.get(subject, HASHTAG_SUBJECT[DEFAULT_SUBJECT]))
    rng.shuffle(subj)
    tags += subj[:3]

    extras = list(HASHTAG_EMOTION) + list(HASHTAG_DISCOVERY)
    rng.shuffle(extras)
    for tag in extras:
        if len(tags) >= count:
            break
        if tag not in tags:
            tags.append(tag)

    out = []
    for tag in tags:
        if tag not in out:
            out.append(tag)
    return out[:count]


# ==========================================================================
# Tags
# ==========================================================================
TAG_EVERGREEN = [
    "कृष्ण कथा", "krishna story in hindi", "श्रीकृष्ण", "krishna", "भक्ति कथा",
    "hindi moral story", "प्रेरणादायक कहानी", "कृष्ण उपदेश", "sanatan dharma",
    "hindi story", "कृष्ण की कहानी", "krishna leela",
]

TAG_SUBJECT = {
    "bal_leela": [
        "कृष्ण बाल लीला", "bal krishna", "कान्हा की कहानी", "krishna janmashtami",
        "यशोदा कृष्ण", "गोकुल कथा", "makhan chor", "कृष्ण जन्म कथा",
    ],
    "vrindavan": [
        "वृंदावन कथा", "राधा कृष्ण", "radha krishna story", "गोवर्धन लीला",
        "कालिया नाग", "बांसुरी", "vrindavan", "राधे राधे",
    ],
    "gita": [
        "भगवद गीता", "bhagavad gita in hindi", "गीता उपदेश", "गीता सार",
        "गीता ज्ञान", "krishna arjun", "कर्म योग", "gita saar",
    ],
    "mahabharat": [
        "महाभारत कथा", "mahabharat story", "द्रौपदी", "कर्ण", "अभिमन्यु",
        "बर्बरीक", "कुरुक्षेत्र", "mahabharat in hindi",
    ],
    "dwarka": [
        "सुदामा चरित्र", "sudama krishna", "द्वारका", "रुक्मिणी विवाह",
        "मथुरा कथा", "कंस वध", "dwarkadhish",
    ],
    "bhakti": [
        "भक्ति", "उद्धव गीता", "कृष्ण भजन कथा", "आध्यात्मिक कहानी",
        "जय श्री कृष्ण", "hare krishna", "राधे राधे",
    ],
}

# YouTube enforces its 500-limit on snippet.tags against the UTF-8 ENCODING, not
# the character count, and it quotes any tag containing a space (costing 2 more
# bytes). On an English channel the difference is invisible - ASCII is 1 byte per
# character - but every Devanagari character is 3 bytes, so a set measuring a
# comfortable 385 "characters" is really 765 bytes. That is precisely how this
# channel's first real upload failed: reason=invalidTags, after the video had
# already rendered. Budget in bytes.
TAGS_BYTE_BUDGET = 440  # under 500 with headroom for the uploader's own guard
TAG_MAX_BYTES = 90      # one overlong tag just burns budget


def _normalise_tag(tag):
    return " ".join(str(tag or "").replace(",", " ").split()).strip()


def _tag_cost(tag):
    """Bytes this tag consumes in YouTube's budget: UTF-8 length, +1 separator,
    +2 if YouTube must quote it (it quotes any tag containing a space)."""
    return len(tag.encode("utf-8")) + 1 + (2 if " " in tag else 0)


def build_tags(core_title="", keywords=None, subject=None, rng=None, extra=None):
    """Per-video tag list, ordered most specific first and budget-capped.

    Specific first matters because the budget cuts from the end: if the generic
    "hindi story" tags led, the leela-specific ones would be the ones dropped.
    """
    rng = rng or random
    subject = subject or detect_subject(core_title, "", keywords)

    ordered = []

    # Leela-specific first.
    subj = list(TAG_SUBJECT.get(subject, TAG_SUBJECT[DEFAULT_SUBJECT]))
    rng.shuffle(subj)
    ordered += subj

    # Then anything meaningful from the title.
    core = _clean_core(core_title)
    if core:
        ordered.append(core)

    # Then the anchors for this leela (real search phrases).
    ordered += list(SEARCH_ANCHORS.get(subject, []))[:3]

    # Then any caller extras and the atmosphere keywords.
    for item in (extra or []):
        ordered.append(item)
    for item in (keywords or []):
        ordered.append(item)

    # Evergreen last - dropped first if the budget runs out.
    ever = list(TAG_EVERGREEN)
    rng.shuffle(ever)
    ordered += ever

    out = []
    seen = set()
    used = 0
    for raw in ordered:
        tag = _normalise_tag(raw)
        if not tag or len(tag.encode("utf-8")) > TAG_MAX_BYTES:
            continue
        key = tag.lower()
        if key in seen:
            continue
        cost = _tag_cost(tag)
        if used + cost > TAGS_BYTE_BUDGET:
            continue
        seen.add(key)
        out.append(tag)
        used += cost
    return out


# ==========================================================================
# Description
# ==========================================================================
DESC_OPENERS = [
    "आज की कथा:",
    "सुनिए एक कथा:",
    "श्रीकृष्ण की एक लीला:",
    "एक छोटी कथा, एक बड़ी सीख:",
    "आज की सीख:",
    "कान्हा की एक लीला:",
    "ये कथा ध्यान से सुनिए:",
    "एक प्रसंग:",
    "आज का प्रसंग:",
    "एक कथा जो सोच बदल देती है:",
    "कृष्ण कथा:",
    "सुनिए और सोचिए:",
    "आज की कृष्ण कथा:",
    "एक लीला, एक सीख:",
    "ये बात याद रखने वाली है:",
    "श्रीकृष्ण कहते हैं:",
    "एक कथा आपके लिए:",
    "आज की भक्ति कथा:",
    "एक कथा जो बार-बार याद आती है:",
    "आज सुनिए ये प्रसंग:",
    "श्रीकृष्ण की एक अनसुनी बात:",
    "ये कथा हर किसी को पता होनी चाहिए:",
    "एक छोटी घटना, बड़ी सीख:",
    "सुनिए, और ठहर कर सोचिए:",
    "आज का प्रसंग कुछ खास है:",
    "कान्हा की एक और लीला:",
    "ये कथा दिल को छू जाती है:",
    "एक सवाल का जवाब इस कथा में है:",
    "श्रीकृष्ण ने क्या सिखाया, सुनिए:",
    "आज की कथा और उसकी सीख:",
    "एक प्रसंग जो सोच बदल देता है:",
    "सुनिए ये पुरानी कथा:",
    "कान्हा का एक और रूप:",
    "आज की बात ध्यान से सुनिए:",
    "एक कथा, एक जवाब:",
    "श्रीकृष्ण की लीला और उसका अर्थ:",
    "ये प्रसंग आपके काम आएगा:",
    "आज सुनिए कान्हा की ये कथा:",
    "एक कथा जो शांति देती है:",
    "श्रीकृष्ण की सीख, आसान शब्दों में:",
]

DESC_QUESTIONS = [
    "आपको इस कथा से क्या सीख मिली? कमेंट में लिखिए।",
    "आप इस बारे में क्या सोचते हैं? नीचे बताइए।",
    "क्या आपने ये कथा पहले सुनी थी? कमेंट कीजिए।",
    "इस सीख में से कौन सी बात आपको सबसे अच्छी लगी?",
    "कमेंट में जय श्री कृष्ण लिखिए।",
    "आपके जीवन में ये सीख कब काम आई? बताइए।",
    "अगली कथा किस लीला पर चाहिए? कमेंट कीजिए।",
    "क्या आप इस बात से सहमत हैं? कमेंट में लिखिए।",
    "कमेंट में राधे राधे लिखकर बताइए।",
    "इस कथा का कौन सा हिस्सा दिल को छू गया?",
    "आप कहाँ से सुन रहे हैं? कमेंट में शहर का नाम लिखिए।",
    "ये सीख किसे भेजना चाहेंगे? टैग कीजिए।",
    "आपकी सबसे पसंदीदा कृष्ण लीला कौन सी है?",
    "क्या ये बात आज भी लागू होती है? बताइए।",
    "अगर सहमत हैं तो एक कमेंट कर दीजिए।",
    "कमेंट में हरे कृष्ण लिखिए।",
    "आपको कान्हा की कौन सी बात सबसे अच्छी लगती है?",
    "इस पर आपकी राय क्या है? नीचे लिखिए।",
    "क्या आपने गीता पढ़ी है? कमेंट में बताइए।",
    "आपका आज का दिन कैसा जा रहा है? बताइए।",
    "अगली सीख के लिए क्या सुनना चाहेंगे?",
    "ये कथा किसे याद दिलाना चाहेंगे?",
    "कमेंट में एक शब्द लिखिए — कृष्ण।",
    "आपके घर में कौन सी कथा सबसे ज़्यादा सुनाई जाती है?",
    "आपने ये कथा पहले कहाँ सुनी थी? कमेंट कीजिए।",
    "इस सीख को एक लाइन में अपने शब्दों में लिखिए।",
    "कान्हा की कौन सी लीला आपको सबसे प्यारी लगती है?",
    "क्या आप रोज़ कृष्ण कथा सुनते हैं? बताइए।",
    "इस कथा में सबसे अच्छा हिस्सा कौन सा था?",
    "आप किस शहर से सुन रहे हैं? कमेंट कीजिए।",
    "कमेंट में जय कन्हैया लाल की लिखिए।",
    "ये सीख आपके किस काम आएगी? बताइए।",
    "अगर सहमत हैं तो एक ❤️ कमेंट कीजिए।",
    "आपके परिवार में ये कथा कौन सुनाता था?",
    "क्या ये बात आज भी लागू होती है? कमेंट कीजिए।",
    "कमेंट में राधे कृष्णा लिखिए।",
    "आपको कौन सी सीख सबसे ज़्यादा छू गई?",
    "इस कथा पर आपकी राय क्या है? लिखिए।",
    "अगली बार कौन सी लीला सुनाऊँ? बताइए।",
    "क्या आपने कभी ऐसा अनुभव किया है? कमेंट कीजिए।",
]

DESC_CTAS = [
    "ऐसी ही कथाओं के लिए चैनल को Subscribe कर लीजिए।",
    "रोज़ एक नई कथा के लिए Subscribe कीजिए और घंटी दबा दीजिए।",
    "अगर अच्छा लगा तो Like और Subscribe कर दीजिए।",
    "कृष्ण कथाएँ रोज़ पाने के लिए Subscribe कीजिए।",
    "चैनल Subscribe करके हमारा साथ दीजिए।",
    "और कथाएँ आ रही हैं — Subscribe कर लीजिए।",
    "इस कथा को अपनों के साथ शेयर कीजिए।",
    "Subscribe कीजिए, रोज़ एक सीख मिलेगी।",
    "अगर दिल को छुआ तो Like कीजिए और चैनल Subscribe कर लीजिए।",
    "जय श्री कृष्ण। चैनल से जुड़े रहिए।",
    "राधे राधे। Subscribe करके साथ बने रहिए।",
    "नई कथा छूट न जाए — Subscribe करके घंटी दबा दीजिए।",
    "एक Share किसी का दिन बदल सकता है।",
    "Subscribe करके इस परिवार का हिस्सा बनिए।",
    "हरे कृष्ण। रोज़ मिलते हैं एक नई कथा के साथ।",
    "अगर सीख काम की लगी तो शेयर कीजिए।",
    "Like, Share और Subscribe — बस इतना ही।",
    "अगली कथा के लिए जुड़े रहिए।",
    "रोज़ एक कथा चाहिए तो Subscribe कर लीजिए।",
    "कान्हा की और कथाओं के लिए Subscribe कीजिए।",
    "अगर ये सीख काम की लगी तो Share कीजिए।",
    "Subscribe करके घंटी दबा दीजिए, कोई कथा नहीं छूटेगी।",
    "जय कन्हैया लाल की। Subscribe करके साथ दीजिए।",
    "ये कथा किसी अपने को Share कीजिए।",
    "और गहरी कथाएँ आ रही हैं — Subscribe कीजिए।",
    "अगर मन शांत हुआ तो Like और Subscribe कीजिए।",
    "राधे राधे। Subscribe करके जुड़े रहिए।",
    "अगली कथा और भी सुंदर है — Subscribe कर लीजिए।",
    "Subscribe कीजिए, रोज़ एक सीख आपके पास आएगी।",
    "इस कथा को अपने बच्चों को भी सुनाइए, और चैनल Subscribe कीजिए।",
    "हरे कृष्ण। चैनल Subscribe करके साथ चलिए।",
    "एक Share से ये कथा किसी और तक पहुँच जाएगी।",
    "अगर अंत तक सुना तो Subscribe ज़रूर कीजिए।",
    "जय श्री कृष्ण। Subscribe करके परिवार का हिस्सा बनिए।",
    "और कथाएँ सुनने के लिए Follow कर लीजिए।",
    "अगर दिल को अच्छा लगा तो Share कीजिए।",
    "Subscribe कीजिए और रोज़ एक कथा सुनिए।",
    "राधे राधे। साथ बने रहिए, कथाएँ जारी हैं।",
    "इस कथा को Share कीजिए, किसी का दिन बन जाएगा।",
    "Subscribe करके अगली कथा का इंतज़ार कीजिए।",
]

DESC_ABOUT = [
    "इस चैनल पर भगवान श्रीकृष्ण के जीवन की लीलाएँ और उनसे मिलने वाली सीख सरल हिंदी में सुनाई जाती है।",
    "यहाँ आपको श्रीकृष्ण की बाल लीला से लेकर गीता के उपदेश तक, हर कथा छोटी और सरल भाषा में मिलेगी।",
    "कृष्ण कथा, महाभारत के प्रसंग और गीता की सीख — रोज़ एक नई कथा, आसान हिंदी में।",
    "बच्चों और बड़ों, दोनों के लिए — श्रीकृष्ण की कथाएँ और जीवन में काम आने वाली सीख।",
    "श्रीकृष्ण की लीलाएँ, महाभारत के प्रसंग और भगवद गीता का सार — छोटी कथाओं में।",
]

# Stated openly rather than hidden. Undisclosed synthetic narration and imagery
# is a disclosure problem on YouTube, and being upfront costs nothing while
# removing a genuine review risk on a channel of this type.
PRODUCTION_NOTE = (
    "नोट: ये कथाएँ प्रचलित पौराणिक कथाओं पर आधारित हैं। दृश्य और आवाज़ "
    "AI की सहायता से बनाए गए हैं। किसी की भावनाओं को ठेस पहुँचाने का "
    "उद्देश्य नहीं है।"
)


# Minimum length for the description's first line. Only the opening ~100 chars
# show in search results and above the "...more" fold, so a short first line
# throws away the single most valuable piece of description real estate.
FIRST_LINE_TARGET = 78


def _teaser(text, max_chars=160):
    """A short teaser from the STORY, skipping the randomly drawn hook sentence.

    The first sentence is a rotating hook, so including it would make many
    descriptions open on the same line - the exact thing this module exists to
    prevent.
    """
    body = _strip_hook_sentence(text)
    body = " ".join(str(body or "").split())
    if not body:
        return ""
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    for sep in ("। ", ". ", ", "):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.5:
            return cut[: idx + 1].strip()
    return cut.rsplit(" ", 1)[0] + "..."


def build_description(core_title, text="", seekh="", subject=None, hashtags=None,
                      keywords=None, rng=None, apply_line=""):
    """Assemble the video description.

    Structure is deliberate: the searchable line comes FIRST because only the
    opening ~100 characters show in search results and above the "more" fold.
    """
    rng = rng or random
    subject = subject or detect_subject(core_title, text, keywords)
    anchors = SEARCH_ANCHORS.get(subject) or SEARCH_ANCHORS[DEFAULT_SUBJECT]
    anchor = rng.choice(list(anchors))

    opener = history.pick("desc_openers", list(DESC_OPENERS)) or DESC_OPENERS[0]
    question = history.pick("desc_questions", list(DESC_QUESTIONS)) or DESC_QUESTIONS[0]
    cta = history.pick("desc_ctas", list(DESC_CTAS)) or DESC_CTAS[0]
    about = rng.choice(list(DESC_ABOUT))

    core = _clean_core(core_title)
    teaser = _teaser(text)

    # A SECOND anchor goes on the first line too. Hindi is far more compact than
    # English - the same sentence is ~30% fewer characters - so a single-anchor
    # opener produced a search snippet of barely 50 characters, which wastes the
    # only part of the description that shows in search results and above the
    # "...more" fold. Two anchors fill that line with real query surface instead
    # of padding it.
    # Pad the first line with GENERIC anchors, never with the leela-specific
    # ones. Padding from SEARCH_ANCHORS looked fine until a Kaliya-naag video
    # came out carrying "गोवर्धन कथा" in its opening line - a real, different
    # leela that the video does not tell. That is misleading to a viewer and
    # reads as keyword stuffing to YouTube. The generic phrases are true of every
    # video on the channel, so they can pad safely.
    padding = [a for a in GENERIC_ANCHORS if a != anchor]
    rng.shuffle(padding)

    parts = []
    first = f"{opener} {core} — {anchor}"
    for extra in padding:
        if len(first) >= FIRST_LINE_TARGET:
            break
        first += f" | {extra}"
    parts.append(first)
    if teaser:
        parts.append("")
        parts.append(teaser)
    if seekh:
        parts.append("")
        parts.append(f"सीख: {str(seekh).strip().rstrip('।')}।")
    # The application line, verbatim from the script. Two reasons it is worth its
    # own line: it is the only part of the description that is about the VIEWER
    # rather than about Krishna, and because it is unique per reel it keeps the
    # middle of the description from collapsing into the same generic sentence on
    # every upload.
    if str(apply_line or "").strip():
        parts.append(f"आज कैसे लगाएँ: {str(apply_line).strip().rstrip('।')}।")
    parts.append("")
    parts.append(question)
    parts.append("")
    parts.append(cta)

    channel_url = get_cfg("seo.channel_url", "")
    if channel_url:
        parts.append(channel_url)

    parts.append("")
    parts.append(about)
    parts.append("")
    parts.append(PRODUCTION_NOTE)

    if hashtags:
        parts.append("")
        parts.append(" ".join(hashtags))

    return "\n".join(parts).strip()


# ==========================================================================
# Pinned comment
# ==========================================================================
# Posted manually: the upload token carries only the youtube.upload scope, which
# cannot write comments, and there is no API to PIN one at all. generate.py logs
# the suggested text so it can be pasted in seconds.
PINNED_COMMENTS = [
    "आपको इस कथा से क्या सीख मिली? कमेंट में लिखिए 👇",
    "कमेंट में जय श्री कृष्ण लिखिए 🙏",
    "आपकी सबसे पसंदीदा कृष्ण लीला कौन सी है? बताइए 👇",
    "क्या आप इस सीख से सहमत हैं? हाँ या ना 👇",
    "कमेंट में राधे राधे लिखकर आशीर्वाद लीजिए 🙏",
    "अगली कथा किस पर चाहिए? कमेंट कीजिए 👇",
    "आप कहाँ से सुन रहे हैं? शहर का नाम लिखिए 👇",
    "ये सीख किसे भेजना चाहेंगे? टैग कीजिए 👇",
    "कमेंट में हरे कृष्ण लिखिए 🙏",
    "इस कथा का कौन सा हिस्सा दिल को छू गया? 👇",
    "आपके जीवन में ये सीख कब काम आई? बताइए 👇",
    "क्या आपने ये कथा पहले सुनी थी? हाँ या ना 👇",
    "कमेंट में एक शब्द लिखिए — कृष्ण 🦚",
    "गीता की कौन सी बात आपको सबसे अच्छी लगती है? 👇",
    "अगर दिल को छुआ तो एक 🙏 कमेंट कर दीजिए",
    "आज का दिन कैसा जा रहा है? बताइए 👇",
    "आपके घर में कौन सी कथा सबसे ज़्यादा सुनाई जाती है? 👇",
    "कमेंट में जय कन्हैया लाल की लिखिए 🙏",
    "ये बात आपको कैसी लगी? एक लाइन में लिखिए 👇",
    "किस लीला पर अगली कथा बनाऊँ? कमेंट कीजिए 👇",
    "अगर सहमत हैं तो ❤️ कमेंट कीजिए",
    "आपका पसंदीदा कृष्ण नाम कौन सा है? 👇",
    "क्या आप रोज़ कृष्ण कथा सुनते हैं? बताइए 👇",
    "कमेंट में राधे कृष्णा लिखिए 🦚",
    "इस सीख को एक लाइन में अपने शब्दों में लिखिए 👇",
    "आपको कान्हा की कौन सी बात सबसे प्यारी लगती है? 👇",
    "कमेंट में अपना नाम और जय श्री कृष्ण लिखिए 🙏",
    "अगर काम की बात लगी तो शेयर कीजिए और कमेंट कीजिए 👇",
    "आप किस उम्र से कृष्ण कथा सुन रहे हैं? 👇",
    "क्या आपको ये कथा पहले से पता थी? हाँ या ना 👇",
    "आपके परिवार में ये कथा कौन सुनाता था? 👇",
    "ये कथा किसे भेजना चाहेंगे? टैग कीजिए 👇",
    "आपको कौन सी सीख सबसे ज़्यादा छू गई? 👇",
    "अगली कथा किस लीला पर बनाऊँ? कमेंट कीजिए 👇",
    "अगर सहमत हैं तो एक 🙏 कमेंट कर दीजिए",
    "आप किस शहर से सुन रहे हैं? नाम लिखिए 👇",
    "क्या आपने कभी ऐसा अनुभव किया है? बताइए 👇",
]


def build_pinned_comment(rng=None):
    return history.pick("pinned", list(PINNED_COMMENTS)) or PINNED_COMMENTS[0]


# ==========================================================================
# Public API
# ==========================================================================
def build_metadata(core_title, text="", keywords=None, rng=None, seekh="",
                   apply_line=""):
    """Build the complete metadata bundle for one video.

    Returned keys are kept identical to the parent pipeline so generate.py, the
    uploader, retitle_existing.py and seo_report.py all keep working.
    """
    rng = rng or random
    subject = detect_subject(core_title, text, keywords)

    hashtags = build_hashtags(
        subject=subject, rng=rng, count=int(get_cfg("seo.hashtag_count", 9))
    )
    title = build_title(core_title, text=text, keywords=keywords, subject=subject, rng=rng)
    description = build_description(
        core_title, text=text, seekh=seekh, subject=subject,
        hashtags=hashtags, keywords=keywords, rng=rng, apply_line=apply_line,
    )
    tags = build_tags(core_title=core_title, keywords=keywords, subject=subject, rng=rng)

    return {
        "subject": subject,
        "youtube_title": title,
        "youtube_description": description,
        "youtube_tags": tags,
        "hashtags": hashtags,
        "pinned_comment": build_pinned_comment(rng=rng),
    }
