# -*- coding: utf-8 -*-
"""
SEO / metadata layer for Krishna Universe Shorts (Hindi).

WHAT THIS REPLACES
------------------
In the pipeline this was ported from, metadata was assembled in five different
places and every one of them was fixed: the uploader appended an identical
"| Cute & Wholesome #shorts #cute" suffix to every title, the same eight hashtags
went on every video, and the description was the narration pasted verbatim plus
boilerplate. Across 113 uploads that produced one identical metadata fingerprint,
which is precisely the pattern YouTube's inauthentic-content policy describes as
"mass-produced and repetitious".

So everything here is per-video and drawn through modules/history.py (no
repeats until a pool is exhausted):

  build_title        -> Hindi title, search anchor first, 40 rotating patterns
  build_hashtags     -> per-video Hindi + English hashtag mix
  build_tags         -> tag set packed into YouTube's 500-character budget
  build_description  -> hook line, teaser, lesson, question, sign-off, tags
  build_pinned_comment
  build_metadata     -> all of the above in one call

LANGUAGE CHOICE
---------------
Titles and descriptions are Hindi, because the audience is Indian and Hindi
queries are what this content actually ranks for. Tags carry BOTH scripts: real
users search "krishna katha" in Latin script as often as "कृष्ण कथा", and tags
are the cheap place to cover both without making the title look like keyword
soup.
"""

import logging
import random
import re

from .config import get_cfg
from . import history

log = logging.getLogger("krishna.seo")


# ==========================================================================
# Which part of Krishna's life is this?
# ==========================================================================
# Used for three things: choosing the search anchor, choosing hashtags, and
# choosing which real-footage atmosphere set the composer should cut to. Getting
# it wrong is not cosmetic -- a Kurukshetra story tagged as a Gokul bal-leela is
# served to the wrong audience and dies.
#
# Scoring is WEIGHTED BY SOURCE rather than first-match. The narration's opening
# sentence is a randomly drawn hook that frequently names an unrelated character
# ("कृष्ण ने अर्जुन से कहा..." on a Gokul story), so a naive scan of the full text
# mislabels a large share of reels. Title and keywords are trusted most; the
# hook sentence is excluded outright.
_THEME_TOKENS = {
    "janm": ["कारागार", "जन्म", "देवकी", "वसुदेव", "कंस का भय", "आधी रात", "गर्भ"],
    "gokul": ["गोकुल", "यशोदा", "नंद", "माखन", "मटकी", "बाल", "गाय", "ग्वाल", "मिट्टी", "रस्सी", "दामोदर", "पूतना", "शकटासुर", "तृणावर्त"],
    "vrindavan": ["वृंदावन", "राधा", "बाँसुरी", "मुरली", "यमुना", "गोपी", "ग्वालिन", "मोर", "कालिया", "अघासुर", "धेनुकासुर", "प्रलंब"],
    "govardhan": ["गोवर्धन", "इंद्र", "बरसात", "वर्षा", "छत्र", "पर्वत"],
    "mathura": ["मथुरा", "कंस", "अक्रूर", "कुब्जा", "चाणूर", "मुष्टिक", "धनुष", "उग्रसेन", "धोबी"],
    "dwarka": ["द्वारका", "रुक्मिणी", "सत्यभामा", "जरासंध", "कालयवन", "स्यमंतक", "नरकासुर", "समुद्र", "मुचुकुंद"],
    "kurukshetra": ["कुरुक्षेत्र", "अर्जुन", "युद्ध", "भीष्म", "कर्ण", "अभिमन्यु", "चक्रव्यूह", "दुर्योधन", "द्रौपदी", "गांडीव", "बर्बरीक", "घटोत्कच", "युधिष्ठिर", "एकलव्य", "पांडव", "सारथी"],
    "gita": ["गीता", "आत्मा", "कर्म", "फल की चिंता", "क्रोध", "संदेह", "स्थिर", "अध्याय", "उपदेश", "धर्म"],
    "sudama": ["सुदामा", "चावल", "पोटली", "सांदीपनि", "गुरु", "आश्रम", "मित्र", "दोस्ती", "विदुर"],
    "ant": ["प्रभास", "उद्धव", "गांधारी", "श्राप", "शिकारी", "शरीर छोड़", "अंतिम", "पीपल"],
}

DEFAULT_THEME = "gita"

_W_TITLE = 3
_W_KEYWORDS = 2
_W_LESSON = 2
_W_BODY = 1


def _strip_hook_sentence(text):
    """Drop the first sentence: it is a randomly drawn hook, not story content.

    Hindi sentences end in a danda as often as a full stop, so both count.
    """
    body = str(text or "").strip()
    parts = re.split(r"(?<=[।.!?])\s+", body, maxsplit=1)
    return parts[1] if len(parts) == 2 else body


def detect_leela(title="", text="", keywords=None, lesson=""):
    """Return the theme key for this story (see _THEME_TOKENS)."""
    sources = (
        (str(title or ""), _W_TITLE),
        (" ".join(str(k) for k in (keywords or [])), _W_KEYWORDS),
        (str(lesson or ""), _W_LESSON),
        (_strip_hook_sentence(text), _W_BODY),
    )
    scores = {}
    for theme, tokens in _THEME_TOKENS.items():
        score = 0
        for blob, weight in sources:
            if not blob:
                continue
            for tok in tokens:
                if tok in blob:
                    score += weight
        if score:
            scores[theme] = score
    if not scores:
        return DEFAULT_THEME
    best = max(scores.values())
    # Deterministic tie-break so the same story always resolves the same way.
    winners = sorted(t for t, s in scores.items() if s == best)
    return winners[0]


# ==========================================================================
# Titles
# ==========================================================================
# The anchor goes FIRST. YouTube truncates in the feed and search snippet, and a
# title that opens with the searchable phrase both ranks and reads better than
# one that buries it behind a clever clause.
SEARCH_ANCHORS = {
    "janm": ["कृष्ण जन्म कथा", "श्रीकृष्ण जन्म", "कृष्ण कथा"],
    "gokul": ["कृष्ण बाल लीला", "बाल कृष्ण कथा", "कृष्ण लीला"],
    "vrindavan": ["कृष्ण लीला", "वृंदावन की कथा", "राधा कृष्ण कथा"],
    "govardhan": ["गोवर्धन लीला", "कृष्ण लीला", "कृष्ण कथा"],
    "mathura": ["कृष्ण कथा", "कंस वध कथा", "श्रीकृष्ण कथा"],
    "dwarka": ["द्वारकाधीश कथा", "श्रीकृष्ण कथा", "कृष्ण कथा"],
    "kurukshetra": ["महाभारत कथा", "कृष्ण अर्जुन संवाद", "महाभारत की सीख"],
    "gita": ["भगवद गीता ज्ञान", "गीता उपदेश", "गीता सार"],
    "sudama": ["कृष्ण सुदामा कथा", "कृष्ण कथा", "सच्ची मित्रता"],
    "ant": ["श्रीकृष्ण कथा", "कृष्ण की सीख", "कृष्ण कथा"],
}

# Secondary phrases that widen the query surface without changing meaning.
QUALIFIERS = [
    "जो हर किसी को जाननी चाहिए",
    "एक अनसुनी बात",
    "आज भी लागू होती है",
    "जीवन बदल देने वाली सीख",
    "सबसे गहरी सीख",
    "जो सब भूल गए",
    "हर घर की कहानी",
    "एक छोटी सी बात",
    "जिसने सबको चुप कर दिया",
    "समझ लो तो जीवन आसान",
]

TITLE_PATTERNS = [
    "{anchor}: {core}",
    "{anchor} | {core}",
    "{anchor} - {core}",
    "{core} | {anchor}",
    "{anchor}: {core} | {qual}",
    "{core} - {anchor}",
    "{anchor} | {core} | {qual}",
    "{core} | {anchor} | {qual}",
    "{anchor}: {qual} | {core}",
    "{core}: {qual} | {anchor}",
    "{anchor} | {qual}",
    "{core} | {qual} | {anchor}",
    "{anchor} - {core} | {qual}",
    "{core} - {qual} | {anchor}",
    "{anchor}: {core} - {qual}",
    "{qual} | {anchor}: {core}",
    "{anchor} | जानिए {core}",
    "{core} | {anchor} की सीख",
    "{anchor}: क्यों {core}",
    "{core} | श्रीकृष्ण की सीख | {anchor}",
]

TITLE_SOFT_LIMIT = 70
TITLE_HARD_LIMIT = 100


def _clean_core(core):
    """Strip any legacy suffix / stray hashtags out of the model's title."""
    s = " ".join(str(core or "").split())
    s = re.sub(r"\s*[|\-–—]\s*(Cute & Wholesome|Krishna Universe).*$", "", s, flags=re.I)
    s = re.sub(r"#\w+", "", s)
    s = s.strip(" |-–—:।")
    return s or "कृष्ण की एक सीख"


def build_title(core_title, text="", keywords=None, theme=None, lesson="", rng=None):
    """Assemble a per-video Hindi title. Never returns a fixed suffix."""
    rng = rng or random
    theme = theme or detect_leela(core_title, text, keywords, lesson)
    core = _clean_core(core_title)
    anchor = rng.choice(SEARCH_ANCHORS.get(theme, SEARCH_ANCHORS[DEFAULT_THEME]))
    qual = history.pick("title_quals", QUALIFIERS)
    pattern = history.pick("title_patterns", TITLE_PATTERNS)

    title = pattern.format(anchor=anchor, core=core, qual=qual)
    title = " ".join(title.split())

    # Try progressively shorter shapes rather than hard-truncating mid-word,
    # which is how the old pipeline produced titles ending in "| Cu".
    if len(title) > TITLE_SOFT_LIMIT:
        for fallback in ("{anchor}: {core}", "{core} | {anchor}", "{anchor} | {core}"):
            attempt = " ".join(fallback.format(anchor=anchor, core=core, qual=qual).split())
            if len(attempt) <= TITLE_SOFT_LIMIT:
                title = attempt
                break
    if len(title) > TITLE_HARD_LIMIT:
        title = title[:TITLE_HARD_LIMIT].rsplit(" ", 1)[0]
    return title


# ==========================================================================
# Hashtags
# ==========================================================================
# YouTube shows the first three above the title, so #shorts is not first: it wins
# nothing there and wastes the most valuable slot. A topical Hindi tag goes first.
HASHTAG_CORE = ["#कृष्ण", "#कृष्णकथा", "#shorts"]

HASHTAG_THEME = {
    "janm": ["#कृष्णजन्म", "#जन्माष्टमी", "#krishnajanma"],
    "gokul": ["#बाललीला", "#गोकुल", "#ladducopal", "#krishnaleela"],
    "vrindavan": ["#वृंदावन", "#राधाकृष्ण", "#radhakrishna", "#vrindavan"],
    "govardhan": ["#गोवर्धन", "#गिरिराज", "#govardhan"],
    "mathura": ["#मथुरा", "#कंसवध", "#mathura"],
    "dwarka": ["#द्वारकाधीश", "#रुक्मिणी", "#dwarkadhish"],
    "kurukshetra": ["#महाभारत", "#अर्जुन", "#mahabharat", "#kurukshetra"],
    "gita": ["#भगवदगीता", "#गीतासार", "#bhagavadgita", "#gitagyan"],
    "sudama": ["#सुदामा", "#मित्रता", "#sudama"],
    "ant": ["#श्रीकृष्ण", "#कृष्णभक्ति", "#shrikrishna"],
}

HASHTAG_DEVOTION = [
    "#राधेराधे", "#जयश्रीकृष्ण", "#हरेकृष्ण", "#कृष्णभक्ति", "#भक्ति",
    "#radheradhe", "#jaishreekrishna", "#harekrishna", "#bhakti", "#devotional",
]

HASHTAG_DISCOVERY = [
    "#कथा", "#प्रेरणा", "#जीवनकीसीख", "#सनातन", "#धर्म",
    "#motivation", "#lifelesson", "#hindistory", "#spiritual", "#sanatandharma",
]


def build_hashtags(theme=None, rng=None, count=None):
    """Per-video hashtag set. Core first, then theme, devotion, discovery."""
    rng = rng or random
    if count is None:
        count = int(get_cfg("seo.hashtag_count", 9))
    theme = theme or DEFAULT_THEME
    tags = list(HASHTAG_CORE)
    pool_theme = list(HASHTAG_THEME.get(theme, []))
    rng.shuffle(pool_theme)
    tags.extend(pool_theme[:2])

    devotion = list(HASHTAG_DEVOTION)
    discovery = list(HASHTAG_DISCOVERY)
    rng.shuffle(devotion)
    rng.shuffle(discovery)
    tags.extend(devotion[:2])
    tags.extend(discovery[:3])

    out = []
    for t in tags:
        if t not in out:
            out.append(t)
        if len(out) >= count:
            break
    return out


# ==========================================================================
# Tags
# ==========================================================================
TAG_EVERGREEN = [
    "krishna katha", "कृष्ण कथा", "krishna story hindi", "श्रीकृष्ण कथा",
    "krishna leela", "कृष्ण लीला", "hindi moral story", "प्रेरणादायक कहानी",
    "bhakti story", "krishna motivational", "जीवन की सीख",
]

TAG_THEME = {
    "janm": ["krishna janam katha", "कृष्ण जन्म", "janmashtami story", "devaki vasudev"],
    "gokul": ["bal krishna", "बाल कृष्ण", "makhan chor", "yashoda krishna", "krishna bal leela"],
    "vrindavan": ["radha krishna story", "राधा कृष्ण", "vrindavan katha", "krishna murli", "gopi krishna"],
    "govardhan": ["govardhan leela", "गोवर्धन पूजा", "indra krishna", "giriraj katha"],
    "mathura": ["kans vadh", "कंस वध", "mathura katha", "akrur krishna"],
    "dwarka": ["dwarkadhish", "द्वारका", "rukmini krishna", "jarasandh"],
    "kurukshetra": ["mahabharat katha", "महाभारत", "arjun krishna", "draupadi krishna", "karn katha"],
    "gita": ["bhagavad gita", "भगवद गीता", "gita gyan", "gita updesh", "गीता सार", "krishna gyan"],
    "sudama": ["krishna sudama", "कृष्ण सुदामा", "sachi mitrata", "sudama charitra"],
    "ant": ["krishna ant", "उद्धव गीता", "krishna prabhas", "shri krishna katha"],
}

TAGS_CHAR_BUDGET = 480   # a little under 500 so the API never 400s
TAG_MAX_LEN = 60


def _normalise_tag(tag):
    t = " ".join(str(tag or "").split()).strip().lower()
    t = t.replace('"', "").replace(",", " ")
    return " ".join(t.split())


def build_tags(core_title="", keywords=None, theme=None, lesson="", rng=None, extra=None):
    """Build a tag list that fits inside YouTube's total character budget.

    YouTube counts the COMBINED length of all tags against ~500 characters and
    rejects the request outright if it overflows, so tags are added in priority
    order and the list stops when the budget is spent -- rather than sending a
    long list and getting a 400.
    """
    rng = rng or random
    theme = theme or detect_leela(core_title, "", keywords, lesson)

    ordered = []
    ordered.extend(TAG_THEME.get(theme, []))
    ordered.extend(TAG_EVERGREEN)
    for k in (keywords or []):
        ordered.append(k)
    for e in (extra or []):
        ordered.append(e)
    core = _clean_core(core_title)
    if core:
        ordered.append(core)

    out = []
    used = 0
    seen = set()
    for raw in ordered:
        tag = _normalise_tag(raw)
        if not tag or len(tag) > TAG_MAX_LEN or tag in seen:
            continue
        if used + len(tag) > TAGS_CHAR_BUDGET:
            continue
        seen.add(tag)
        out.append(tag)
        used += len(tag)
    return out


# ==========================================================================
# Description
# ==========================================================================
# The first ~100 characters are what appears in search results, so the opener
# carries the topic in plain Hindi rather than a greeting.
DESC_OPENERS = [
    "श्रीकृष्ण की एक ऐसी कथा, जिसकी सीख आज भी हर घर में काम आती है।",
    "भगवान श्रीकृष्ण के जीवन का एक प्रसंग और उससे मिलने वाली गहरी सीख।",
    "कृष्ण कथा: एक छोटा प्रसंग, एक बड़ी सीख।",
    "ये कथा सुनने के बाद आपका नज़रिया बदल जाएगा।",
    "श्रीकृष्ण की लीला और उसमें छिपा जीवन का सबक।",
    "कृष्ण की एक सीख, जो आज के समय में और ज़्यादा ज़रूरी है।",
    "एक कथा, एक सीख — श्रीकृष्ण के जीवन से।",
    "भगवद गीता और कृष्ण लीला की सरल भाषा में कथा।",
    "श्रीकृष्ण के जीवन का वो प्रसंग जो हमें बहुत कुछ सिखाता है।",
    "कृष्ण कथा जो मन को शांति और दिशा दोनों देती है।",
    "ये प्रसंग छोटा है, पर इसकी सीख बहुत बड़ी है।",
    "श्रीकृष्ण की कथा, आज के जीवन से जोड़कर।",
    "कन्हैया की एक लीला और उसमें छिपा उत्तर।",
    "गीता का सार, एक कथा के ज़रिए।",
    "कृष्ण ने जो सिखाया, वो किताबों में नहीं मिलता।",
    "एक प्रसंग जो हर माता-पिता को सुनना चाहिए।",
    "श्रीकृष्ण की कथाओं में जीवन के सारे उत्तर हैं।",
    "आज की कथा: श्रीकृष्ण और एक ज़रूरी सीख।",
]

DESC_QUESTIONS = [
    "आपको ये सीख कैसी लगी? कमेंट में बताइए।",
    "आप उस जगह होते तो क्या करते? कमेंट में लिखिए।",
    "अगली कथा किस लीला पर चाहिए? कमेंट कीजिए।",
    "क्या आप इस सीख से सहमत हैं?",
    "इस कथा ने आपको किसकी याद दिलाई?",
    "आपकी सबसे प्रिय कृष्ण लीला कौन सी है?",
    "कमेंट में लिखिए — राधे राधे।",
    "ये सीख किसे भेजनी चाहिए? उन्हें टैग कीजिए।",
    "आपने ये कथा पहले सुनी थी?",
    "गीता की कौन सी बात आपके सबसे काम आई?",
    "क्या आज भी ये बात लागू होती है? बताइए।",
    "इस प्रसंग पर पूरी कथा चाहिए? कमेंट कीजिए।",
    "आपके घर में ये कथा कौन सुनाता था?",
    "इनमें से कौन सी सीख सबसे कठिन लगती है?",
    "बोलिए — जय श्री कृष्ण।",
    "आपको कौन सा हिस्सा सबसे अच्छा लगा?",
    "क्या ये सीख बच्चों को सिखानी चाहिए?",
    "कमेंट में अपनी राय ज़रूर लिखिए।",
]

DESC_CTAS = [
    "रोज़ ऐसी कथाओं के लिए चैनल सब्सक्राइब कीजिए।",
    "हर दिन एक नई कृष्ण कथा — सब्सक्राइब कर लीजिए।",
    "अगर अच्छा लगा तो लाइक और सब्सक्राइब कीजिए।",
    "कृष्ण कथाओं की रोज़ की खुराक — सब्सक्राइब कीजिए।",
    "चैनल से जुड़ जाइए, कल फिर एक नई कथा।",
    "ऐसी सीखों के लिए बेल आइकन दबा दीजिए।",
    "सब्सक्राइब कीजिए और कोई कथा मिस न कीजिए।",
    "परिवार के साथ शेयर कीजिए और चैनल फॉलो कीजिए।",
    "रोज़ पाँच नई कथाएँ — सब्सक्राइब कर लीजिए।",
    "जय श्री कृष्ण। चैनल सब्सक्राइब कीजिए।",
    "अगर मन को शांति मिली तो सब्सक्राइब कीजिए।",
    "गीता और कृष्ण लीला रोज़ — सब्सक्राइब कीजिए।",
]

DESC_ABOUT = [
    "इस चैनल पर भगवान श्रीकृष्ण के जन्म से लेकर उनके जीवन के अंतिम प्रसंगों तक "
    "की कथाएँ सरल हिंदी में सुनाई जाती हैं — हर कथा के साथ एक साफ़ सीख।",
    "यहाँ आपको बाल लीला, वृंदावन, मथुरा, द्वारका, महाभारत और भगवद गीता — "
    "श्रीकृष्ण के जीवन का हर पड़ाव कथा रूप में मिलेगा।",
    "श्रीकृष्ण की लीलाएँ और गीता का ज्ञान, रोज़ की भाषा में, रोज़ की ज़िंदगी के लिए।",
    "कृष्ण कथा, गीता उपदेश और जीवन की सीख — सब एक जगह, सरल हिंदी में।",
]

PRODUCTION_NOTE = (
    "नोट: इस वीडियो के दृश्य AI की सहायता से बनाए गए हैं और कुछ प्राकृतिक "
    "फुटेज Pexels से लिया गया है। कथा शास्त्रों में वर्णित प्रसंगों पर आधारित है।"
)


def _teaser(text, max_chars=140):
    """One line of the katha itself, skipping the randomly drawn hook sentence.

    The old pipeline pasted the ENTIRE narration into the description. That
    duplicated the audio as text on every single video, which reads as
    auto-generated and gives the ranking system nothing it does not already have
    from the captions.
    """
    body = _strip_hook_sentence(text)
    if not body:
        return ""
    parts = re.split(r"(?<=[।.!?])\s+", body)
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(out) + len(p) + 1 > max_chars:
            break
        out = (out + " " + p).strip()
    if not out:
        out = body[:max_chars].rsplit(" ", 1)[0]
    return out


def build_description(core_title, text="", keywords=None, theme=None, lesson="",
                      hashtags=None, rng=None):
    """Assemble the per-video description."""
    rng = rng or random
    theme = theme or detect_leela(core_title, text, keywords, lesson)
    if hashtags is None:
        hashtags = build_hashtags(theme, rng=rng)

    opener = history.pick("desc_openers", DESC_OPENERS)
    question = history.pick("desc_questions", DESC_QUESTIONS)
    cta = history.pick("desc_ctas", DESC_CTAS)
    about = rng.choice(DESC_ABOUT)
    channel_url = get_cfg("seo.channel_url", "")

    blocks = [opener]

    teaser = _teaser(text)
    if teaser:
        blocks.append(teaser)

    if lesson:
        blocks.append("सीख: %s" % str(lesson).strip().rstrip("।") + "।")

    blocks.append(question)
    blocks.append(cta)
    if channel_url:
        blocks.append("चैनल: %s" % channel_url)
    blocks.append(about)

    kws = [str(k) for k in (keywords or []) if str(k).strip()][:5]
    if kws:
        blocks.append("इस कथा में: " + ", ".join(kws))

    blocks.append(PRODUCTION_NOTE)
    blocks.append(" ".join(hashtags))

    return "\n\n".join(b for b in blocks if b)


# ==========================================================================
# Pinned comment
# ==========================================================================
# Printed into the run log for manual pinning. Comment velocity in the first hour
# is a strong signal and viewers rarely start a thread themselves, so the channel
# owner posts the first one. Posting it automatically is not possible with the
# youtube.upload scope this pipeline uses.
PINNED_COMMENTS = [
    "आपकी सबसे प्रिय कृष्ण लीला कौन सी है? नीचे लिखिए 👇",
    "बोलिए — जय श्री कृष्ण 🙏 और अगली कथा का विषय बताइए।",
    "आप उस जगह होते तो क्या करते? ईमानदारी से बताइए 👇",
    "ये सीख किसे भेजनी चाहिए? उनका नाम लिखिए 👇",
    "राधे राधे 🙏 आपको ये कथा कैसी लगी?",
    "गीता की कौन सी बात आपके सबसे ज़्यादा काम आई? 👇",
    "इस प्रसंग पर पूरी कथा चाहिए? कमेंट में 'हाँ' लिखिए।",
    "आपके घर में बचपन में ये कथा कौन सुनाता था? 👇",
    "क्या आज भी ये बात लागू होती है? आपकी राय 👇",
    "अगली कथा — गोकुल, महाभारत या गीता? आप चुनिए 👇",
    "एक शब्द में बताइए, इस कथा से क्या सीखा? 👇",
    "जय कन्हैया लाल की 🙏 कल कौन सी लीला सुनना चाहेंगे?",
    "इस सीख को अपने बच्चों को सुनाइएगा? बताइए 👇",
    "आपको कौन सा हिस्सा सबसे अच्छा लगा? 👇",
    "हरे कृष्ण 🙏 आपका पसंदीदा कृष्ण मंत्र कौन सा है?",
    "क्या ये कथा आपने पहले सुनी थी? हाँ या नहीं 👇",
    "कृष्ण की कौन सी सीख आपको सबसे कठिन लगती है? 👇",
    "इस कथा ने आपको किसकी याद दिलाई? 👇",
    "जय द्वारकाधीश 🙏 अगली कथा का विषय आप बताइए।",
    "आपके शहर से राधे राधे लिखिए 👇",
]


def build_pinned_comment(rng=None):
    return history.pick("pinned_comments", PINNED_COMMENTS)


# ==========================================================================
# One-call bundle
# ==========================================================================
def build_metadata(core_title, text="", keywords=None, lesson="", rng=None):
    """Return the complete metadata bundle for one reel."""
    rng = rng or random
    theme = detect_leela(core_title, text, keywords, lesson)
    title = build_title(core_title, text, keywords, theme=theme, lesson=lesson, rng=rng)
    hashtags = build_hashtags(theme, rng=rng)
    tags = build_tags(core_title, keywords, theme=theme, lesson=lesson, rng=rng)
    description = build_description(
        core_title, text=text, keywords=keywords, theme=theme,
        lesson=lesson, hashtags=hashtags, rng=rng,
    )
    return {
        # Kept under the key name the rest of the pipeline already reads.
        "subject": theme,
        "theme": theme,
        "youtube_title": title,
        "youtube_description": description,
        "youtube_tags": tags,
        "hashtags": hashtags,
        "pinned_comment": build_pinned_comment(rng=rng),
        "atmosphere_theme": theme,
    }
