# -*- coding: utf-8 -*-
"""
Hindi script generation for Krishna Universe Shorts.

Produces a ~30 second Hindi narration built around ONE usable seekh, the everyday
situation it applies to, and a list of ENGLISH scene prompts used to generate the
visuals.

SEEKH-FIRST, NOT KATHA-FIRST
----------------------------
This module used to ask for "a leela plus the lesson it teaches". It now asks for
the inverse: a cause-and-effect rule Krishna is explaining, with a small prasang
as the evidence and a closing line telling the viewer where it applies in their
own week. See the long note above _PROMPT_TEMPLATE for why - in short, a
retelling of a story the audience already knows gives them no reason to stay and
nothing to carry away, and the channel's view counts said so.

Premises come from pools.LESSON_POOL (seekh-first) mixed with pools.TOPIC_POOL
(leela-as-evidence) at content.lesson_share. Both are told in the same
lesson-first shape.

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
    KRISHNA_ATTRIBUTIONS,
    LESSON_HOOKS,
    LESSON_POOL,
    LESSON_SCREEN_HOOKS,
    SCREEN_HOOKS,
    THUMB_HOOKS_LEELA,
    THUMB_HOOKS_LESSON,
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


# Permanent ledger key for the one line a viewer actually takes away. See
# history.seen()/remember(): pool rotation protects the INPUT, this protects the
# OUTPUT, so the same seekh can never be published twice even after a reset.
SEEKH_LEDGER = "seekh_lines"

# Same permanent-ledger treatment for the banner line. The thumbnail hook is the
# single most visible string this pipeline produces - it is what a viewer sees on
# the channel grid before anything else - so a repeat there is the most damaging
# repeat available. "कुछ भी रिपीट नहीं होना चाहिए, चाहे कुछ भी हो जाए."
THUMB_HOOK_LEDGER = "thumb_hooks_used"


def _pick_attribution():
    """The phrase that puts the seekh in Krishna's mouth, rotated per reel."""
    return history.pick("attributions", KRISHNA_ATTRIBUTIONS) or KRISHNA_ATTRIBUTIONS[0]


def _fallback_thumb_hook(lesson_mode=False):
    """A banner hook for when the model gives nothing usable.

    Drawn through history AND checked against the permanent ledger, so a fallback
    can never put the same line on two banners.
    """
    pool = THUMB_HOOKS_LESSON if lesson_mode else THUMB_HOOKS_LEELA
    for _ in range(6):
        hook = history.pick("thumb_hooks", list(pool))
        if hook and not history.seen(THUMB_HOOK_LEDGER, hook):
            return hook
    return None


def _clean_thumb_hook(raw, lesson_mode=False):
    """Validate the model's banner hook, then fall back if it is unusable.

    Rejected: anything empty, longer than 5 words, or carrying punctuation that
    looks wrong set in 104px type on a phone-sized tile. Also rejected: a hook
    already printed on an earlier banner.
    """
    hook = " ".join(str(raw or "").split())
    hook = re.sub(r"[\"'“”‘’#*_`\[\](){}<>|]", "", hook).strip(" .।,-—–")
    if hook and 1 <= len(hook.split()) <= 5 and not history.seen(THUMB_HOOK_LEDGER, hook):
        return hook
    if hook:
        log.info("Banner hook %r unusable or already used; drawing a fallback.", hook[:40])
    return _fallback_thumb_hook(lesson_mode)


def _pick_cta():
    return history.pick("ctas", CTA_CANDIDATES)


def _pick_screen_hook(lesson_mode=False):
    """The 2-4 word on-screen label, which is also the thumbnail headline.

    Lesson reels draw from a pool that names no episode - putting "गोवर्धन उठा"
    on a reel about controlling anger is a promise the video does not keep, and
    that mismatch is read as clickbait.
    """
    if lesson_mode:
        return history.pick("lesson_screen_hooks", LESSON_SCREEN_HOOKS)
    return history.pick("screen_hooks", SCREEN_HOOKS)


def _pick_spoken_hook(lesson_mode=False):
    """The narrated opening sentence. Same episode-vs-lesson split as above."""
    if lesson_mode:
        return history.pick("lesson_hooks", LESSON_HOOKS)
    return history.pick("hooks", HOOK_CANDIDATES)


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
    # Where the seekh applies in a viewer's own week. This is the line that
    # decides whether the reel changed someone's day or was just pleasant to
    # listen to, so it is a first-class field and not left inside `text`: the
    # description reuses it verbatim, which also stops every description from
    # repeating the same generic "सीख" sentence.
    apply_line: str = ""
    lesson_mode: bool = False  # True when the premise came from LESSON_POOL
    # The curiosity line printed on the channel-grid banner. Separate from
    # screen_hook (which is burned into the opening 2.2s of the VIDEO) because
    # the two jobs are different: screen_hook keeps a viewer who is already
    # watching, thumb_hook has to earn the tap in the first place.
    thumb_hook: str = ""

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
# THE SHIFT THIS PROMPT ENCODES: KATHA -> SEEKH
# ---------------------------------------------
# The previous template asked for a katha - "narrate this leela, then state its
# lesson". Two things were wrong with that, and the channel's view counts (1 to 9
# per upload) said so out loud:
#
#   1. NOTHING TO STAY FOR. The audience already knows that Krishna lifted
#      Govardhan. A retelling has no open question, so there is no reason not to
#      swipe at second three, and Shorts is driven almost entirely by whether
#      people swipe at second three.
#
#   2. NOTHING TO TAKE AWAY. The lesson arrived as a moral tacked onto the end,
#      phrased as a virtue ("respect those who feed you"). Nobody's Tuesday
#      changes because of that. It is agreeable, and agreeable content does not
#      get shared.
#
# So the shape is inverted. The leela (or the small prasang) is now the EVIDENCE,
# cut down to two sentences, and the reel's real payload is a cause-and-effect
# rule plus the exact place in the viewer's own week where it applies. That is
# what the owner asked for: "30 सेकंड में कान्हा जी समझा रहे हों कि ऐसे-ऐसे
# करने से ऐसे-ऐसे होता है."
#
# The word budget is unchanged, so the runtime and the voice track are untouched.
_PROMPT_TEMPLATE = """आप "Krishna Universe" नाम के हिंदी YouTube Shorts चैनल के लिए
लिखते हैं। दर्शक भारत में हैं — आम हिंदी बोलने वाले लोग, जो अपनी रोज़ की ज़िंदगी
में परेशान हैं और तीस सेकंड में कुछ काम की बात चाहते हैं।

ये चैनल "कथा सुनाने" वाला चैनल नहीं है। ये चैनल हर video में एक ऐसी सीख देता है
जिसे दर्शक आज ही अपने जीवन में लगा सके। कथा सिर्फ़ उदाहरण है, असली चीज़ सीख है।

इस पर एक 30 सेकंड का narration लिखें:
  प्रसंग: {premise}
  सीख:   {lesson}
  आज के जीवन में: {apply}

STRUCTURE — इसी क्रम में लिखें:
  1. पहला वाक्य: 4 से 9 शब्द का hook, जो दर्शक की अपनी परेशानी को छू ले।
  2. दो-तीन वाक्य: ऊपर दिया प्रसंग। बहुत छोटा रखें — कौन, कहाँ, क्या हुआ। बस।
  3. दो-तीन वाक्य: यहाँ सीख श्रीकृष्ण के अपने मुँह से कहलवाएँ। इसी वाक्य से
     शुरू करें: "{attribution}" ... और आगे कान्हा की बात लिखें।
     बात CAUSE-AND-EFFECT में हो: "ऐसा करोगे तो ऐसा होगा", "ऐसा करते रहे तो ये
     होता है"। सिर्फ़ उपदेश नहीं, वजह बताएँ। एक छोटा ठोस उदाहरण दें।
  4. एक वाक्य: सीख साफ़, छोटी लाइन में — और ये भी कान्हा की कही बात के रूप में।
  5. एक वाक्य: दर्शक आज, अपने जीवन में, ये कैसे करे — "आज के जीवन में" वाली बात
     को अपने शब्दों में, सीधे दर्शक से कहते हुए ("आप", "आज", "कीजिए")।
  6. सबसे आख़िर में बिल्कुल यही वाक्य: "{cta}"

नियम:
- लंबाई लगभग {words} शब्द। कम से कम {min_words} और {max_words} से ज़्यादा
  बिल्कुल नहीं। बोलने पर ये लगभग 26 से 36 सेकंड बनता है।
- {min_words} शब्द से छोटा narration अस्वीकार कर दिया जाएगा।
- ये सबसे ज़रूरी नियम है: पूरे narration में कम से कम दो बार साफ़ पता चले कि ये
  बात श्रीकृष्ण की कही हुई है। "श्रीकृष्ण कहते हैं", "कान्हा ने कहा",
  "श्रीकृष्ण ने समझाया" जैसे शब्द इस्तेमाल करें। सीख कभी अपनी तरफ़ से मत दें —
  हमेशा कान्हा के कहे के रूप में दें। ये चैनल श्रीकृष्ण की सीख का चैनल है,
  सामान्य सलाह का नहीं।
- सरल, बोलचाल की हिंदी। कठिन संस्कृत शब्द नहीं। शांत, अपनापन लिए, श्रद्धा के
  साथ।
- वाक्य छोटे रखें, 8 से 14 शब्द। लंबे वाक्य बोलने में उलझ जाते हैं और सुनने
  वाले को समझ नहीं आते।
- DASH का इस्तेमाल बिल्कुल मत करें। कोई "—", कोई "–", कोई "-" नहीं। ठहराव के
  लिए सिर्फ़ कॉमा (,) और पूर्ण विराम (।) लगाएँ। ये ज़रूरी है क्योंकि आवाज़
  बनाने वाला इंजन dash पर वाक्य तोड़ देता है और सुनने में आवाज़ अटकी हुई लगती है।
- "आज की कथा", "सुनिए एक कथा", "प्रस्तुत है" जैसी भूमिका बिल्कुल मत बाँधें।
  सीधे बात से शुरू करें।
- सीख को "अच्छा बनो", "धर्म का पालन करो" जैसे बड़े-बड़े शब्दों में मत कहें।
  ठोस बात कहें, जो कोई आज कर सके।
- केवल बोले जाने वाले वाक्य। कोई emoji, hashtag, markdown या stage direction
  नहीं। देवनागरी में लिखें।
- कोई ऐसा दावा न करें जो शास्त्रों में नहीं है। प्रसंग को वैसे ही रखें जैसे वो
  प्रचलित है।

सिर्फ़ एक JSON object लौटाएँ (कोई code fence नहीं), इन keys के साथ:
  "title": हिंदी में छोटा शीर्षक (अधिकतम 9 शब्द) जो सीख बताए, न कि कथा का नाम।
      अच्छा: "गुस्सा पहले किसे जलाता है"। बुरा: "कालिया नाग की कथा"।
  "text": पूरा narration एक string में (हिंदी),
  "seekh": सीख एक छोटी हिंदी लाइन में, cause-and-effect के रूप में,
  "apply": एक छोटी हिंदी लाइन, दर्शक आज ये कैसे लगाए,
  "thumb_hook": thumbnail पर छपने वाली 2 से 4 शब्द की हिंदी लाइन, जो देखते ही
      जिज्ञासा जगा दे और क्लिक करवा दे। इसी video की बात हो, झूठा वादा नहीं —
      जो thumbnail पर लिखा है वो video में आना ही चाहिए, वरना दर्शक दो सेकंड
      में निकल जाता है और video का नुक़सान होता है।
      अच्छे उदाहरण: "कान्हा और काला नाग", "पर्वत उठा लिया", "गुस्सा किसे जलाता है",
      "यही सबसे बड़ी भूल"। बुरे उदाहरण: "कृष्ण कथा", "आज की सीख" (इनमें
      जिज्ञासा नहीं है)।
  "scene_prompts": {scenes} ENGLISH image-generation prompts का array, narration
      के क्रम में। हर prompt एक पूरा दृश्य बताए — कौन है, कहाँ है, क्या हो रहा
      है, रोशनी कैसी है। उदाहरण: "young krishna speaking calmly to a troubled
      young cowherd under a banyan tree, warm late afternoon light".
      ये prompts अंग्रेज़ी में ही लिखें, हिंदी में नहीं।
  "keywords": 3-5 ENGLISH stock-footage search phrases for ATMOSPHERE shots that
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


def _build_prompt(premise, lesson, apply_line=""):
    target_words, min_words, max_words = _word_budget()
    scenes = int(get_cfg("ai_images.max_images", 7))
    # A leela drawn from TOPIC_POOL has no "jeevan" field of its own, so the model
    # is told to derive one rather than being handed an empty line - an empty
    # placeholder made it skip step 5 of the structure entirely, which is the one
    # step the whole rewrite exists for.
    apply_line = str(apply_line or "").strip() or (
        "इस सीख को आज दर्शक के अपने जीवन की एक आम स्थिति से जोड़कर बताएँ "
        "(घर, नौकरी, पैसा, रिश्ते, पढ़ाई — जो इस सीख पर सबसे सही बैठे)"
    )
    return _PROMPT_TEMPLATE.format(
        premise=premise, lesson=lesson, apply=apply_line, words=target_words,
        min_words=min_words, max_words=max_words,
        cta=_pick_cta(), scenes=scenes, attribution=_pick_attribution(),
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


def _generate_with_gemini(premise, lesson, apply_line="", lesson_mode=False):
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
                _build_prompt(premise, lesson, apply_line),
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
                apply_line=str(data.get("apply") or apply_line or "").strip(),
                lesson_mode=bool(lesson_mode),
                thumb_hook=_clean_thumb_hook(data.get("thumb_hook"), lesson_mode),
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

            # DUPLICATE-SEEKH GATE.
            # The pools guarantee a fresh PREMISE; they cannot stop the model from
            # closing two different premises on the same sentence, and once a pool
            # completes a cycle the premise itself comes round again. Since the
            # seekh is the only line a viewer is meant to remember, a repeat of it
            # IS a repeat of the video as far as they are concerned. Ask the next
            # model instead - it is a fresh sample from a different model at
            # temperature 0.92, so it very rarely lands on the same line twice.
            if script.seekh and history.seen(SEEKH_LEDGER, script.seekh):
                log.warning(
                    "Model '%s' produced an already-published seekh (%r); "
                    "trying next model for a fresh one.",
                    model_name, script.seekh[:50],
                )
                if shortest_ok is None:
                    shortest_ok = script
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
                        apply_line=str(item.get("apply", "")),
                        # Declared per entry so swap_spoken_hook draws from the
                        # matching pool: a lesson-shaped fallback must not open
                        # with "कंस ने सब कर लिया, पर एक चीज़ भूल गया।"
                        lesson_mode=bool(item.get("lesson_mode", False)),
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
            apply_line="आज एक काम पूरा कीजिए और नतीजे की गिनती छोड़ दीजिए।",
            keywords=list(DEFAULT_KEYWORDS),
            scene_prompts=list(FALLBACK_SCENES),
        )
    return random.choice(scripts)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _split_topic(topic):
    """Accept a (premise, seekh[, jeevan]) tuple, or a plain string for --topic.

    LESSON_POOL entries carry a third field (where the seekh applies today);
    TOPIC_POOL entries carry two. Both are unpacked here so callers never have to
    know which pool a topic came from.
    """
    if isinstance(topic, (tuple, list)):
        premise = str(topic[0]) if len(topic) >= 1 else ""
        lesson = str(topic[1]) if len(topic) >= 2 else ""
        apply_line = str(topic[2]) if len(topic) >= 3 else ""
        return premise, lesson, apply_line
    return str(topic), "", ""


def _pick_topic():
    """Draw the next premise, weighted towards the lesson pool.

    WHY A MIX RATHER THAN A SWITCH
    ------------------------------
    The owner's instruction was that every reel must teach something new, and
    LESSON_POOL is built for exactly that. But the 150 leelas in TOPIC_POOL are
    genuine, recognisable content that pulls in search traffic a pure-advice reel
    never will - "गोवर्धन" and "सुदामा" are things people actively look for, and
    the new prompt now forces even those to be told as a cause-and-effect lesson
    with a same-day application. Throwing them away would cost reach for no gain.
    So the default is 70% lesson-first reels and 30% leela-as-evidence reels, and
    both shapes deliver a takeaway. Tunable via content.lesson_share.

    Returns (premise, lesson, apply_line, lesson_mode).
    """
    share = float(get_cfg("content.lesson_share", 0.7))
    use_lesson = LESSON_POOL and random.random() < share
    if use_lesson:
        topic = history.pick("lessons", LESSON_POOL)
        left, total = len(history.remaining("lessons", LESSON_POOL)), len(LESSON_POOL)
        label = "seekh"
    else:
        topic = history.pick("topics", TOPIC_POOL)
        left, total = len(history.remaining("topics", TOPIC_POOL)), len(TOPIC_POOL)
        label = "leela"
    premise, lesson, apply_line = _split_topic(topic)
    log.info("Auto-picked %s: %s  (%d of %d unused)", label, premise, left, total)
    return premise, lesson, apply_line, bool(use_lesson)


def generate_script(topic=None):
    """Return a single Hindi Script, preferring Gemini and falling back."""
    if topic:
        premise, lesson, apply_line = _split_topic(topic)
        lesson_mode = False
    else:
        premise, lesson, apply_line, lesson_mode = _pick_topic()

    script = _generate_with_gemini(premise, lesson, apply_line, lesson_mode)
    from_gemini = script is not None
    if not from_gemini:
        # The fallback tells whichever pre-written story it picked from
        # quotes.json, NOT the premise that was just drawn. So the drawn lesson
        # and its application must not be grafted on: a reel narrating Barbarik's
        # sacrifice would close with a line about checking your results too often.
        # The fallback's own seekh/apply are the only ones that match its text,
        # and lesson_mode stays as that entry declares it so the hook pool matches
        # too.
        script = _fallback_script(premise, lesson)
        log.info("Using fallback script: '%s'.", script.title)

    fresh_hook = _pick_spoken_hook(script.lesson_mode)
    script.text = swap_spoken_hook(script.text, fresh_hook)
    script.text = swap_cta(script.text)
    script.hook = fresh_hook
    script.screen_hook = _pick_screen_hook(script.lesson_mode)
    script.flashes = _pick_flashes()
    if from_gemini:
        if lesson and not script.seekh:
            script.seekh = lesson
        if apply_line and not script.apply_line:
            script.apply_line = apply_line

    if not script.thumb_hook:
        script.thumb_hook = _fallback_thumb_hook(script.lesson_mode)

    # Spend the seekh and the banner line permanently. Recorded into the same
    # pending buffer that generate.py commits only after the reel actually
    # renders, so a failed run does not burn either of them.
    history.remember(SEEKH_LEDGER, script.seekh)
    history.remember(THUMB_HOOK_LEDGER, script.thumb_hook)
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
        fresh_hook = _pick_spoken_hook(script.lesson_mode)
        script.text = swap_spoken_hook(script.text, fresh_hook)
        script.text = swap_cta(script.text)
        script.hook = fresh_hook
        script.screen_hook = _pick_screen_hook(script.lesson_mode)
        script.flashes = _pick_flashes()
        script.thumb_hook = _fallback_thumb_hook(script.lesson_mode)
        history.remember(THUMB_HOOK_LEDGER, script.thumb_hook)
        results.append(script)
    return results
