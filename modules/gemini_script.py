# -*- coding: utf-8 -*-
"""
Hindi script generation for Krishna Universe Shorts.

Produces a ~30 second Hindi narration about one leela from Krishna's life, the
seekh (lesson) it teaches, and - new in this channel - a list of ENGLISH scene
prompts used to generate the visuals.

WHY SCENE PROMPTS
-----------------
The parent pipeline searched Pexels for footage matching the story. That works
when the subject is a puppy. There is no stock footage of Krishna anywhere, so
the visuals have to be generated per scene instead (modules/ai_images.py), and
the model that generates them needs an explicit visual description of each beat.
Asking Gemini for those descriptions in the same call keeps the pictures locked
to the story rather than being generic devotional wallpaper.

The prompts are requested in ENGLISH on purpose: the image model understands
English prompts far better than Devanagari, while the narration itself stays in
Hindi.

Falls back to quotes.json (Hindi) if Gemini is unavailable. Heavy imports are
lazy so importing this module never hard-fails.
"""

import json
import logging
import random
import re
from dataclasses import dataclass, field, replace

from .config import QUOTES_PATH, get_cfg, get_env
from .pools import (
    ATMOSPHERE_KEYWORDS,
    CTA_CANDIDATES,
    DEFAULT_KEYWORDS,
    FLASH_PHRASES,
    HOOK_CANDIDATES,
    SCREEN_HOOKS,
    TOPIC_POOL,
)
from . import history

log = logging.getLogger("krishna.gemini")

_CTA = CTA_CANDIDATES[0]

# Visual house style. Prepended to every scene prompt so all 150 leelas share a
# consistent look instead of every upload arriving in a different art style,
# which is what makes an AI channel feel like a random image dump.
SCENE_STYLE = (
    "cinematic indian mythological painting, dramatic warm lighting, rich saffron "
    "and deep blue palette, highly detailed, volumetric god rays, film grain, "
    "no text, no watermark, no letters"
)

# Used when the model returns nothing usable for the visuals.
FALLBACK_SCENES = [
    "young lord krishna with peacock feather crown standing under a banyan tree at golden hour",
    "ancient indian village at dawn, mud houses, cows, soft mist",
    "yamuna river flowing at sunset, lotus flowers, warm reflections",
    "flute resting on a stone beside a river, peacock feather, soft light",
    "night sky full of stars over an ancient indian temple",
    "hands of a mother holding a small child, warm lamp light, indian village home",
]


def _pick_cta():
    return history.pick("ctas", CTA_CANDIDATES)


def _pick_screen_hook():
    return history.pick("screen_hooks", SCREEN_HOOKS)


def _pick_flashes(count=3):
    picked = history.pick("flashes", FLASH_PHRASES, count=count)
    return picked if isinstance(picked, list) else [picked]


def _has_cta(text):
    low = (text or "")
    return any(c in low for c in CTA_CANDIDATES)


def _derive_hook(text):
    """Plain random on purpose, NOT history.pick().

    This runs inside Script.__post_init__, and load_fallback_scripts() builds a
    Script for every entry in quotes.json on a single reel. Consuming history
    here would drain the hook, screen-hook and flash pools in one run and force
    an immediate reset - the exact repetition this channel is built to avoid.
    The real history-backed pick happens once per reel in generate_script().
    """
    return random.choice(HOOK_CANDIDATES)


def swap_spoken_hook(text, hook=None):
    """Replace the FIRST sentence of the narration with a fresh Hindi opener.

    Devanagari uses the danda (।) as its full stop, so the sentence split has to
    accept it alongside western punctuation - splitting on '.' alone would leave
    the whole paragraph as one sentence and the hook would simply be prepended.
    """
    if not text:
        return text
    chosen = hook or history.pick("hooks", HOOK_CANDIDATES)
    body = str(text).strip()
    parts = re.split(r"(?<=[।.!?])\s+", body, maxsplit=1)
    rest = parts[1].strip() if len(parts) == 2 else ""
    if rest:
        return f"{chosen} {rest}"
    return f"{chosen} {body}"


def swap_cta(text, cta=None):
    """Replace a known trailing sign-off with a freshly chosen one."""
    if not text:
        return text
    body = str(text).strip()
    chosen = cta or _pick_cta()
    for candidate in CTA_CANDIDATES:
        idx = body.rfind(candidate)
        if idx != -1:
            return (body[:idx].rstrip() + " " + chosen).strip()
    if not _has_cta(body):
        return (body + " " + chosen).strip()
    return body


@dataclass
class Script:
    """A single Hindi narration ready for the pipeline."""

    title: str
    text: str
    keywords: list = field(default_factory=list)
    hook: str = ""            # spoken opener (narrated)
    screen_hook: str = ""     # on-screen label, 2-4 words
    flashes: list = field(default_factory=list)
    seekh: str = ""           # the lesson, reused in the description
    scene_prompts: list = field(default_factory=list)  # ENGLISH image prompts

    def __post_init__(self):
        if not self.hook:
            self.hook = _derive_hook(self.text)
        # Cheap random placeholders only - see the note in _derive_hook.
        if not self.screen_hook:
            self.screen_hook = random.choice(SCREEN_HOOKS)
        if not self.flashes:
            self.flashes = random.sample(FLASH_PHRASES, min(3, len(FLASH_PHRASES)))
        if not self.keywords:
            self.keywords = list(DEFAULT_KEYWORDS)
        if not self.scene_prompts:
            self.scene_prompts = list(FALLBACK_SCENES)

    @property
    def word_count(self):
        return len(self.text.split())


# --------------------------------------------------------------------------
# Gemini-backed generation
# --------------------------------------------------------------------------
_PROMPT_TEMPLATE = """आप "Krishna Universe" नाम के एक हिंदी YouTube Shorts चैनल के लिए
स्क्रिप्ट लिखते हैं। चैनल का विषय: भगवान श्रीकृष्ण के जीवन की लीलाएँ और उनसे
मिलने वाली सीख। दर्शक भारत में हैं, आम हिंदी बोलने वाले लोग।

इस लीला पर एक narration लिखें:
  लीला: {premise}
  सीख:  {lesson}

नियम:
- लंबाई लगभग {words} शब्द। कम से कम {min_words} शब्द ज़रूरी हैं और {max_words} से
  ज़्यादा बिल्कुल नहीं। बोलने पर ये लगभग 26 से 36 सेकंड बनता है।
- {min_words} शब्द से छोटी कथा अस्वीकार कर दी जाएगी — इसलिए कथा को पूरा कहें,
  एक-दो दृश्य ज़रूर डालें, जल्दबाज़ी में मत निपटाएँ।
- सरल, बोलचाल की हिंदी। कठिन संस्कृत शब्द नहीं। जैसे कोई दादी शांति से कथा
  सुना रही हो — भावुक, गर्म, अपनापन लिए।
- पहला वाक्य एक छोटा curiosity hook हो (4 से 9 शब्द), जो स्क्रॉल रोक दे।
  हर बार अलग तरीके से लिखें।
- कथा को सीधे उस दृश्य से शुरू करें, भूमिका मत बाँधें। 30 सेकंड में समय नहीं है।
- अंत में ऊपर दी गई सीख को एक साफ़, छोटी लाइन में कहें — वही इस video का सार है।
- सबसे आख़िर में बिल्कुल यही वाक्य लिखें: "{cta}"
- केवल बोले जाने वाले वाक्य। कोई emoji नहीं, कोई hashtag नहीं, कोई markdown नहीं,
  कोई stage direction नहीं। देवनागरी में लिखें।
- कोई ऐसा दावा न करें जो शास्त्रों में नहीं है। लीला को वैसे ही रखें जैसे वो
  प्रचलित है।

सिर्फ़ एक JSON object लौटाएँ (कोई code fence नहीं), इन keys के साथ:
  "title": हिंदी में छोटा आकर्षक शीर्षक (अधिकतम 9 शब्द),
  "text": पूरा narration एक string में (हिंदी),
  "seekh": सीख एक छोटी हिंदी लाइन में,
  "scene_prompts": {scenes} ENGLISH image-generation prompts का array, कथा के
      क्रम में। हर prompt एक पूरा दृश्य बताए — कौन है, कहाँ है, क्या हो रहा है,
      रोशनी कैसी है। उदाहरण: "young krishna lifting a mountain over a village
      while heavy rain falls, villagers sheltering beneath, dramatic storm light".
      ये prompts अंग्रेज़ी में ही लिखें, हिंदी में नहीं।
  "keywords": 3-5 ENGLISH stock-footage search phrases for ATMOSHPERE shots that
      really exist on video sites — river water, peacock, cows, diya flame,
      monsoon rain, forest light, temple. Krishna himself must NOT appear in
      these, they are only background texture.
"""


# Hindi TTS at the configured -10% rate runs ~140 words/minute. Used to convert
# the word budget into the runtime the channel actually has to honour.
WORDS_PER_MINUTE = 140.0


def _word_budget():
    """(target, minimum, maximum) words for one reel."""
    return (
        int(get_cfg("gemini.target_words", 72)),
        int(get_cfg("gemini.min_words", 62)),
        int(get_cfg("gemini.max_words", 84)),
    )


def estimated_seconds(word_count):
    return (word_count / WORDS_PER_MINUTE) * 60.0


def _build_prompt(premise, lesson):
    target_words, min_words, max_words = _word_budget()
    scenes = int(get_cfg("ai_images.max_images", 7))
    return _PROMPT_TEMPLATE.format(
        premise=premise, lesson=lesson, words=target_words,
        min_words=min_words, max_words=max_words,
        cta=_pick_cta(), scenes=scenes,
    )


def _parse_model_json(raw):
    """Extract a JSON object from a model response that may include fences."""
    if not raw:
        return None
    cleaned = str(raw).strip()
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


def _clean_scene_prompts(raw_list):
    """Keep only usable English scene prompts.

    A prompt written in Devanagari is dropped: the image model produces garbled
    output from Hindi prompts, and a garbled scene is worse than a fallback one.
    """
    out = []
    for item in raw_list or []:
        s = " ".join(str(item).split())
        if len(s) < 12:
            continue
        # Reject anything that is mostly Devanagari.
        deva = sum(1 for ch in s if "\u0900" <= ch <= "\u097F")
        if deva > len(s) * 0.2:
            log.warning("Dropping Devanagari scene prompt: %r", s[:40])
            continue
        out.append(s)
    return out


def _generate_with_gemini(premise, lesson):
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

    temperature = get_cfg("gemini.temperature", 0.92)
    # If every model comes back too short, the least-bad one is still better than
    # dropping to the small bundled pool - the composer's clamp will pad it.
    shortest_ok = None

    for model_name in ordered:
        try:
            log.info("Requesting Hindi script from Gemini model '%s'...", model_name)
            model = genai.GenerativeModel(model_name)
            # Rebuilt per attempt so the CTA rotates and the length rules are
            # restated to each model.
            resp = model.generate_content(
                _build_prompt(premise, lesson),
                generation_config={"temperature": temperature},
            )
            data = _parse_model_json(getattr(resp, "text", None))
            if not data or not data.get("text"):
                log.warning("Model '%s' returned no usable text; trying next.", model_name)
                continue

            scenes = _clean_scene_prompts(data.get("scene_prompts"))
            if not scenes:
                log.warning("Model '%s' gave no usable scene prompts; using fallbacks.", model_name)
                scenes = list(FALLBACK_SCENES)

            script = Script(
                title=str(data.get("title") or "श्रीकृष्ण की एक सीख").strip(),
                text=str(data["text"]).strip(),
                seekh=str(data.get("seekh") or lesson).strip(),
                keywords=[str(k).strip() for k in data.get("keywords", []) if str(k).strip()]
                or random.sample(ATMOSPHERE_KEYWORDS, 5),
                scene_prompts=scenes,
            )
            if not _has_cta(script.text):
                script.text = script.text.rstrip() + " " + _pick_cta()

            # LENGTH FLOOR. A Short must not come out under 25s. The composer
            # clamps the timeline to video.min_duration_seconds, so a short script
            # is not published short - but the padding is trailing SILENCE, which
            # reads as a mistake and hurts the loop. So a script that would run
            # under the floor is rejected and the next model is asked instead.
            target_words, min_words, max_words = _word_budget()
            words = script.word_count
            if words < min_words:
                log.warning(
                    "Model '%s' returned %d words (~%.1fs), under the %d-word floor "
                    "(~%.1fs); trying next model.",
                    model_name, words, estimated_seconds(words),
                    min_words, estimated_seconds(min_words),
                )
                # Keep the LONGEST of the rejects, not the first one - if every
                # model undershoots, the closest to the floor needs the least
                # padding.
                if shortest_ok is None or script.word_count > shortest_ok.word_count:
                    shortest_ok = script
                continue
            if words > max_words:
                log.warning(
                    "Model '%s' returned %d words (~%.1fs), over the %d-word cap; "
                    "trying next model.",
                    model_name, words, estimated_seconds(words), max_words,
                )
                continue
            log.info(
                "Gemini script ready via '%s' (%d words, %d scene prompt(s)).",
                model_name, script.word_count, len(script.scene_prompts),
            )
            return script
        except Exception as exc:
            log.warning("Gemini model '%s' failed (%s); trying next.", model_name, exc)
            continue

    if shortest_ok is not None:
        log.warning(
            "Every model came in under the word floor; using the longest of them "
            "(%d words, ~%.1fs). The composer will pad to the %ss floor.",
            shortest_ok.word_count, estimated_seconds(shortest_ok.word_count),
            get_cfg("video.min_duration_seconds", 25),
        )
        return shortest_ok
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
                        title=str(item.get("title", "श्रीकृष्ण की एक सीख")),
                        text=str(item["text"]),
                        seekh=str(item.get("seekh", "")),
                        keywords=list(item.get("keywords", [])),
                        scene_prompts=list(item.get("scene_prompts", [])),
                    )
                )
            except Exception:
                continue
        return scripts
    except Exception as exc:
        log.error("Could not load quotes.json (%s).", exc)
        return []


def _fallback_script(premise=None, lesson=None):
    scripts = load_fallback_scripts()
    if not scripts:
        return Script(
            title="कान्हा की सबसे बड़ी सीख",
            text=(
                "कान्हा ने बस एक लाइन में सब समझा दिया। जब अर्जुन ने रणभूमि में "
                "अपना धनुष रख दिया, तब कान्हा ने कहा — जो तुम्हारे हाथ में है वो "
                "करो, बाकी मुझ पर छोड़ दो। सीख यही है कि फल की चिंता छोड़कर किया "
                "गया काम कभी बोझ नहीं बनता। " + _CTA
            ),
            seekh=lesson or "फल की चिंता छोड़कर किया गया काम कभी बोझ नहीं बनता",
            keywords=list(DEFAULT_KEYWORDS),
            scene_prompts=list(FALLBACK_SCENES),
        )
    return random.choice(scripts)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _split_topic(topic):
    """Accept a (leela, seekh) tuple, or a plain string for --topic."""
    if isinstance(topic, (tuple, list)) and len(topic) >= 2:
        return str(topic[0]), str(topic[1])
    return str(topic), ""


def generate_script(topic=None):
    """Return a single Hindi Script, preferring Gemini and falling back."""
    if not topic:
        topic = history.pick("topics", TOPIC_POOL)
        log.info(
            "Auto-picked leela: %s  (%d of %d unused)",
            topic[0] if isinstance(topic, (tuple, list)) else topic,
            len(history.remaining("topics", TOPIC_POOL)), len(TOPIC_POOL),
        )
    premise, lesson = _split_topic(topic)

    script = _generate_with_gemini(premise, lesson)
    if script is None:
        script = _fallback_script(premise, lesson)
        log.info("Using fallback script: '%s'.", script.title)

    fresh_hook = history.pick("hooks", HOOK_CANDIDATES)
    script.text = swap_spoken_hook(script.text, fresh_hook)
    script.text = swap_cta(script.text)
    script.hook = fresh_hook
    script.screen_hook = _pick_screen_hook()
    script.flashes = _pick_flashes()
    if lesson and not script.seekh:
        script.seekh = lesson
    return script


def generate_scripts(count, topic=None):
    """Return `count` Scripts, avoiding repeats within the batch."""
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
        # COPY, don't reuse. Once `count` exceeds the number of bundled scripts,
        # pool[i % len(pool)] hands back an object already in `results`, and
        # mutating it would overwrite the earlier reel's hook too.
        script = replace(pool[i % len(pool)])
        fresh_hook = history.pick("hooks", HOOK_CANDIDATES)
        script.text = swap_spoken_hook(script.text, fresh_hook)
        script.text = swap_cta(script.text)
        script.hook = fresh_hook
        script.screen_hook = _pick_screen_hook()
        script.flashes = _pick_flashes()
        results.append(script)
    return results
