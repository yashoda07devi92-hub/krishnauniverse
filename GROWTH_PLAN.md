# Krishna Universe — monetisation plan

This channel is starting from zero. That is genuinely better than starting from a
library with a template fingerprint, because the constraint that matters most is
decided before the first upload, not after a hundred of them.

---

## 1. The honest math

Two routes into the YouTube Partner Program, plus a lower fan-funding tier.

| Gate | Requirement | Realistic timeline here |
|---|---|---|
| **Fan funding tier** | 500 subs + 3 public uploads in 90 days + (3,000 watch hours in 12 mo **OR** 3M Shorts views in 90 days) | Subs are the easy half. The hours half comes from long-form. |
| **Full ads — Shorts route** | 1,000 subs + **10,000,000** valid public Shorts views in 90 days | Needs ~111,000 Shorts views **per day** for 90 days straight. Not the route. |
| **Full ads — long-form route** | 1,000 subs + **4,000 watch hours** in 12 months | **This is the route.** ~92,000 views on 6-minute kathas at 40% retention. |

Availability of the lower tier varies by country — check
**Studio → Earn** to see what your account is actually offered.

### Why long-form, stated plainly

A 6-minute katha watched to 40% yields 2.4 minutes per view. 4,000 hours =
240,000 minutes = about **92,000 views**. The Shorts route asks for **10 million**
views for the same milestone.

That is a 100× difference in required traffic. Shorts are for finding subscribers;
long-form is the only thing that produces the metric that unlocks ads.

**Realistic full monetisation: 4-8 months**, driven by long-form, if the kathas
hold retention. Anyone promising 15 days is not doing the arithmetic.

---

## 2. What the schedule is doing

All times are **IST publish times**, not cron times. The crons sit ~80 minutes
earlier because GitHub's Actions scheduler queues jobs — measured at +78 minutes
average across five consecutive runs, not guessed.

| Slot | Publish IST | Days |
|---|---|---|
| Morning puja | 07:15 | daily |
| Lunch | 13:30 | daily |
| Sandhya aarti | 19:15 | Sun/Tue/Thu/Sat |
| Night peak | 21:15 | daily |
| Late night | 22:45 | daily |
| **Long-form katha** | **20:30** | Mon/Wed/Fri |

Weekly: **32 reels + 3 kathas.**

Two windows matter for devotional content in India, and both are covered: the
morning puja hour, and the long evening stretch from aarti through late night.
IST has no daylight saving, so these crons never need a seasonal correction.

### The ceiling is the API quota, not GitHub

Actions minutes are unlimited on a public repo. The real limit is the YouTube
Data API: **10,000 units/day**, and `videos.insert` costs **1,600** — a hard
ceiling of **6 uploads/day**.

The quota day resets at **midnight Pacific (07:00 UTC)**, not UTC midnight. This
is easy to get wrong: the 07:15 and 13:30 IST slots run before 07:00 UTC, so they
belong to the *previous* quota day. Accounting for that:

- Normal day: 5 reels = 8,250 units
- Long-form day: 4 reels + 1 katha = 8,250 units (the 19:15 slot is skipped)

Both leave room for one retry. `python check_workflows.py` verifies this
arithmetic rather than trusting the comment.

Want more than 6 uploads/day? Request a quota increase in Google Cloud Console.
It is free but can take weeks and can be refused.

---

## 3. First two weeks

**Before enabling the schedule**

1. Set all four secrets (see README). `POLLINATIONS_TOKEN` is not optional — the
   generated images *are* the video.
2. Put the real channel handle in `config.json` → `channel.url` and
   `seo.channel_url`.
3. Run **Actions → Krishna Universe Auto Reel → Run workflow → `selftest: true`**.
   Download the artifact. Confirm the Hindi text renders as Hindi, not as empty
   boxes. This is the one thing that cannot be verified from code.
4. Confirm the channel is **NOT** marked "Made for Kids" in
   **Studio → Settings → Channel → Advanced**. If it is, comments are disabled
   entirely — which kills the pinned-comment plan — and personalised ads are off,
   roughly halving RPM. Devotional kids-adjacent content sits right on this line.

**Daily, 30 seconds of work**

Paste and pin the suggested comment. `generate.py` prints it in the Actions log:

```
PIN THIS COMMENT on https://youtu.be/xxxx -> कमेंट में जय श्री कृष्ण लिखिए 🙏
```

This cannot be automated: the upload token only carries the `youtube.upload`
scope, and there is **no YouTube API to pin a comment at all**. Comment velocity
in the first hour is a strong distribution signal, and devotional audiences reply
to a direct ask more reliably than most niches.

**After 2 weeks**

```bash
python slot_report.py --shorts-only --detail
```

This reads the **real** publish hour off YouTube and groups views by slot. Two
things to use it for:

1. Cut or move the weakest slot — with data, not by eye.
2. Correct the 80-minute cron lead. It came from five samples on a different
   repo; GitHub's queue delay varies by time of day, so the real figure for these
   specific hours will differ.

Read the **median**, not the mean. One lucky video drags a mean anywhere.

---

## 4. Where reach actually comes from

Ranked by how much they move the number, most first:

1. **The first 2 seconds.** The screen hook (2-4 Hindi words) and the opening
   frame. Everything else is downstream of the swipe decision.
2. **Retention through the middle.** Cuts every ~1.6-2.6s, a different camera
   move per scene, real footage mixed in, and flash text for muted viewers.
3. **The thumbnail** — not for the Shorts player, but for the channel grid, the
   subscriptions feed and search. Those are the surfaces where someone who liked
   one video decides to subscribe.
4. **Title + first description line.** Only the opening ~100 characters show in
   search, which is why the first line carries a real Hindi search anchor.
5. **Hashtags.** Real, but the smallest of these five. Capped at 14 — above 15
   YouTube ignores every one of them.

Note the order. Hashtags are last. Adding thirty of them does not beat fixing the
first two seconds, and stuffing irrelevant "viral" tags actively hurts by sending
the video to an audience that swipes.

---

## 5. What is deliberately not built

**No analytics feedback loop.** Every pool is drawn uniformly at random (without
replacement). The pipeline cannot yet learn which hooks or leelas actually won.

The next meaningful upgrade is to pull per-video retention and CTR from the
YouTube Analytics API and weight the pools toward what performs. That needs a
read-only Analytics scope and about two weeks of data first — weighting on a
handful of videos would just amplify noise.

**No paid AI video.** The visuals are generated stills with a motion engine plus
real atmosphere footage. True text-to-video (Veo, Kling) would look better and
costs roughly $5-15 per 30-second Short — $750-2,000/month at 5/day, before any
revenue exists. A sensible upgrade path once monetised: spend it on the first
3 seconds only, where the swipe decision happens.
