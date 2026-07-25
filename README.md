# Krishna Universe — Hindi Krishna-katha automation

Fully automated pipeline for a faceless Hindi YouTube channel: one leela from
Krishna's life and one clear seekh per video, 5 Shorts a day at India prime time.

## How one reel is built

1. **Katha** — Gemini writes a ~30 second Hindi narration for one premise drawn
   from a pool of 143 leelas (birth → Gokul → Vrindavan → Mathura → Dwarka →
   Kurukshetra → Gita → Prabhas). It also returns `scene_prompts`: English
   one-line shot descriptions for each beat of the story. Falls back to
   `quotes.json` if the key is missing.
2. **Frames** — each `scene_prompt` becomes a vertical 1080×1920 image via
   Pollinations (`modules/ai_images.py`). This is the primary visual source:
   there is no stock footage of Krishna anywhere, so it has to be generated.
3. **Voice** — Hindi katha narration via edge-tts (`hi-IN-MadhurNeural` lead),
   slowed to ~-10%, with gTTS(hi) as automatic fallback.
4. **Video** — `modules/video_composer.py` gives every frame a *different*
   camera move (pan / tilt / drift / push / pull) and splices **real Pexels
   atmosphere footage** between them — river water, monsoon rain, lamp flame,
   peacock, cows. That mix is what stops it reading as a slideshow.
5. **On-screen text** — a 2.5s Hindi hook label, then three short Hindi phrases
   flashed mid-video in the upper third. Rolling subtitles are **off on purpose**
   (they cover the artwork, which is the whole visual).
6. **SEO** — per-video Hindi title, description, hashtags and tags from
   `modules/seo.py`. Nothing is a fixed suffix, and nothing repeats until its
   pool is exhausted.
7. **Upload** — YouTube via OAuth2, with a generated 9:16 thumbnail.

## Two things that are not obvious

**Hindi text needs its own renderer.** DejaVu Sans (moviepy/ImageMagick's
default) has no Devanagari glyphs, and ImageMagick's `label:`/`caption:` does no
text shaping, so matras and conjuncts come out wrong even with a Devanagari font
loaded. Both failures are silent. All on-screen text therefore goes through
`modules/textrender.py` (Pillow + libraqm). The workflow installs
`fonts-noto-devanagari`.

**Nothing repeats.** Every pool is drawn *without replacement* through
`modules/history.py`, and `history.json` is committed back by the workflow so the
rotation survives across runs. At 5 reels/day: topics 28 days, spoken hooks 23
days, screen hooks 21 days, flashes 12 days, sign-offs 9 days. On-screen phrases
are also matched to the story's own chapter of Krishna's life, so a Govardhan
reel never flashes a Mathura character's name.

## Schedule (IST — no DST, so cron never drifts)

| Slot | Publish (IST) | cron (UTC) | Days |
|---|---|---|---|
| Morning puja | ~7:15 AM | `25 0` | daily |
| Morning puja | ~8:45 AM | `55 1` | daily |
| Lunch | ~1:30 PM | `40 6` | daily |
| Night prime | ~8:45 PM | `55 13` | Sun/Tue/Thu/Sat |
| Night prime | ~10:30 PM | `40 15` | daily |
| Long-form | ~9:20 PM | `52 13` | **disabled — see below** |

Cron fires ~80 minutes before publish. That lead is **measured**, not guessed:
GitHub Actions schedules are queued, and five consecutive runs on a sibling repo
averaged +78 minutes. Verify with `python slot_report.py --shorts-only` after two
weeks and adjust on data.

Quota: the YouTube Data API allows 10,000 units/day and `videos.insert` costs
1,600, a hard ceiling of 6 uploads. The quota resets at **midnight Pacific
(07:00 UTC)**, not UTC midnight, so the slot list is balanced against that
boundary: every quota day carries 5 uploads = 8,250 units, leaving room for one
retry.

## Long-form: currently disabled

`auto-longform.yml`'s schedule is commented out. The Shorts pipeline is fully
ported to Hindi; the long-form one still has its inherited English
"moral stories for kids" prompt, pools and SEO. Publishing that onto a Hindi
devotional channel would confuse the topic model and split the audience, so it is
switched off rather than left running. Uncommenting one cron line re-enables it
once the Hindi port lands.

## Secrets (Settings → Secrets and variables → Actions)

| Secret | Needed for |
|---|---|
| `YT_TOKEN_JSON` | uploading (see `TOKEN_SETUP.md`) |
| `GEMINI_API_KEY` | writing the katha |
| `PEXELS_API_KEY` | real atmosphere cutaways |
| `POLLINATIONS_TOKEN` | the Krishna frames — **effectively required** |

`POLLINATIONS_TOKEN` is not optional on this channel the way it is elsewhere:
the generated frames *are* the video. Without a token most requests get
rate-limited and the reel falls back to atmosphere footage with no Krishna in it
at all. Get an `sk_` secret key from https://enter.pollinations.ai.

## Local commands

```bash
python seo_report.py -n 40        # metadata self-check, no network needed
python modules/pools.py           # pool sizes + duplicate audit
python diagnose.py                # check secrets and sources
python generate.py --per-day 1    # build one reel
python slot_report.py --shorts-only   # which publish hour actually performs
```

## Manual step each day

The run log prints a `PIN THIS COMMENT` line per video. Paste it as the first
comment and pin it. Comment velocity in the first hour is a strong ranking
signal and viewers rarely start a thread themselves. This cannot be automated
with the `youtube.upload` scope, and the YouTube Data API has no endpoint for
pinning a comment at all.

## Content notes

Visuals are AI-generated and nature footage is from Pexels; both are disclosed in
every description. Stories stay to prasangs described in the scriptures, told in
plain Hindi. Add only royalty-free devotional instrumentals to `assets/music/`.
