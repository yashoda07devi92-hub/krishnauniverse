# Sweet Soul Stories — monetisation reality check & action plan

Channel snapshot used for this plan: **399 subscribers, 113 videos, ~125,000 lifetime
views, roughly 5 weeks old, Shorts landing at 275–941 views each.**

---

## 1. The honest math on "monetise in 15 days"

There are two ways into the YouTube Partner Program, and a lower fan-funding tier.

| Gate | Requirement | Where the channel is | Verdict for 15 days |
|---|---|---|---|
| **Fan funding tier** | 500 subs + 3 public uploads in 90 days + (3,000 watch hours in 12 mo **OR** 3M Shorts views in 90 days) | 399 subs, uploads fine | **Subs part is reachable.** The hours/views part is not. |
| **Full ads — Shorts route** | 1,000 subs + **10,000,000** valid public Shorts views in 90 days | ~125K lifetime views | **Not possible.** Needs ~111,000 views/day; currently ~3,600/day — a 31× jump. |
| **Full ads — long-form route** | 1,000 subs + **4,000** valid public watch hours in 12 months | Long-form posts every other day | **Not possible in 15 days**, but this is the only realistic route overall. |

Why long-form is the realistic route: watch hours come from **duration**, not view count.
4,000 hours = 240,000 minutes. A 6-minute story watched ~40% of the way through banks
about 2.4 minutes per view, so roughly **100,000 long-form views** clears the gate — versus
**10 million** Shorts views. Same milestone, two orders of magnitude apart in difficulty.

Subscriber math: 399 subs in ~35 days is about 11/day. Reaching 1,000 in 15 days needs
about 40/day. Reaching **500** needs about 7/day, which is comfortably achievable.

**So: 15 days to full monetisation is not achievable at this scale.** What 15 days *can*
deliver is: cross 500 subs, remove the policy rejection risk described below, and get the
long-form engine producing enough volume that the 4,000-hour gate becomes a matter of
months instead of never.

---

## 2. The bigger risk nobody was tracking: policy, not SEO

YouTube renamed its "repetitious content" policy to **"inauthentic content"** in July 2025
and expanded it in July 2026. The first of the three named categories is
*generic, repetitive, or template-based content*, and it is **ineligible for monetisation**.
([YouTube channel monetisation policies](https://support.google.com/youtube/answer/1311392),
[TechCrunch on the July 2026 clarification](https://techcrunch.com/2026/07/20/youtube-clarifies-policies-around-ai-slop-and-upsetting-videos/))

Before this change, every one of the 113 uploads shipped with:

- the identical title suffix `| Cute & Wholesome #shorts #cute`
- the identical 8-hashtag block
- the identical two-sentence description tail
- the identical spoken sign-off, in the same synthetic voice
- a description that was a verbatim copy of the video's own narration

That is a machine-detectable template fingerprint across an entire channel. Even if the
subscriber and watch-hour gates were met, that is the pattern a YPP reviewer rejects. So
the work in this change set is not only about getting more views — it is about being
*approvable* when the numbers do arrive.

*Content in this section was rephrased from the linked sources for licensing compliance.*

---

## 3. What changed in the code

### New: per-video SEO engine
- **`modules/seo.py`** — subject detection (puppy / kitten / baby / pair buckets) drives a
  search anchor, 20 rotating title patterns, 4 rotating hashtag pools, a unique description
  body, and a tag set built to fit YouTube's 500-character budget.
- **`longform/modules/seo.py`** — the same idea for long-form, plus **auto-generated
  chapters** with real timestamps derived from the narration length.

### Nothing repeats until a pool is exhausted
Selection used to be `random.choice`, which puts the item straight back in the bag — so even
a large pool collides within days. Pools moved into `modules/pools.py` and grew:

| Pool | Before | After | Lasts (at 5 reels/day) |
|---|---|---|---|
| Story topics | 46 | **150** | 30 days |
| Spoken hooks | 58 | **120** | 24 days |
| Screen hooks | 24 | **80** | 16 days |
| Flash phrases | — | **152** | 10 days (3 per reel) |
| Sign-offs | 8 | **45** | 9 days |
| Title patterns | 20 | **40** | 8 days |
| Pinned comments | 8 | **29** | 6 days |
| Long-form topic seeds | 20 | **80** | 27 weeks (3/week) |

`modules/history.py` then draws **without replacement** and remembers across runs via
`history.json`, which both workflows commit back. Verified over a simulated 30 days of
5 reels/day: every pool is fully exhausted before a single item returns.

### Rolling captions off, word flash in
The word-by-word subtitle track is off — it covered the animal. Instead, three 2-3 word
phrases appear for ~1.3s each in the upper third, with no backdrop panel, so a muted viewer
still has something to read while the subject stays clear.

### Two buttons in the Actions tab (no terminal needed)
- **Fix Old Video Titles** — rewrites the back catalogue. Defaults to `dry-run`, and
  protects the 15 best-performing videos so nothing that is currently earning views gets
  re-indexed.
- **Slot Report** — read-only; prints median views per publish hour.

Both need a one-time token; `TOKEN_SETUP.md` covers it entirely in the browser.

### Long-form retargeted to 3-5 minutes
The composer never cuts a video to `max_duration_seconds` — it always matches the voiceover
length — so changing the duration config alone does nothing. Length is actually controlled by
**word count**: the storyteller voice runs ~145 words/minute, so `story.target_words` went
800 → **560** (~3.9 min) with a 440-700 word band. If a model returns something longer, the
next model is tried; if all of them overshoot, the shortest is trimmed at a sentence boundary
with the moral and sign-off re-appended.

### Upload schedule rebuilt around US prime time
Only 1 of the 5 old slots actually published inside a US prime window; three landed in the
middle of the American working day (11:23 AM, 2:09 PM, 5:51 PM ET). Now:

| Window | Slots | cron (UTC) | Publish (EDT / EST) |
|---|---|---|---|
| Morning scroll | 1 reel | `37 10` | 7:57 AM / 6:57 AM |
| After school | 1 reel | `53 18` | 4:13 PM / 3:13 PM |
| Evening prime | reel, Sun/Tue/Thu/Sat | `47 22` | 8:07 PM / 7:07 PM |
| Evening prime | reel, daily | `33 1` | 10:53 PM / 9:53 PM |
| Evening prime | reel, daily | `57 3` | 1:17 AM / 12:17 AM |
| Evening prime | long-form, Mon/Wed/Fri | `41 22` | 8:39 PM / 7:39 PM |

Both DST states were checked, so the crons never need a seasonal edit. Long-form also moved
from `*/2` day-of-month to Mon/Wed/Fri: `*/2` resets at month boundaries, so the 31st and the
1st both matched and it ran on two consecutive days several times a year.

**The queue delay is ~80 minutes, not 30.** Every cron is set that far ahead of its intended
publish time. The figure is measured, not assumed — five consecutive scheduled runs on this
repo started +83, +88, +64, +79 and +78 minutes after their cron, averaging **+78**. The
render itself is quick (those runs finished in 4-6 minutes), so nearly all of it is queue
time. Re-check with `python slot_report.py --shorts-only`, which reads the real publish hour
off YouTube, and do not shorten the lead without re-measuring.

**Scheduled runs are occasionally dropped altogether.** Run #160 failed with *"The job was not
acquired by Runner of type hosted even after multiple attempts"* alongside a GitHub internal
server error — no runner was ever assigned, so no code in this repo could have prevented it.
It costs one reel and needs no fix. Minute values avoid `:00` and `:30`, when the scheduler is
most congested.
- Metadata is now built **once at generate time** and stored in `manifest.json`. The
  uploader consumes it instead of stamping a fixed suffix on top.

### Retention fixes (why views were 275–941)
| Setting | Before | After | Reason |
|---|---|---|---|
| `captions.enabled` | `false` | `true` | A large share of Shorts plays start muted. With captions off, those viewers got no text at all. |
| `hook.enabled` | `false` | `true`, 2.5s | There was no scroll-stopper in the first frame. Now driven by short 2–4 word `SCREEN_HOOKS`, not the long spoken sentence that was unreadable at 150px. |
| `target_duration_seconds` | 30 | 24 | Shorts distribution leans on view-duration-as-a-percentage and on loops. |
| `clip_cut_seconds` | 2.5 | 1.8 | Faster visual changes reduce mid-video swipe-away. |
| `tts.voice` | 1 fixed voice | pool of 6 + rate variation | 113 videos in one identical synthetic voice reads as mass-produced. |
| Pexels keywords | 10 (incl. breed-specific) | 18 generic | The old list kept pulling the same handful of stock clips. |

### Content diversity
- Spoken hooks: 30 → **58**
- Story topics: 20 → **46**
- New: 24 short on-screen hooks; 8 rotating spoken sign-offs (was 1 fixed line)
- Long-form: rotating sign-offs, and `channel.name` corrected from **"Krishna Universe"** to
  **"Sweet Soul Stories"** — the long-form pipeline uploads to the *same* channel with the
  *same* token, so descriptions were welcoming viewers to a brand that does not exist there.

### New tools
- **`seo_report.py`** — verifies uniqueness and API limits with no keys needed.
  `python seo_report.py -n 40` → currently **604 checks passing**, 100% distinct titles,
  descriptions and hashtag sets.
- **`retitle_existing.py`** — rewrites the metadata of the **113 already-published videos**.
  Dry run by default. Fixing the generator only fixes future uploads; this fixes the back
  catalogue, which is what a reviewer actually inspects.
- **`modules/thumbnail.py`** — Shorts thumbnails for the channel grid / subscriptions feed /
  search. These are the surfaces where a viewer decides to subscribe, and the channel was
  letting YouTube pick an arbitrary (often blurry) frame.

---

## 4. Your 15-day checklist — the parts only you can do

### Day 1 — clean up the back catalogue (all in the browser)
1. Follow **`TOKEN_SETUP.md`** once to create the `YT_MANAGE_TOKEN_JSON` secret.
2. Actions → **Slot Report** → Run workflow. Read-only, so it proves the token works.
3. Actions → **Fix Old Video Titles** → Run workflow with `mode = dry-run`. Read the
   before/after pairs.
4. Same button with `mode = apply`. Start with `limit = 5`, wait 48 hours, check Studio, then
   move to 20/day.

Roughly 20/day for six days covers all 113. Keep batches small: `videos.update` costs 50 API
units and the daily uploads already spend ~8,250 of the 10,000 allowance.

The 15 best-performing videos are protected by default (`skip_top`). Rewriting a video that
is currently earning views makes YouTube re-index it and reach can dip for a few days —
there is nothing to lose on one sitting at 275 views, but there is on the ones carrying the
channel.

### Day 1 — check the setting that decides whether any of this pays
**Confirm the channel is not classified "Made for Kids."** Studio → Settings → Channel →
Advanced, and the Audience setting on individual videos. If YouTube treats this content as
made-for-kids, **comments are disabled entirely** and personalised ads are switched off, which
roughly halves RPM. Given the niche (babies, toddlers, kids' moral stories) this channel sits
right on the boundary, so verify it rather than assume. This matters more than any SEO change.

Also confirm **2-step verification** is on — custom thumbnails require it.

### Upload volume: what the real ceiling is
The repo is public, so GitHub Actions minutes are unlimited and no longer a constraint. The
binding limit is now the **YouTube Data API quota: 10,000 units/day**, and `videos.insert`
costs **1,600 units** — a hard ceiling of **6 uploads/day**. The quota resets at midnight
**Pacific** (07:00 UTC), not at UTC midnight.

Current allocation keeps every day at 8,250 units, leaving headroom for one retry:

| Days | Uploads | Units |
|---|---|---|
| Sun / Tue / Thu / Sat | 5 reels | 8,250 |
| Mon / Wed / Fri | 4 reels + 1 long-form | 8,250 |

That is **32 reels + 3 long-form per week**. To go beyond it, request a quota increase in
Google Cloud Console (free form, takes a while and may be refused).

### Every day — 10 minutes of manual work that the API cannot do
- **Pin the first comment.** The generator now prints one for each video
  (`PIN THIS COMMENT on https://youtu.be/...` in the workflow log). Comment velocity in the
  first hour is a strong distribution signal, and posting comments needs a scope the upload
  token does not have.
- **Reply to every comment** for the first hour after each upload.
- **Check Studio → Content → Shorts**, sort by views, and note which *screen hook* and which
  *subject* (puppy / kitten / baby) the winners used. Feed that back by weighting those pools.

### Week 1 — verify you are actually eligible
- Studio → **Earn** — confirm which tier is offered in your country. The 500-sub fan-funding
  tier rolled out region by region, so check rather than assume.

### Week 2 — decide the schedule on data, not on a hunch
```bash
python slot_report.py --shorts-only --detail
```
This groups every published video by the hour it went live in US Eastern and reports the
**median** views per slot. Read the median, not the mean — one lucky video makes a dead slot
look healthy. A slot needs ~8-10 videos before its number means anything, so give it two weeks.

The morning slot in particular is a deliberate re-test: a morning slot was removed earlier for
"almost no views", but that was measured when every video had an identical title and no
on-screen text, so the slot itself was never fairly tested.

### Things to stop doing
- Don't add more hashtags. Above 15, YouTube ignores **all** of them. The engine ships 9.
- Don't chase the Shorts monetisation route as the *goal*. Reels are for subscribers and
  reach; the 10M-views-in-90-days gate stays out of range. Watch hours come from long-form.
- Don't set cron times to the publish time you want. Actions queues jobs 5-30 minutes late and
  rendering adds ~10-15 more, so the crons are deliberately set ~40 minutes early.

---

## 5. Realistic timeline

| Milestone | Realistic ETA | Depends on |
|---|---|---|
| 500 subscribers | **10–20 days** | back catalogue retitled, thumbnails live, hooks on screen |
| 3,000 watch hours (fan funding) | 2–4 months | daily long-form, decent audience retention |
| 1,000 subscribers | 1.5–3 months | one or two Shorts breaking out |
| 4,000 watch hours (full ads) | **4–7 months** | 2 long-form/day at improved retention |

Anyone promising 15 days is selling something. The version of this that works is: fix the
template problem now so you are *approvable*, and put the volume into long-form so the
watch-hour clock actually moves.

---

## 6. Suggested next build (not in this change set)

An **analytics feedback loop**: pull per-video CTR, average view duration and subscribers-gained
from the YouTube Analytics API, then weight the hook / topic / subject pools toward what is
measurably winning. Right now every pool is drawn from uniformly at random, so the pipeline has
no way to learn from its own results. That is the single biggest remaining gap.
