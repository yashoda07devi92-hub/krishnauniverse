"""
Long-form moral-story generation for Krishna Universe.

Produces a ~5-7 minute (about 750-1000 word) narrated MORAL STORY for kids in
American English using Google's Gemini API. If no API key is configured, or
every model candidate fails, it falls back to the bundled stories.json of
pre-written stories.

The script is engineered for RETENTION:
  * A 1-2 sentence scroll-stopping HOOK as the opener.
  * "Open loops" / mini cliffhangers sprinkled through the story so viewers
    keep watching to find out what happens.
  * A clear, satisfying MORAL stated plainly near the end.
  * A spoken call-to-action close.

Heavy third-party libraries are imported lazily so importing this module never
hard-fails where the dependency is missing.
"""

import json
import logging
import random
import re
from dataclasses import dataclass, field

from .config import STORIES_PATH, get_cfg, get_env
from .pools import CTA_CANDIDATES, TOPIC_POOL
from . import history

log = logging.getLogger("krishna.story")

# Lesson/topic seeds and spoken sign-offs now live in modules/pools.py so they can
# be grown in one place: seeds 20 -> 80 (about 27 weeks at 3 episodes/week) and
# sign-offs 5 -> 30. Both are imported at the top of this module and drawn through
# modules/history.py, i.e. WITHOUT replacement, so no premise or closing line
# returns until its pool is genuinely exhausted.


_PROMPT_TEMPLATE = """आप "{channel}" नाम के एक हिंदी YouTube चैनल के मुख्य लेखक हैं।
इस चैनल पर भगवान श्रीकृष्ण के जीवन की एक पूरी कथा विस्तार से सुनाई जाती है।
दर्शक भारत में हैं — आम हिंदी बोलने वाले परिवार। कथा एक शांत, गंभीर, कथावाचक
जैसी आवाज़ में पढ़ी जाती है।

इस विषय पर एक पूरी कथा लिखें:
  कथा: {topic}
  सीख: {lesson}

लंबाई (बहुत ज़रूरी और सख़्त):
- लगभग {words} शब्द। बोलने पर {min_words} से {max_words} शब्द = लगभग 5 से 8 मिनट।
- {max_words} शब्द से ज़्यादा बिल्कुल नहीं — उससे लंबी कथा अस्वीकार कर दी जाएगी।
- {min_words} से कम भी नहीं। पूरी कथा सुनाइए, दृश्यों के साथ — बस कसी हुई।
- कोई भी दृश्य जो कथा को आगे नहीं बढ़ाता, हटा दें।

शुरुआत (सबसे ज़रूरी हिस्सा):
- पहले 1-2 वाक्य ऐसे हों कि दर्शक रुक जाए — एक सवाल, एक वादा, या एक छोटा रहस्य।
  जैसे: "कंस को पता था कि उसकी मौत कैसे आएगी — फिर भी वो उसे रोक नहीं सका।"
  हर कथा के लिए नया और उसी कथा से जुड़ा hook लिखें।

दर्शक को रोके रखना:
- सरल, बोलचाल की हिंदी। कठिन संस्कृत शब्द नहीं। एक बच्चा भी समझ जाए।
- छोटे-छोटे दृश्य: शुरुआत, समस्या, तनाव बढ़ना, मोड़, और संतोष देने वाला अंत।
- हर एक-दो मिनट पर एक ऐसी लाइन डालें जो आगे सुनने पर मजबूर करे, जैसे
  "लेकिन आगे जो हुआ, वो किसी ने सोचा भी नहीं था।"
- वाक्य छोटे रखें ताकि बोलने में आसान हों।

सीख:
- कथा को ऊपर दी गई सीख तक साफ़-साफ़ पहुँचाना है।
- अंत के पास सीख को एक साफ़ लाइन में कहें, इस तरह शुरू करते हुए:
  "इस कथा की सीख यही है कि"

भाव (बहुत ज़रूरी):
- कथा सच में दिल को छूने वाली हो — गर्म, भावुक, ऐसी कि अंत में गला भर आए।
  मुख्य पात्र से दर्शक का सच्चा जुड़ाव बने, तभी अंत असर करेगा।
- श्रद्धा बनाए रखें। कोई ऐसी बात न लिखें जो शास्त्रों में नहीं है, और कथा को
  वैसे ही रखें जैसे वो प्रचलित है। किसी की भावना को ठेस न पहुँचे।

अंत:
- सबसे आख़िर में बिल्कुल यही वाक्य लिखें: "{cta}"

रूप:
- केवल बोले जाने वाले वाक्य। कोई emoji नहीं, कोई hashtag नहीं, कोई markdown नहीं,
  कोई stage direction नहीं, कोई अध्याय शीर्षक नहीं। देवनागरी में लिखें।

सिर्फ़ एक JSON object लौटाएँ (कोई code fence नहीं), इन keys के साथ:
  "title": हिंदी में छोटा, जिज्ञासा जगाने वाला शीर्षक (अधिकतम 9 शब्द),
  "hook": शुरुआत का वही एक hook वाक्य (thumbnail पर भी यही जाता है),
  "moral": सीख एक हिंदी लाइन में,
  "main_character": मुख्य पात्र का SHORT visual description, ENGLISH में, ताकि
          वो हर दृश्य में एक जैसा दिखे। जैसे: "young lord krishna, around 8
          years old, blue-tinted skin, peacock feather in his hair, yellow
          dhoti, bare feet". ठोस और स्थिर रखें, हर scene में यही इस्तेमाल होगा।
  "text": पूरी कथा एक string में (शुरुआत का hook और अंत का CTA दोनों शामिल),
  "scenes": 10 से 14 SHORT visual descriptions का array, कथा के क्रम में, ENGLISH
          में। हर scene उस पल के पात्र + जगह + क्रिया + रोशनी बताए, जैसे
          "young krishna lifting a mountain over a village while heavy rain
          falls, villagers sheltering beneath, dramatic storm light". हर scene
          एक ही सजीव वाक्य। दृश्य में कोई text/अक्षर नहीं।
          ये सब अंग्रेज़ी में ही लिखें, हिंदी में नहीं — image model हिंदी prompt
          से बिगड़ा हुआ चित्र बनाता है।
  "keywords": 5-8 ENGLISH stock-footage search phrases, सिर्फ़ ATMOSPHERE के लिए
          जो असल में video sites पर मिलती हैं — "river water flowing sunlight",
          "peacock feathers close up", "cows grazing green field india",
          "oil lamp diya flame dark", "monsoon rain on leaves". इनमें कृष्ण या
          कोई देवता नहीं होना चाहिए — असली footage मौजूद ही नहीं है; ये सिर्फ़
          पृष्ठभूमि की बनावट के लिए हैं।
"""


@dataclass
class Story:
    title: str
    text: str
    hook: str = ""
    moral: str = ""
    keywords: list = field(default_factory=list)
    scenes: list = field(default_factory=list)
    main_character: str = ""

    def __post_init__(self):
        if not self.keywords:
            self.keywords = list(get_cfg("pexels.default_keywords", []))
        if not self.hook:
            parts = re.split(r"(?<=[।.!?])\s+", self.text.strip(), maxsplit=1)
            self.hook = parts[0] if parts else self.title
        if not self.scenes:
            self.scenes = derive_scenes_from_text(self.text)

    @property
    def word_count(self):
        return len(self.text.split())


def derive_scenes_from_text(text, target=12):
    """Fallback: split the narration into ~target visual scene prompts so AI
    images can still be generated when the model didn't return a 'scenes' list
    (e.g. the bundled fallback stories)."""
    sentences = [s.strip() for s in re.split(r"(?<=[।.!?])\s+", (text or "").strip()) if s.strip()]
    if not sentences:
        return []
    target = max(4, min(target, len(sentences)))
    per = max(1, len(sentences) // target)
    scenes = []
    for i in range(0, len(sentences), per):
        chunk = " ".join(sentences[i : i + per]).strip()
        if chunk:
            scenes.append(chunk)
        if len(scenes) >= target:
            break
    return scenes


def _cta_pool():
    """Sign-off pool: modules/pools.py, with config as an override."""
    return list(get_cfg("channel.cta_pool", []) or []) or list(CTA_CANDIDATES)


def _pick_cta():
    """Rotate the spoken sign-off, drawn without replacement.

    A single fixed closing line repeated word-for-word at the end of every
    episode is both a mass-production signal and a cue that trains returning
    viewers to click away the moment they hear it. Drawn through history so it
    genuinely rotates instead of landing on the same line repeatedly by chance.
    """
    return history.pick("ctas", _cta_pool())


def _has_cta(text):
    low = (text or "").lower()
    pool = _cta_pool()
    pool.append(get_cfg("channel.cta", ""))
    return any(c and c.lower() in low for c in pool)


# Narration speed of the edge-tts storyteller voices at the configured rate,
# measured against the bundled stories: ~145 spoken words per minute. Used to
# translate the 3-5 minute target into a word budget the model can actually aim
# at, and to sanity-check what comes back.
WORDS_PER_MINUTE = 145


def _word_budget():
    """Return (target, minimum, maximum) words for the configured duration."""
    target = int(get_cfg("story.target_words", 560))
    min_words = int(get_cfg("story.min_words", 420))
    max_words = int(get_cfg("story.max_words", 700))
    return target, min_words, max_words


def _estimated_minutes(word_count):
    return word_count / float(WORDS_PER_MINUTE)


def _build_prompt(lesson, topic):
    target, min_words, max_words = _word_budget()
    return _PROMPT_TEMPLATE.format(
        channel=get_cfg("channel.name", "Krishna Universe"),
        words=target,
        min_words=min_words,
        max_words=max_words,
        lesson=lesson,
        topic=topic,
        cta=_pick_cta(),
    )


def _trim_to_words(story, max_words):
    """Shorten an over-long story to fit the 5-minute ceiling.

    Only used as a last resort, when every model candidate came back too long.
    The video composer does NOT cut the video to `max_duration_seconds` -- it
    always matches the voiceover length -- so an 900-word story would silently
    produce a 6+ minute video no matter what the config says. Trimming happens
    here instead, at a sentence boundary, and the moral plus the sign-off are
    re-appended so the story still lands properly instead of stopping mid-scene.
    """
    sentences = [s for s in re.split(r"(?<=[।.!?])\s+", story.text.strip()) if s]
    kept, used = [], 0
    # Reserve room for the moral and the closing CTA we are about to add back.
    reserve = len((story.moral or "").split()) + 12
    for sentence in sentences:
        n = len(sentence.split())
        if used + n > max_words - reserve and kept:
            break
        kept.append(sentence)
        used += n

    tail = []
    if story.moral and story.moral.lower() not in " ".join(kept).lower():
        tail.append(story.moral)
    story.text = " ".join(kept + tail).strip()
    if not _has_cta(story.text):
        story.text = story.text.rstrip() + " " + _pick_cta()
    log.warning(
        "Trimmed story to %d words (~%.1f min) to respect the 5-minute ceiling.",
        story.word_count, _estimated_minutes(story.word_count),
    )
    return story


def _parse_model_json(raw):
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


def _generate_with_gemini(lesson, topic):
    api_key = get_env("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set - using local stories.json fallback.")
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
    candidates = get_cfg("gemini.model_candidates", ["gemini-2.0-flash"])
    ordered = [default_model] + [m for m in candidates if m != default_model]

    prompt = _build_prompt(lesson, topic)
    temperature = get_cfg("gemini.temperature", 0.95)
    _target, min_words, max_words = _word_budget()
    # Best over-long candidate seen so far, kept so we can trim it instead of
    # dropping to stories.json (which would repeat one of only three stories).
    oversize = None

    for model_name in ordered:
        try:
            log.info("Requesting story from Gemini model '%s'...", model_name)
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(
                prompt, generation_config={"temperature": temperature}
            )
            raw = getattr(resp, "text", None)
            data = _parse_model_json(raw)
            if not data or not data.get("text"):
                log.warning("Model '%s' returned no usable text; trying next.", model_name)
                continue
            story = Story(
                title=str(data.get("title") or "A Moral Story").strip(),
                text=str(data["text"]).strip(),
                hook=str(data.get("hook") or "").strip(),
                moral=str(data.get("moral") or "").strip(),
                keywords=[str(k).strip() for k in data.get("keywords", []) if str(k).strip()],
                scenes=[str(s).strip() for s in data.get("scenes", []) if str(s).strip()],
                main_character=str(data.get("main_character") or "").strip(),
            )
            if not _has_cta(story.text):
                story.text = story.text.rstrip() + " " + _pick_cta()
            if story.word_count < min_words:
                log.warning(
                    "Model '%s' story too short (%d words, ~%.1f min); trying next.",
                    model_name, story.word_count, _estimated_minutes(story.word_count),
                )
                continue
            if story.word_count > max_words:
                # Would overshoot the 5-minute ceiling. Remember it and ask the
                # next model, which often obeys the length instruction better.
                log.warning(
                    "Model '%s' story too long (%d words, ~%.1f min); trying next.",
                    model_name, story.word_count, _estimated_minutes(story.word_count),
                )
                if oversize is None or story.word_count < oversize.word_count:
                    oversize = story
                continue
            log.info(
                "Gemini story ready via '%s' (%d words, ~%.1f min).",
                model_name, story.word_count, _estimated_minutes(story.word_count),
            )
            return story
        except Exception as exc:
            log.warning("Gemini model '%s' failed (%s); trying next.", model_name, exc)
            continue

    if oversize is not None:
        log.warning("Every candidate overshot 5 minutes; trimming the shortest one.")
        return _trim_to_words(oversize, max_words)

    log.warning("All Gemini model candidates failed - using local stories.json.")
    return None


# --------------------------------------------------------------------------
# Local fallback
# --------------------------------------------------------------------------
def load_fallback_stories():
    try:
        with open(STORIES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("stories", []) if isinstance(data, dict) else data
        stories = []
        for item in items:
            try:
                stories.append(
                    Story(
                        title=str(item.get("title", "A Moral Story")),
                        text=str(item["text"]),
                        hook=str(item.get("hook", "")),
                        moral=str(item.get("moral", "")),
                        keywords=list(item.get("keywords", [])),
                        scenes=list(item.get("scenes", [])),
                        main_character=str(item.get("main_character", "")),
                    )
                )
            except Exception:
                continue
        return stories
    except Exception as exc:
        log.error("Could not load stories.json (%s).", exc)
        return []


def _fallback_story():
    stories = load_fallback_stories()
    if stories:
        return random.choice(stories)
    return Story(
        title="The Honest Woodcutter",
        text=(
            "What would you do if a stranger offered you gold you did not earn? "
            "A poor woodcutter once dropped his only axe into a deep river. As he "
            "wept, a shining spirit rose from the water holding an axe of pure gold. "
            "Is this yours, she asked. No, the woodcutter said, mine was only old "
            "iron. Pleased by his honesty, the spirit gave him the gold axe and the "
            "iron one too. The moral of the story is that honesty is always "
            "rewarded in the end. Subscribe for a new moral story every day!"
        ),
        moral="Honesty is always rewarded in the end.",
        keywords=["forest river sunlight", "old man working", "calm water nature"],
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def generate_story(lesson=None, topic=None):
    """Return a single Story, preferring Gemini, falling back to stories.json."""
    if not lesson or not topic:
        lesson, topic = history.pick("topics", TOPIC_POOL)
        log.info(
            "Auto-picked lesson: %s | topic: %s  (%d of %d seeds unused)",
            lesson, topic,
            len(history.remaining("topics", TOPIC_POOL)), len(TOPIC_POOL),
        )
    story = _generate_with_gemini(lesson, topic)
    if story is None:
        story = _fallback_story()
        log.info("Using fallback story: '%s'.", story.title)
    return story
