---
inclusion: always
---

# Krishna Universe conventions

## Language and text rendering
- Narration, titles, descriptions, hooks and flashes are **Hindi (Devanagari)**.
  Tags carry both Devanagari and Latin script, because real users search both.
- `scene_prompts` (for the image model) and Pexels keywords stay **English** —
  they are machine inputs, not viewer-facing.
- NEVER render on-screen text with moviepy `TextClip`. DejaVu has no Devanagari
  glyphs and ImageMagick's `label:`/`caption:` does no shaping, and both fail
  silently. Use `modules/textrender.py`.
- Any workflow that renders video must install `fonts-noto-devanagari`.

## No repeats
- Every user-visible pool goes through `modules/history.py` (`pick` → `commit` on
  success, `discard` on failure). Never `random.choice` on a pool that a viewer
  will see across videos.
- `history.commit()` only after the artefact actually exists, so a failed run
  does not burn the rotation.
- On-screen phrases must match the story's theme. Generic phrases live in
  `SCREEN_GENERIC` / `FLASH_GENERIC`; anything naming a person or place lives
  under its theme in `SCREEN_BY_THEME` / `FLASH_BY_THEME`.

## Visuals
- Generated frames are the primary source; real Pexels footage is **atmosphere
  cutaways only**, never people.
- Do not fall back to a plain still slideshow. Every frame gets a camera move
  from `_MOVES`. Pans/tilts/drifts run at constant scale (no per-frame resample);
  zooms are expensive, so keep them a minority in `_MOVE_WEIGHTS`.

## Captions
- `captions.enabled` stays **false**. A rolling subtitle track covers the
  artwork. Mid-video flash phrases replace it. Do not re-enable without looking
  at a rendered reel.

## Scheduling
- Reason in **IST**; there is no DST, so cron does not drift.
- Cron fires ~80 minutes before the intended publish time (measured queue lead).
  Do not shorten it without re-measuring via `slot_report.py`.
- Avoid `:00` and `:30` minute values — the Actions scheduler is most congested
  then and runs are delayed or dropped.
- Respect the 6-upload/day YouTube quota ceiling and remember the quota day
  resets at **07:00 UTC**, not UTC midnight.

## Verification
- `python seo_report.py -n 40` and `python modules/pools.py` must both pass
  before pushing metadata or pool changes.
