# Krishna Universe

Automated Hindi YouTube channel: श्रीकृष्ण की लीलाएँ और उनसे मिलने वाली सीख.

- **Shorts** — 5 per day, 30 seconds each, published at India prime time
- **Long-form katha** — 3 per week (Mon/Wed/Fri), 5-8 minutes, 20:30 IST

Everything runs on GitHub Actions. No server, no manual step in the normal path.

---

## The one thing to understand first

There is no stock footage of Krishna anywhere in the world.

That single fact shapes the whole visual layer, and it is the biggest difference
from the cute-pets pipeline this was ported from. That channel searched Pexels
for "puppy playing" and got real footage of the actual subject. Here:

- The **leela itself** is generated per story beat (`modules/ai_images.py`),
  from English scene prompts Gemini returns alongside the Hindi narration.
- **Real footage is used only for atmosphere** — river water, peacocks, cows,
  diya flames, monsoon rain. Things that genuinely exist on video sites.
- The composer **interleaves the two** (`_mixed_background`): two generated
  frames, then one real moving shot, repeating.

That mix is what stops the result reading as a slideshow. Animating a still with
a slow zoom is not enough — the eye recognises the repeating move. Real motion
cut in every few seconds gives it something to anchor on, and the generated
frames around it start reading as filmed. Every still also gets one of 10
different camera moves (push, pull, pan, tilt, diagonal) rather than the same
centre zoom every time.

---

## Setup

Four GitHub Actions secrets (Settings → Secrets and variables → Actions):

| Secret | Where to get it | Needed for |
|---|---|---|
| `YT_TOKEN_JSON` | See [TOKEN_SETUP.md](TOKEN_SETUP.md) — browser only, no terminal | Uploading |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/app/apikey) | Writing the katha |
| `PEXELS_API_KEY` | [pexels.com/api/new](https://www.pexels.com/api/new/) | Atmosphere footage |
| `POLLINATIONS_TOKEN` | [enter.pollinations.ai](https://enter.pollinations.ai) — take the `sk_` key | Krishna scene images |

`POLLINATIONS_TOKEN` is not optional in practice. On this channel the generated
images *are* the video, so a rate-limited run produces a katha with no Krishna
in it.

Also set the channel handle in `config.json` → `channel.url` and
`seo.channel_url`. It is printed in every description, so a wrong handle sends
viewers nowhere.

---

## Before you let the schedule run

Run one manual test: **Actions → Krishna Universe Auto Reel → Run workflow →
`selftest: true`**. This renders a real reel but does **not** upload it. Download
the artifact and check:

1. **Hindi text renders correctly** — not empty boxes, and matras/conjuncts in
   the right places. This is the highest-risk item and cannot be verified
   without actually rendering. See the font note below.
2. The flash text is readable and not covering the subject.
3. The motion looks like camera movement, not a slideshow.

---

## Hindi text: why there is a whole module for it

`modules/textrender.py` exists because the inherited text path could not draw
Hindi at all, and failed **silently** in two separate ways:

1. The configured font was DejaVu-Sans-Bold, which contains no Devanagari
   glyphs — every word renders as a row of empty boxes (tofu).
2. moviepy's `TextClip` shells out to ImageMagick, whose `label:`/`caption:`
   operators do not run a complex-text shaper. Even with a correct font,
   "कृष्ण" comes out as "क ृ ष ् ण" and the i-matra in "शिक्षा" lands on the
   wrong side of the consonant.

Neither raises an error. So all text now renders through Pillow, whose wheels
bundle libraqm and therefore shape Devanagari properly. The workflow installs
`fonts-noto-core` and **hard-fails** if no Devanagari font is found — every
other missing dependency here degrades gracefully, but this one would publish a
broken video.

---

## Nothing repeats

Every user-visible choice is drawn **without replacement** through
`modules/history.py`, and the history is committed back to the repo after each
run so it persists across GitHub Actions jobs.

| Pool | Size | Cycles in |
|---|---|---|
| Leelas (with their seekh) | 150 | 30 days |
| Spoken hooks | 121 | 24 days |
| On-screen hooks | 80 | 16 days |
| Flash phrases | 150 | 10 days |
| Sign-offs | 45 | 9 days |
| Title patterns | 60 | 12 days |
| Descriptions (openers/questions/CTAs) | 40 each | 8 days |
| Long-form kathas | 80 | 27 weeks |

Verify it rather than trusting the table:

```bash
python repeat_audit.py --days 90
```

This simulates 90 days of publishing and asserts that nothing repeats before its
pool is genuinely exhausted. It also checks titles against the *mathematical
ceiling* of the decoration space, not an arbitrary percentage.

---

## Hashtags: why 14 and not 30

Two hard limits make maximising the count counter-productive:

1. **YouTube ignores ALL hashtags on a video carrying more than 15.** Thirty
   hashtags does not mean triple the reach — it means zero working hashtags.
2. **Hashtags are a targeting signal, not a lottery ticket.** `#viral` on a
   Krishna katha tells YouTube to test the video against an audience that did
   not come for devotional content. They swipe immediately, early retention
   drops, and that weak signal follows the video — so an irrelevant "viral" tag
   *reduces* reach.

So the count is 14 (one slot of headroom under the cliff), and the pools are
broad-but-relevant (`#shortsviral`, `#ytshorts`, `#devotional`) rather than pure
bait. Reach in this niche comes from the hook, the first frame and retention.

---

## Verification tools

```bash
python seo_report.py -n 40          # metadata: uniqueness, API limits, SEO shape
python seo_report.py --longform     # same for the katha pipeline
python repeat_audit.py --days 90    # nothing repeats before it must
python check_workflows.py           # YAML, cron validity, IST windows, API quota
python diagnose.py                  # which API keys and sources are actually live
```

None of these need media libraries or a running render.

---

## Layout

```
config.json              Shorts settings (every non-obvious value has a comment)
generate.py              Build reels -> output/ + manifest.json
upload_youtube.py        Upload from the manifest
modules/
  pools.py               150 leelas, hooks, flash phrases, sign-offs
  gemini_script.py       Hindi narration + English scene prompts
  ai_images.py           Krishna scene frames (1080x1920)
  pexels_video.py        Atmosphere footage only
  video_composer.py      Motion engine, mixing, audio, overlays
  textrender.py          Devanagari-safe text (see above)
  seo.py                 Titles, descriptions, tags, hashtags
  history.py             Draw-without-replacement, persisted
  thumbnail.py           Shorts thumbnail (channel grid / search)
longform/                The same shape, for 5-8 minute kathas
.github/workflows/       Schedules + two manual buttons
```

Manual buttons in the Actions tab: **Fix Old Video Titles** (dry-run by default,
protects the top 15 performers) and **Slot Report** (read-only; shows which
publish hour actually earns views).

---

## Known limitations

- **Video render and Hindi glyph output are unverified.** They cannot be checked
  without ffmpeg, Pillow and network access. Run the selftest before trusting
  the schedule.
- **Pinned comments are manual.** The upload token carries only the
  `youtube.upload` scope, which cannot post comments — and there is no YouTube
  API to *pin* one at all. `generate.py` logs suggested text to paste.
- **Music is synthesized** (tanpura drone + slow bansuri line in a pentatonic
  raga). Commit your own royalty-free instrumental `.mp3` files to
  `assets/music/` to override it.
