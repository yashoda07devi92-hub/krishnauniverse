# Conventions for this repo

Read this before touching anything that produces titles, descriptions, hashtags, tags,
on-screen text, or visuals.

This is a **Hindi** channel about श्रीकृष्ण की लीलाएँ. It was ported from an English
cute-pets pipeline, and several of these rules exist specifically because a value carried
over from that channel would fail here silently — no exception, no error, just a wrong or
broken video published to a real audience.

## Hard rules

0. **All on-screen text goes through `modules/textrender.py`. Never `TextClip`.**
   moviepy's `TextClip` shells out to ImageMagick, which fails for Hindi twice over: the
   inherited DejaVu font has no Devanagari glyphs (every word becomes an empty box), and
   ImageMagick's `label:`/`caption:` operators do not run a complex-text shaper, so matras
   and conjuncts land in the wrong places even with a correct font. Neither raises an
   error. The `font` keys in `config.json` are ignored on purpose — `textrender.find_font()`
   resolves it.

1. **Narration is Hindi. Image prompts are English.** The image model produces garbled
   output from Devanagari prompts. `gemini_script` and `longform/modules/story` both request
   Hindi `text` and English `scene_prompts` / `scenes` in the same call, and
   `_clean_scene_prompts` drops any prompt that comes back mostly Devanagari.

2. **Split sentences on the danda.** Use `r"(?<=[।.!?])\s+"`, never `r"(?<=[.!?])\s+"`.
   Hindi uses `।` (U+0964) as its full stop, so splitting on `.` alone leaves a whole
   paragraph as one sentence — which silently breaks hook swapping, teasers, chapters and
   word-trimming.

3. **No ASCII-only regex on Hindi text.** `re.findall(r"[A-Za-z]+", ...)` matches nothing in
   Devanagari. This exact bug was in `longform/modules/seo._lesson_from_moral`, where it
   would have made every episode fall through to the same hard-coded label — one word
   repeated across the whole library, invisibly.

4. **`.upper()` is meaningless here.** Devanagari has no letter case. It has been removed
   everywhere; do not add it back thinking it styles the text.

5. **Rolling word-by-word captions stay OFF for Shorts** (`captions.enabled: false`). The
   owner removed them on the sibling channel: the large text with a dark backdrop pill
   covered the subject. The muted-viewer gap is covered by `flash_text` — three 2-4 word
   Hindi phrases in the upper third, no backdrop. Long-form captions ARE on: a 16:9 frame
   has room at the bottom and the subject is not filling the screen.

6. **Never append a fixed string to every title.** No suffixes, no stamped hashtags. The
   deleted line `f"{base} | Cute & Wholesome #shorts #cute"` is the exact anti-pattern —
   113 videos on the sibling channel shared one metadata fingerprint, which is both a
   distribution problem and a [YouTube "inauthentic content"](https://support.google.com/youtube/answer/1311392)
   monetisation risk (the policy names *generic, repetitive, or template-based content* as
   ineligible).

7. **All published metadata comes from the SEO modules** — `modules/seo.py` for Shorts,
   `longform/modules/seo.py` for long-form. Do not build titles or descriptions inline in
   `generate.py`, `upload_youtube.py` or `modules/youtube.py`.

8. **Hashtag count must stay ≤ 14.** YouTube ignores **all** hashtags on a video carrying
   more than 15, so a bigger number means zero working hashtags. Also do not add pure bait
   (`#viral`, `#funny`, `#memes`): hashtags are a targeting signal, and sending a Krishna
   katha to a non-devotional audience produces instant swipes, which weakens the video's
   early retention signal and *reduces* reach.

9. **Anything a viewer can notice repeating is drawn through `modules/history.py`**, never
   with bare `random.choice`. `history.pick` draws WITHOUT replacement and persists across
   runs. Two follow-ups that were real bugs:
   - Do not call `history.pick` inside `Script.__post_init__` or similar constructors.
     `load_fallback_scripts()` builds one object per bundled story on a single reel, which
     drained several pools in one run and forced an immediate reset.
   - Key per-subject pools by subject (`"title_patterns_" + subject`). A single shared key
     let one leela's videos mark another leela's pool dirty, degrading the draw to
     near-random.

10. **Pexels is for ATMOSPHERE only.** There is no footage of Krishna anywhere. Keywords
    must be things that genuinely exist as stock video — river water, peacocks, cows, diya
    flames, monsoon rain. The leela itself comes from `ai_images`. A keyword containing
    "krishna" means the pipeline is searching for footage that does not exist, and the reel
    silently loses its background.

11. **Motion must vary.** `_motion_from_image` picks from 10 camera moves and
    `_mixed_background` cuts real footage in between generated frames. Do not replace this
    with a single centre zoom, and do not set `ai_images.motion: false` — that was the
    shipped default in the long-form pipeline and it is literally what made it a slideshow.

12. **Audio must match the niche.** The synth bed is a tanpura drone with a slow bansuri
    line in a pentatonic raga; the hook accent is a temple bell or conch. The inherited
    "uplifting anthem / viral pop hook / Olympic swell" beds are wrong in a way a viewer
    feels in two seconds. Do not commit hard-coded music URLs that cannot be verified — a
    link that silently serves the wrong track is worse than no link.

13. **Declare the language on upload.** `defaultLanguage` and `defaultAudioLanguage` must
    be `hi`. Left unset, YouTube guesses from the title and can serve a Hindi katha to an
    English audience.

## Before claiming anything works

```bash
python seo_report.py -n 40          # metadata: uniqueness, API limits, SEO shape
python seo_report.py --longform     # same for the katha pipeline
python repeat_audit.py --days 90    # nothing repeats before its pool is exhausted
python check_workflows.py           # YAML, cron validity, IST windows, quota math
```

Fix the root cause; do not relax a threshold to make a check pass. When a check *is* wrong,
say why in the code — e.g. the title uniqueness check compares against the mathematical
ceiling of the decoration space, because a flat percentage passes at 30 days and fails at 90
for reasons the engine does not control.

**What these tools cannot verify:** the actual video render and Hindi glyph output. There is
no ffmpeg, Pillow or network access in the dev sandbox. Always run
**Actions → Run workflow → `selftest: true`** and inspect the artifact before trusting a
change to the composer, fonts or thumbnails.
