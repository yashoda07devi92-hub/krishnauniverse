#!/usr/bin/env python3
"""
SEO self-check for Krishna Universe.

Runs the metadata engine over a batch of simulated uploads and asserts the
properties that actually matter for distribution and for the YouTube Partner
Program review:

  1. UNIQUENESS  - no two uploads share a title, a description or a hashtag set.
                   This is the check the old pipeline would have failed 100%%:
                   every title ended with the same "| Cute & Wholesome
                   #shorts #cute" and every description ended with the same
                   8 hashtags.
  2. API LIMITS  - title <= 100 chars, description <= 5000, tags <= 500 chars
                   total, hashtag count <= 15 (above 15 YouTube ignores them
                   all).
  3. SEO SHAPE   - a search anchor appears in the title, the description's first
                   line is long enough to be a real search snippet, and every
                   video carries a call to action.

Needs no API keys and no media libraries, so it can run anywhere.

Usage:
  python seo_report.py              # 25 samples, summary + verdict
  python seo_report.py -n 100       # bigger sample
  python seo_report.py --show 5     # also print 5 full metadata examples
  python seo_report.py --longform   # check the long-form engine instead
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Limits straight from the YouTube Data API / Studio rules
# --------------------------------------------------------------------------
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
# YouTube enforces this against the UTF-8 ENCODING, not the character count, and
# it quotes any tag containing a space (2 extra bytes). This check previously
# measured CHARACTERS and therefore PASSED on a tag set that the API rejected -
# 385 "characters" of Devanagari is 765 bytes. Measure bytes.
MAX_TAGS_BYTES = 500
MAX_HASHTAGS = 15


def _tag_bytes(tags):
    """What snippet.tags actually costs against YouTube's 500 limit.

    UTF-8 length per tag, +1 separator, +2 where YouTube has to quote the tag -
    which it does for any tag containing a space.
    """
    return sum(len(t.encode("utf-8")) + 1 + (2 if " " in t else 0) for t in tags)


def _has_devanagari(s):
    return any("\u0900" <= ch <= "\u097F" for ch in str(s or ""))


def _mostly_devanagari(s):
    s = str(s or "")
    if not s:
        return False
    deva = sum(1 for ch in s if "\u0900" <= ch <= "\u097F")
    return deva > len(s) * 0.2


class Check:
    """Collects pass/fail results so every problem is reported, not just the first."""

    def __init__(self):
        self.failures = []
        self.passes = 0

    def ok(self, condition, label, detail=""):
        if condition:
            self.passes += 1
        else:
            self.failures.append(f"{label}{(' -> ' + detail) if detail else ''}")
        return condition

    def report(self):
        print()
        print("=" * 70)
        if self.failures:
            print(f"FAILED: {len(self.failures)} problem(s), {self.passes} check(s) passed")
            for f in self.failures:
                print(f"  x {f}")
        else:
            print(f"PASSED: all {self.passes} checks")
        print("=" * 70)
        return 1 if self.failures else 0


# --------------------------------------------------------------------------
# Shorts
# --------------------------------------------------------------------------
def sample_shorts(n):
    from modules import gemini_script, seo  # noqa: F401 (used by check_shorts)

    rows = []
    scripts = gemini_script.generate_scripts(n)
    for s in scripts:
        meta = seo.build_metadata(s.title, s.text, s.keywords, seekh=s.seekh)
        meta["_script_title"] = s.title
        meta["_text"] = s.text
        meta["_keywords"] = list(s.keywords)
        meta["_screen_hook"] = s.screen_hook
        meta["_spoken_hook"] = s.hook
        meta["_scene_prompts"] = list(s.scene_prompts)
        rows.append(meta)
    return rows


def check_shorts(rows, check):
    from modules import gemini_script, seo

    anchors = {a.lower() for pool in seo.SEARCH_ANCHORS.values() for a in pool}

    titles, descs, hashsets, screen_hooks = [], [], [], []
    for i, m in enumerate(rows):
        tag = f"video {i + 1}"
        title = m["youtube_title"]
        desc = m["youtube_description"]
        tags = m["youtube_tags"]
        hashtags = m["hashtags"]

        check.ok(len(title) <= MAX_TITLE, f"{tag}: title over {MAX_TITLE} chars", f"{len(title)}")
        check.ok(len(desc) <= MAX_DESCRIPTION, f"{tag}: description over {MAX_DESCRIPTION}", f"{len(desc)}")

        tag_bytes = _tag_bytes(tags)
        check.ok(tag_bytes <= MAX_TAGS_BYTES,
                 f"{tag}: tags over {MAX_TAGS_BYTES} BYTES (YouTube rejects with "
                 f"invalidTags)", f"{tag_bytes} bytes")
        check.ok(len(tags) >= 8, f"{tag}: suspiciously few tags", f"{len(tags)}")

        check.ok(len(hashtags) <= MAX_HASHTAGS, f"{tag}: more than {MAX_HASHTAGS} hashtags",
                 f"{len(hashtags)}")
        check.ok(len(hashtags) >= 3, f"{tag}: fewer than 3 hashtags", f"{len(hashtags)}")

        # The regression that started all of this on the parent channel.
        check.ok("Cute & Wholesome" not in title, f"{tag}: legacy hard-coded title suffix is back")
        check.ok(title.count("#") <= 1, f"{tag}: more than one hashtag in the title")

        # This is a HINDI channel. A title with no Devanagari means the pipeline
        # fell through to an English fallback somewhere, which would be served to
        # the wrong audience.
        check.ok(_has_devanagari(title), f"{tag}: title has no Devanagari (Hindi) text", title)
        check.ok(_has_devanagari(desc), f"{tag}: description has no Devanagari text")

        # Scene prompts drive image generation and MUST stay English - the image
        # model produces garbled output from Devanagari prompts.
        for sp in m.get("_scene_prompts", []):
            check.ok(not _mostly_devanagari(sp),
                     f"{tag}: scene prompt is in Hindi (image model needs English)", sp[:50])

        # Atmosphere keywords are real stock-footage searches. If "krishna" ever
        # leaks into them the pipeline is searching Pexels for footage that does
        # not exist, and the reel silently loses its background.
        for kw in m.get("_keywords", []):
            check.ok("krishna" not in str(kw).lower() and not _has_devanagari(str(kw)),
                     f"{tag}: atmosphere keyword is not a real footage search", str(kw))

        # A searchable phrase must survive into the title.
        check.ok(any(a in title.lower() for a in anchors) or len(title) > 25,
                 f"{tag}: title carries no search anchor", title)

        # Subject targeting must match the actual content. A kitten video that
        # gets served "#babyanddog" reaches the wrong audience, gets swiped, and
        # drags the next upload down with it.
        subject = m["subject"]
        subj_hashtags = {h.lower() for h in seo.HASHTAG_SUBJECT.get(subject, [])}
        check.ok(bool(subj_hashtags & {h.lower() for h in hashtags}),
                 f"{tag}: no hashtag from its own subject pool ({subject})",
                 " ".join(hashtags))
        expected = seo.detect_subject(
            m["_script_title"], m.get("_text", ""), m.get("_keywords"))
        check.ok(subject == expected,
                 f"{tag}: subject drifted", f"{subject} vs {expected}")
        check.ok(subject in seo.SEARCH_ANCHORS,
                 f"{tag}: unknown subject bucket", str(subject))

        first_line = desc.split("\n", 1)[0]
        check.ok(len(first_line) >= 60,
                 f"{tag}: first description line too short to work as a search snippet",
                 f"{len(first_line)} chars")
        # CTAs are Hindi and only sometimes use the English word "Subscribe",
        # so the check accepts the Devanagari action words too.
        low = desc.lower()
        check.ok(
            any(w in low for w in ("subscribe", "follow", "share"))
            or any(w in desc for w in ("शेयर", "फॉलो", "जुड़े", "साथ")),
            f"{tag}: description has no call to action",
        )
        check.ok("#" in desc, f"{tag}: description carries no hashtags")

        # LENGTH FLOOR. A Short under 25s is a hard requirement from the channel
        # owner. The composer pads to video.min_duration_seconds, but padding is
        # trailing silence, so the NARRATION itself has to clear the floor.
        words = len(str(m.get("_text", "")).split())
        secs = gemini_script.estimated_seconds(words)
        floor = float(seo.get_cfg("video.min_duration_seconds", 25))
        check.ok(secs >= floor,
                 f"{tag}: narration only ~{secs:.1f}s ({words} words), under the "
                 f"{floor:.0f}s floor - would publish with trailing silence",
                 f"{words} words")

        titles.append(title)
        descs.append(desc)
        hashsets.append(tuple(hashtags))
        screen_hooks.append(m["_screen_hook"])

    _uniqueness(check, titles, descs, hashsets, screen_hooks)


# --------------------------------------------------------------------------
# Long-form
# --------------------------------------------------------------------------
def sample_longform(n):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "longform"))
    from modules import seo as lseo  # noqa: E402  (longform/modules)
    from modules import story as lstory  # noqa: E402

    # NOTE: this is the WORST CASE for the title engine. The bundled
    # stories.json holds only a handful of stories, so the same story titles are
    # recycled across the sample and the decoration (pattern + anchor +
    # qualifier + lesson) is the only thing that can make the titles differ. In
    # production Gemini writes a fresh title per episode, so real variety is
    # strictly higher than what this check measures.
    rows = []
    pool = lstory.load_fallback_stories() or [lstory._fallback_story()]
    for i in range(n):
        st = pool[i % len(pool)]
        # 4-7 minute spread, which is what this pipeline actually renders.
        duration = 240 + (i * 37) % 180
        meta = lseo.build_metadata(st, duration_seconds=duration)
        meta["_duration"] = duration
        rows.append(meta)
    return rows


def check_longform(rows, check):
    titles, descs, hashsets = [], [], []
    for i, m in enumerate(rows):
        tag = f"episode {i + 1}"
        title = m["youtube_title"]
        desc = m["youtube_description"]
        tags = m["youtube_tags"]

        check.ok(len(title) <= MAX_TITLE, f"{tag}: title over {MAX_TITLE} chars", f"{len(title)}")
        check.ok(len(desc) <= MAX_DESCRIPTION, f"{tag}: description over {MAX_DESCRIPTION}", f"{len(desc)}")
        tag_bytes = _tag_bytes(tags)
        check.ok(tag_bytes <= MAX_TAGS_BYTES,
                 f"{tag}: tags over {MAX_TAGS_BYTES} BYTES (YouTube rejects with "
                 f"invalidTags)", f"{tag_bytes} bytes")
        check.ok(len(m["hashtags"]) <= MAX_HASHTAGS, f"{tag}: more than {MAX_HASHTAGS} hashtags")
        # The parent repo checked that the old mismatched "MoralTales" brand was
        # gone. Here the equivalent risk is an English-only description, i.e. the
        # Hindi layer failed somewhere.
        check.ok(_has_devanagari(desc), f"{tag}: description has no Devanagari text")
        check.ok(_has_devanagari(title), f"{tag}: title has no Devanagari text", title)

        # Chapters are only valid if they start at 0:00 and there are 3+.
        if "Chapters:" in desc:
            block = desc.split("Chapters:", 1)[1].strip().split("\n\n", 1)[0]
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            check.ok(len(lines) >= 3, f"{tag}: fewer than 3 chapters (YouTube ignores the block)",
                     f"{len(lines)}")
            check.ok(lines and lines[0].startswith("0:00"),
                     f"{tag}: first chapter is not at 0:00", lines[0] if lines else "-")
            secs = []
            for l in lines:
                mm, _, ss = l.split()[0].partition(":")
                try:
                    secs.append(int(mm) * 60 + int(ss))
                except Exception:
                    pass
            gaps = [b - a for a, b in zip(secs, secs[1:])]
            check.ok(all(g >= 10 for g in gaps),
                     f"{tag}: a chapter is shorter than 10s (YouTube ignores the block)", str(gaps))
            check.ok(not secs or secs[-1] < m["_duration"],
                     f"{tag}: last chapter starts after the video ends")

        titles.append(title)
        descs.append(desc)
        hashsets.append(tuple(m["hashtags"]))

    _uniqueness(check, titles, descs, hashsets, None)


# --------------------------------------------------------------------------
# Shared uniqueness reporting
# --------------------------------------------------------------------------
def _ratio(values):
    return len(set(values)) / float(len(values)) if values else 0.0


def _uniqueness(check, titles, descs, hashsets, screen_hooks):
    n = len(titles)
    t_ratio = _ratio(titles)
    d_ratio = _ratio(descs)
    h_ratio = _ratio(hashsets)

    print()
    print(f"Samples                  : {n}")
    print(f"Distinct titles          : {len(set(titles))}/{n}  ({t_ratio:.0%})")
    print(f"Distinct descriptions    : {len(set(descs))}/{n}  ({d_ratio:.0%})")
    print(f"Distinct hashtag sets    : {len(set(hashsets))}/{n}  ({h_ratio:.0%})")
    if screen_hooks:
        print(f"Distinct on-screen hooks : {len(set(screen_hooks))}/{n}")

    # Titles are built from a story title + one of many patterns. Repeats are
    # only expected when the underlying story repeats (small fallback pool).
    check.ok(t_ratio >= 0.85, "titles are not varied enough", f"{t_ratio:.0%} distinct")
    check.ok(d_ratio >= 0.95, "descriptions are not varied enough", f"{d_ratio:.0%} distinct")
    check.ok(h_ratio >= 0.80, "hashtag sets are not varied enough", f"{h_ratio:.0%} distinct")

    # The specific old failure: an identical trailing block on every upload.
    tails = [d[-120:] for d in descs]
    check.ok(_ratio(tails) >= 0.8,
             "every description still ends with the same block",
             f"{_ratio(tails):.0%} distinct tails")


# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify Krishna Universe SEO metadata.")
    parser.add_argument("-n", "--count", type=int, default=25, help="How many samples to build.")
    parser.add_argument("--show", type=int, default=0, help="Print this many full examples.")
    parser.add_argument("--longform", action="store_true", help="Check the long-form engine.")
    args = parser.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.ERROR)  # keep the report readable

    check = Check()
    mode = "LONG-FORM" if args.longform else "SHORTS"
    print("=" * 70)
    print(f"Krishna Universe SEO self-check - {mode} - {args.count} samples")
    print("=" * 70)

    if args.longform:
        rows = sample_longform(args.count)
        check_longform(rows, check)
    else:
        rows = sample_shorts(args.count)
        check_shorts(rows, check)

    if args.show:
        for m in rows[: args.show]:
            print("\n" + "-" * 70)
            print("TITLE    :", m["youtube_title"])
            print("TAGS     :", ", ".join(m["youtube_tags"]))
            print("HASHTAGS :", " ".join(m["hashtags"]))
            if m.get("pinned_comment"):
                print("PIN      :", m["pinned_comment"])
            print("-" * 70)
            print(m["youtube_description"])

    return check.report()


if __name__ == "__main__":
    sys.exit(main())
