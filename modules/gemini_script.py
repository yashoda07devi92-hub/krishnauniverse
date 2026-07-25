# -*- coding: utf-8 -*-
"""
Script generation for Krishna Universe Shorts (Hindi katha).

Produces a ~30 second Hindi narration about one leela / one lesson from
Krishna's life, using Gemini. If no API key is set, or every model candidate
fails, it falls back to the bundled quotes.json of pre-written Hindi scripts.

Two things differ from the English pipeline this was ported from:

  * The narration is Hindi (Devanagari). Word budget is therefore tuned to the
    Hindi voice, which reads slower than the English one: ~130 words/minute at
    the configured rate, so ~65 words is 30 seconds.

  * The model is also asked for `scene_prompts` -- English one-line visual
    descriptions of each beat of the story. There is no stock footage of Krishna
    anywhere, so those prompts are what modules/ai_images.py turns into the
    actual frames of the video. Asking the SAME model that wrote the story to
    describe the shots keeps picture and narration in sync; generic prompts
    produced frames that had nothing to do with the words being spoken.

Heavy third-party libraries (google-generativeai) are imported lazily inside
functions so importing this module never hard-fails.
"""

import json
import logging
import random
import re
from dataclasses import dataclass, field, replace

from .config import QUOTES_PATH, get_cfg, get_env

log = logging.getLogger("krishna.gemini")

# All content pools live in modules/pools.py so they can be grown in one place.
# Selection goes through modules/history.py, which draws WITHOUT replacement and
# remembers across runs, so nothing repeats until a pool is genuinely exhausted.
from .pools import (
    CTA_CANDIDATES,
    DEFAULT_KEYWORDS,
    FLASH_BY_THEME,
    FLASH_GENERIC,
    FLASH_PHRASES,
    HOOK_CANDIDATES,
    SCREEN_BY_THEME,
    SCREEN_GENERIC,
    SCREEN_HOOKS,
    TOPIC_POOL,
)
from . import history

_CTA = CTA_CANDIDATES[0]


def _pick_cta():
    return history.pick("ctas", CTA_CANDIDATES)


def _as_list(picked):
    return picked if isinstance(picked, list) else [picked]


def _pick_screen_hook(theme=None):
    """On-screen label for the opening 2.5s, biased toward the story's own theme.

    Half the time it draws from the theme's own labels ("गोवर्धन उठा" on a
    Govardhan story) and half the time from the safe generic set. Always drawing
    themed would exhaust the small per-theme lists in a few days; never drawing
    themed produced bland labels. Each theme keeps its own history bucket so one
    theme's draws do not consume another's.
    """
    themed = SCREEN_BY_THEME.get(theme) or []
    if themed and random.random() < 0.5:
        return history.pick("screen_hooks_%s" % theme, list(themed))
    return history.pick("screen_hooks", list(SCREEN_GENERIC))


def _pick_flashes(count=3, theme=None):
    """Short phrases flashed mid-video (see video_composer._build_flash_clips).

    One themed phrase plus generic ones. A flat random draw across every phrase
    put proper nouns from the wrong chapter of Krishna's life on screen -- a
    Govardhan reel flashing a Mathura character's name -- which reads as
    careless. See the note above FLASH_GENERIC in pools.py.
    """
    count = max(1, int(count))
    out = []
    themed = FLASH_BY_THEME.get(theme) or []
    if themed and count > 1:
        out.extend(_as_list(history.pick("flashes_%s" % theme, list(themed), count=1)))
    need = count - len(out)
    if need > 0:
        out.extend(_as_list(history.pick("flashes", list(FLASH_GENERIC), count=need)))
    return out[:count]


def _split_topic(topic):
    """TOPIC_POOL holds (premise, lesson) tuples. Accept either shape."""
    if isinstance(topic, (tuple, list)) and len(topic) >= 2:
        return str(topic[0]), str(topic[1])
    return (str(topic) if topic else ""), ""


def _has_cta(text):
    """True if the script already ends with one of our sign-offs."""
    body = (text or "")
    return any(c in body for c in CTA_CANDIDATES)


def _derive_hook(text):
    """Pick a voice-friendly Hindi hook sentence for this reel.

    Plain random on purpose, NOT history.pick(). This runs inside
    Script.__post_init__, and load_fallback_scripts() builds a Script for every
    entry in quotes.json on a single reel. Consuming history here would drain the
    hook, screen-hook and flash pools in one run and force an immediate reset --
    which is exactly the repetition the history layer exists to prevent. The
    real, history-backed pick happens once per reel in generate_script().
    """
    return random.choice(HOOK_CANDIDATES)


def swap_spoken_hook(text, hook=None):
    """Replace the FIRST sentence of the script with a fresh spoken hook.

    The narrator voices `script.text`, and both Gemini and the bundled scripts
    gravitate to the same handful of openers. Swapping the first sentence means
    every reel's voiceover starts differently, while the rest of the katha and
    the closing sign-off are untouched.

    Hindi sentences end in a danda (।) as often as a full stop, so the split has
    to accept both -- splitting on [.!?] alone left the whole paragraph intact
    and the hook simply got prepended, producing two openers in a row.
    """
    if not text:
        return text
    chosen = hook or history.pick("hooks", HOOK_CANDIDATES)
    body = text.strip()
    parts = re.split(r"(?<=[।.!?])\s+", body, maxsplit=1)
    rest = parts[1].strip() if len(parts) == 2 else ""
    if rest:
        return "%s %s" % (chosen, rest)
    return "%s %s" % (chosen, body)


def swap_cta(text, cta=None):
    """Replace a known trailing sign-off with a freshly chosen one."""
    if not text:
        return text
    body = text.strip()
    chosen = cta or _pick_cta()
    for candidate in CTA_CANDIDATES:
        idx = body.rfind(candidate)
        if idx != -1:
            return (body[:idx].rstrip() + " " + chosen).strip()
    if not _has_cta(body):
        return (body + " " + chosen).strip()
    return body


# Fallback visual beats, used when the model returns no scene_prompts. Kept
# generic so they fit any leela rather than contradicting the narration.
_GENERIC_SCENES = [
    "young Lord Krishna with peacock feather crown, serene expression, warm golden light",
    "ancient Indian village at dawn, mud houses, cows, soft mist",
    "Yamuna riverbank at sunset, calm water, silhouette of a flute player",
    "diya oil lamps glowing in a stone temple courtyard at night",
    "peacock spreading feathers under a banyan tree, dramatic light",
]


@dataclass
class Script:
    """A single Hindi narration script ready for the pipeline."""

    title: str
    text: str
    keywords: list = field(default_factory=list)
    hook: str = ""          # spoken opener (full Hindi sentence, narrated)
    screen_hook: str = ""   # on-screen label (2-4 Hindi words, drawn ~2.5s)
    flashes: list = field(default_factory=list)   # phrases flashed mid-video
    scene_prompts: list = field(default_factory=list)  # English AI-image prompts
    lesson: str = ""        # the seekh, used in the description + last chapter

    def __post_init__(self):
        if not self.hook:
            self.hook = _derive_hook(self.text)
        # Cheap random placeholders only; generate_script() overwrites these with
        # history-backed picks for the reel that is actually produced.
        if not self.screen_hook:
            self.screen_hook = random.choice(SCREEN_HOOKS)
        if not self.flashes:
            self.flashes = random.sample(FLASH_PHRASES, min(3, len(FLASH_PHRASES)))
        if not self.keywords:
            self.keywords = list(DEFAULT_KEYWORDS)
        if not self.scene_prompts:
            self.scene_prompts = list(_GENERIC_SCENES)

    @property
    def word_count(self):
        return len(self.text.split())


# --------------------------------------------------------------------------
# Gemini-backed generation
# --------------------------------------------------------------------------
_PROMPT_TEMPLATE = """आप "Krishna Universe" नाम के एक YouTube Shorts चैनल के लिए कथा लिखते हैं।
चैनल का विषय: भगवान श्रीकृष्ण के जीवन की लीलाएँ और उनसे मिलने वाली सीख।
दर्शक भारत में हैं, भाषा सरल बोलचाल की हिंदी है।

एक कथा लिखिए, लगभग {words} शब्दों की (धीमी आवाज़ में पढ़ने पर करीब 30 सेकंड)।

नियम:
- पहला वाक्य एक छोटा, ज़ोरदार हुक हो जो स्क्रॉल रोक दे। हर बार अलग तरीका
  अपनाइए — कभी सवाल, कभी दावा, कभी रहस्य। एक ही शुरुआत दोहराइए नहीं।
- टोन: शांत, आदरपूर्ण, कथावाचक जैसी। जैसे कोई दादी-नानी बैठकर कथा सुना रही हो।
- कथा में एक ठोस दृश्य होना चाहिए और अंत में एक साफ़ सीख।
- सरल हिंदी। भारी संस्कृत शब्द नहीं। छोटे वाक्य।
- किसी धर्म, जाति या व्यक्ति के बारे में कोई अपमानजनक बात नहीं। कोई राजनीति नहीं।
- कोई तथ्य गढ़िए नहीं — शास्त्रों में जो प्रसंग है, उसी को सरल भाषा में कहिए।
- अंत में बिल्कुल यही पंक्ति लिखिए: "{cta}"
- सिर्फ बोले जाने वाले वाक्य। कोई इमोजी नहीं, कोई हैशटैग नहीं, कोई मार्कडाउन नहीं,
  कोई स्टेज-डायरेक्शन नहीं।
{topic_line}{lesson_line}
सिर्फ एक JSON ऑब्जेक्ट लौटाइए (कोई code fence नहीं), इन keys के साथ:
  "title": हिंदी में छोटा आकर्षक शीर्षक (अधिकतम 8 शब्द),
  "text": पूरी कथा एक ही string में (हिंदी),
  "lesson": इस कथा की सीख एक छोटे हिंदी वाक्य में,
  "scene_prompts": 5 से 6 items का array. हर item ENGLISH में एक दृश्य का
      वर्णन हो, जिससे AI चित्र बनाया जाएगा. कथा के क्रम में लिखिए.
      हर वर्णन में जगह, समय और रोशनी बताइए. उदाहरण:
      "baby Krishna crawling on a mud floor holding a butter pot, warm lamplight,
       ancient Indian village hut, cinematic". कोई text/letters न मांगें.
  "keywords": 3 से 5 items का array, ENGLISH में, माहौल वाले stock-footage
      search phrases (जैसे "yamuna river flowing water", "peacock feathers",
      "oil lamp flame"). इनमें कोई इंसान न हो, सिर्फ प्रकृति/वस्तु/जगह.
"""


def _build_prompt(topic=None, lesson=None):
    target_words = get_cfg("gemini.target_words", 68)
    topic_line = ""
    lesson_line = ""
    if topic:
        topic_line = "- कथा इस प्रसंग पर हो: %s\n" % topic
    if lesson:
        lesson_line = "- कथा की सीख यही होनी चाहिए: %s\n" % lesson
    return _PROMPT_TEMPLATE.format(
        words=target_words, cta=_pick_cta(),
        topic_line=topic_line, lesson_line=lesson_line,
    )


def _parse_model_json(raw):
    """Extract a JSON object from a model response that may include fences."""
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except Exception:
        return None


def _clean_list(values, limit=8):
    out = []
    for v in (values or []):
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _generate_with_gemini(topic=None, lesson=None):
    """Try Gemini across the ordered model candidates. Returns Script or None."""
    api_key = get_env("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set - using local quotes.json fallback.")
        return None

    try:
        import google.generativeai as genai
    except Exception as exc:
        log.warning("google-generativeai not available (%s); using fallback.", exc)
        return None

    try:
        genai.configure(api_key=api_key)
    except Exception as exc:
        log.warning("Could not configure Gemini (%s); using fallback.", exc)
        return None

    default_model = get_env("GEMINI_MODEL", get_cfg("gemini.model", "gemini-2.0-flash"))
    candidates = get_cfg(
        "gemini.model_candidates",
        ["gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-flash"],
    )
    ordered = [default_model] + [m for m in candidates if m != default_model]

    prompt = _build_prompt(topic, lesson)
    temperature = get_cfg("gemini.temperature", 0.9)
    min_words = int(get_cfg("gemini.min_words", 45))

    for model_name in ordered:
        try:
            log.info("Requesting Hindi katha from Gemini model '%s'...", model_name)
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(
                prompt, generation_config={"temperature": temperature}
            )
            raw = getattr(resp, "text", None)
            data = _parse_model_json(raw)
            if not data or not data.get("text"):
                log.warning("Model '%s' returned no usable text; trying next.", model_name)
                continue

            text = str(data["text"]).strip()
            if len(text.split()) < min_words:
                log.warning(
                    "Model '%s' returned only %d words (need >=%d); trying next.",
                    model_name, len(text.split()), min_words,
                )
                continue

            script = Script(
                title=str(data.get("title") or "कृष्ण कथा").strip(),
                text=text,
                keywords=_clean_list(data.get("keywords"), 5),
                scene_prompts=_clean_list(data.get("scene_prompts"), 8),
                lesson=str(data.get("lesson") or lesson or "").strip(),
            )
            if not _has_cta(script.text):
                script.text = script.text.rstrip() + " " + _pick_cta()
            log.info(
                "Gemini katha ready via '%s' (%d words, %d scene prompts).",
                model_name, script.word_count, len(script.scene_prompts),
            )
            return script
        except Exception as exc:
            log.warning("Gemini model '%s' failed (%s); trying next.", model_name, exc)
            continue

    log.warning("All Gemini model candidates failed - using local quotes.json.")
    return None


# --------------------------------------------------------------------------
# Local fallback
# --------------------------------------------------------------------------
def load_fallback_scripts():
    """Load all pre-written Hindi scripts from quotes.json as Script objects."""
    try:
        with open(QUOTES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("scripts", []) if isinstance(data, dict) else data
        scripts = []
        for item in items:
            try:
                scripts.append(
                    Script(
                        title=str(item.get("title", "कृष्ण कथा")),
                        text=str(item["text"]),
                        keywords=list(item.get("keywords", [])),
                        scene_prompts=list(item.get("scene_prompts", [])),
                        lesson=str(item.get("lesson", "")),
                    )
                )
            except Exception:
                continue
        return scripts
    except Exception as exc:
        log.error("Could not load quotes.json (%s).", exc)
        return []


def _fallback_script(topic=None, lesson=None):
    scripts = load_fallback_scripts()
    if not scripts:
        return Script(
            title="कृष्ण की सीख",
            text=(
                "एक बात सुनो, जो कृष्ण ने बहुत पहले कह दी थी। "
                "उन्होंने कहा था, अंधेरे को गाली देने से कुछ नहीं होता, "
                "एक दीया जला देना ही धर्म है। शिकायत करना आसान है, "
                "पर एक छोटा अच्छा काम पूरे माहौल को बदल देता है। " + _CTA
            ),
            keywords=list(DEFAULT_KEYWORDS),
            lesson=lesson or "शिकायत करने से अच्छा है एक दीया जला देना",
        )
    return random.choice(scripts)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def generate_script(topic=None):
    """Return a single Script, preferring Gemini and falling back to quotes."""
    lesson = None
    if not topic:
        topic = history.pick("topics", TOPIC_POOL)
        log.info(
            "Auto-picked leela: %s  (%d of %d unused)",
            topic, len(history.remaining("topics", TOPIC_POOL)), len(TOPIC_POOL),
        )
    topic, lesson = _split_topic(topic)

    script = _generate_with_gemini(topic, lesson)
    if script is None:
        script = _fallback_script(topic, lesson)
        log.info("Using fallback script: '%s'.", script.title)

    fresh_hook = history.pick("hooks", HOOK_CANDIDATES)
    script.text = swap_spoken_hook(script.text, fresh_hook)
    script.text = swap_cta(script.text)
    script.hook = fresh_hook
    if not script.lesson and lesson:
        script.lesson = lesson

    # On-screen text is chosen AFTER the story exists, so it can be matched to
    # which part of Krishna's life this actually is. Imported here rather than at
    # module level: seo imports history and pools, and importing it at the top
    # would make the script/SEO layers circular.
    from . import seo

    theme = seo.detect_leela(script.title, script.text, script.keywords, script.lesson)
    script.screen_hook = _pick_screen_hook(theme)
    script.flashes = _pick_flashes(theme=theme)
    return script


def generate_scripts(count, topic=None):
    """Return `count` Scripts. Uses Gemini per item when available, else fills
    from unique fallback scripts to avoid repeats within a batch."""
    count = max(1, int(count))
    results = []

    if get_env("GEMINI_API_KEY"):
        for _ in range(count):
            results.append(generate_script(topic))
        return results

    pool = load_fallback_scripts()
    random.shuffle(pool)
    if not pool:
        return [generate_script(topic) for _ in range(count)]
    for i in range(count):
        # COPY, don't reuse. quotes.json holds a couple of dozen scripts, so once
        # `count` exceeds that, pool[i % len(pool)] hands back an object already
        # in `results`; mutating it would overwrite the earlier reel's hook too.
        script = replace(pool[i % len(pool)])
        fresh_hook = history.pick("hooks", HOOK_CANDIDATES)
        script.text = swap_spoken_hook(script.text, fresh_hook)
        script.text = swap_cta(script.text)
        script.hook = fresh_hook
        from . import seo

        theme = seo.detect_leela(script.title, script.text, script.keywords, script.lesson)
        script.screen_hook = _pick_screen_hook(theme)
        script.flashes = _pick_flashes(theme=theme)
        results.append(script)
    return results
