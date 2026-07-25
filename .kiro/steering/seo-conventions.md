# SEO & metadata conventions for this repo

Read this before touching anything that produces titles, descriptions, hashtags, tags or
on-screen text. These rules exist because the channel previously shipped 113 videos with an
identical metadata fingerprint, which is both a distribution problem and a
[YouTube "inauthentic content"](https://support.google.com/youtube/answer/1311392)
monetisation risk (the policy names *generic, repetitive, or template-based content* as
ineligible).

## Hard rules

0. **Rolling word-by-word captions stay OFF.** `captions.enabled` is `false` because the
   channel owner removed them: the 84px text with a dark backdrop pill covered the animal,
   which is the only thing the viewer came for. Do not re-enable without asking. The
   muted-viewer gap is covered by `flash_text` — three 2-3 word phrases in the upper third.
1. **Never append a fixed string to every title.** No suffixes, no stamped hashtags. The
   deleted line `f"{base} | Cute & Wholesome #shorts #cute"` is the exact anti-pattern.
2. **All published metadata comes from the SEO modules** — `modules/seo.py` for Shorts,
   `longform/modules/seo.py` for long-form. Do not build titles or descriptions inline in
   `generate.py`, `upload_youtube.py` or `modules/youtube.py`.
3. **Metadata is built once at generate time** and stored in `manifest.json` under
   `youtube_title` / `youtube_tags` / `hashtags` / `description`. Uploaders read those fields;
   they never re-derive or re-append.
4. **Static values in `config.json` (`youtube.hashtags`, `youtube.default_tags`) are fallbacks
   only.** They apply only when the SEO engine produced nothing.
5. **Anything user-visible that repeats must be a rotating pool**, not a constant: hooks,
   on-screen hooks, flash phrases, sign-offs/CTAs, TTS voices, description blocks, title
   patterns, pinned comments.
6. **Pools live in `modules/pools.py` / `longform/modules/pools.py`** — one place, easy to
   grow. Run `python modules/pools.py` to print sizes and fail on duplicates.
7. **Never select a user-visible string with `random.choice`.** Use
   `history.pick(name, pool)`, which draws WITHOUT replacement and remembers across runs via
   `history.json`. `random.choice` puts the item straight back in the bag, so even a
   150-item pool collides within days (birthday problem: ~50% chance of a repeat inside 15
   draws).
8. **Never call `history.pick()` from a dataclass `__post_init__` or any other hot path.**
   `load_fallback_scripts()` builds a `Script` for all 23 entries of `quotes.json` on a
   single reel — history picks there drained the hook, screen-hook and flash pools in one
   run and forced an immediate reset, which is exactly the repetition the system exists to
   prevent. Placeholders in `__post_init__` use plain `random.choice`; the real pick happens
   once per reel in `generate_script()`.
9. **`history.json` and `longform/history.json` must be committed, never gitignored.** Both
   scheduled workflows push them back (`permissions: contents: write`). Without that, every
   run starts from an empty history.

## YouTube limits to respect

| Field | Limit | Enforced in |
|---|---|---|
| Title | 100 chars (aim ≤72 — the Shorts UI truncates around 40–50 visible) | `seo.TITLE_HARD_LIMIT` |
| Description | 5,000 chars | `build_description` |
| Tags | **500 chars total**, separators included | `TAGS_CHAR_BUDGET = 480`, `_trim_tags` |
| Hashtags | above 15, YouTube ignores **all** of them | `seo.hashtag_count` (9) |
| Chapters | must start at `0:00`, need ≥3, each ≥10s, else ignored | `longform` `build_chapters` |
| Thumbnail | 2 MB max | `modules/thumbnail.py` |

## Before you commit

Run the self-check. It needs no API keys:

```bash
python seo_report.py -n 40              # Shorts
python seo_report.py --longform -n 20   # long-form
```

It fails if titles/descriptions/hashtag sets are not sufficiently distinct, if any API limit is
exceeded, if the legacy `Cute & Wholesome` suffix reappears, or if a video's subject targeting
drifts from its content (e.g. a kitten video tagged `#babyanddog`).

## Subject targeting

`detect_subject()` is **weighted, not first-match**: title and footage keywords carry weight 3,
the narration body weight 1, and the narration's first sentence is excluded entirely because it
is a randomly assigned generic hook that often names an animal the video does not contain. Do
not simplify this back to a plain regex scan — that bug caused kitten videos to be tagged and
hashtagged as baby-and-dog videos and served to the wrong audience.
