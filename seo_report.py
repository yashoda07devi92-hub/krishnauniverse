#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEO self-check for Krishna Universe.

Generates N sample reels' worth of metadata WITHOUT touching the network, the
YouTube API or ffmpeg, and asserts the properties that actually matter. It exists
because the failure this pipeline was rebuilt to fix -- every video carrying an
identical title suffix, hashtag block and description -- is invisible in a single
sample. You only see it by generating a batch and comparing.

Checks per sample:
  * title is non-empty, within YouTube's limit, carries no legacy suffix
  * tags fit YouTube's ~500-character combined budget
  * hashtag count is right and every hashtag is well formed
  * description contains the lesson, a question, a sign-off and the hashtags
  * on-screen text (screen hook + flashes) BELONGS to the detected theme --
    catches the class of bug where a Govardhan reel flashed a Mathura name
  * theme detection agrees with what the title and keywords alone imply

Checks across the batch:
  * titles / descriptions / hashtag sets are distinct

Run:  python seo_report.py -n 40
Exit code is non-zero if any check fails, so it can gate CI.
"""

import argparse
import random
import re
import sys

sys.path.insert(0, ".")

from modules import gemini_script, history, pools, seo  # noqa: E402


PASS, FAIL = "PASS", "FAIL"


class Checker:
    def __init__(self):
        self.total = 0
        self.failures = []

    def check(self, ok, label, detail=""):
        self.total += 1
        if not ok:
            self.failures.append((label, detail))
        return ok

    def report(self):
        print("\n" + "=" * 72)
        if not self.failures:
            print("PASSED: all %d checks" % self.total)
            return 0
        print("FAILED: %d of %d checks" % (len(self.failures), self.total))
        for label, detail in self.failures:
            print("  - %-42s %s" % (label, detail))
        return 1


def _themed_vocab(theme):
    """Everything that is legitimately allowed on screen for this theme."""
    allowed = set(pools.SCREEN_GENERIC) | set(pools.FLASH_GENERIC)
    allowed |= set(pools.SCREEN_BY_THEME.get(theme, []))
    allowed |= set(pools.FLASH_BY_THEME.get(theme, []))
    return allowed


def run(n, seed=None):
    if seed is not None:
        random.seed(seed)
    ck = Checker()

    titles, descs, hashsets = [], [], []
    scripts = gemini_script.generate_scripts(n)

    for i, s in enumerate(scripts, 1):
        meta = seo.build_metadata(s.title, s.text, s.keywords, s.lesson)
        theme = meta["theme"]
        title = meta["youtube_title"]
        desc = meta["youtube_description"]
        tags = meta["youtube_tags"]
        hashtags = meta["hashtags"]

        ck.check(bool(title.strip()), "title non-empty [%d]" % i)
        ck.check(len(title) <= seo.TITLE_HARD_LIMIT,
                 "title <= %d chars [%d]" % (seo.TITLE_HARD_LIMIT, i),
                 "%d chars" % len(title))
        ck.check("Cute & Wholesome" not in title and "#" not in title,
                 "title has no legacy suffix / hashtags [%d]" % i, title)

        tag_chars = sum(len(t) for t in tags)
        ck.check(tag_chars <= seo.TAGS_CHAR_BUDGET,
                 "tags within char budget [%d]" % i, "%d chars" % tag_chars)
        ck.check(len(tags) >= 8, "enough tags [%d]" % i, "%d tags" % len(tags))
        ck.check(all(len(t) <= seo.TAG_MAX_LEN for t in tags),
                 "no overlong tag [%d]" % i)

        ck.check(len(hashtags) >= 6, "enough hashtags [%d]" % i, str(len(hashtags)))
        ck.check(all(re.match(r"^#\S+$", h) for h in hashtags),
                 "hashtags well formed [%d]" % i, " ".join(hashtags))
        ck.check("#shorts" in hashtags, "#shorts present [%d]" % i)

        ck.check(len(desc) > 200, "description substantial [%d]" % i, "%d chars" % len(desc))
        ck.check(desc.count("\n\n") >= 4, "description has structure [%d]" % i)
        if s.lesson:
            ck.check("सीख:" in desc, "lesson line in description [%d]" % i)
        ck.check(hashtags[0] in desc, "hashtags in description [%d]" % i)
        # The whole narration must NOT be pasted in: that was the old behaviour
        # and it duplicated the audio as text on every single video.
        ck.check(s.text not in desc, "narration not dumped into description [%d]" % i)

        # On-screen text must belong to this story's theme.
        allowed = _themed_vocab(theme)
        ck.check(s.screen_hook in allowed,
                 "screen hook fits theme '%s' [%d]" % (theme, i), s.screen_hook)
        for f in s.flashes:
            ck.check(f in allowed,
                     "flash fits theme '%s' [%d]" % (theme, i), f)

        # Theme must be derivable from title+keywords alone, not only from the
        # randomly drawn hook sentence.
        theme_from_meta = seo.detect_leela(s.title, "", s.keywords, s.lesson)
        ck.check(theme_from_meta == theme or theme_from_meta == seo.DEFAULT_THEME,
                 "theme stable without body text [%d]" % i,
                 "%s vs %s" % (theme_from_meta, theme))

        titles.append(title)
        descs.append(desc)
        hashsets.append(" ".join(hashtags))

        if n <= 8:
            print("\n--- sample %d -------------------------------------------" % i)
            print("theme      :", theme)
            print("title      :", title, "(%d)" % len(title))
            print("screen hook:", s.screen_hook)
            print("flashes    :", " / ".join(s.flashes))
            print("hashtags   :", " ".join(hashtags))
            print("tags       : %d tags, %d chars" % (len(tags), tag_chars))
            print("scenes     :", len(s.scene_prompts))
            print("description:")
            for line in desc.split("\n"):
                if line.strip():
                    print("   ", line[:100])

    # Batch-level distinctness: this is the check that would have caught the
    # original problem, where all 113 uploads shared one metadata fingerprint.
    for label, values in (("titles", titles), ("descriptions", descs),
                          ("hashtag sets", hashsets)):
        distinct = len(set(values))
        ck.check(distinct == len(values), "all %s distinct" % label,
                 "%d distinct of %d" % (distinct, len(values)))

    print("\n%d samples: %d/%d distinct titles, %d/%d distinct descriptions, "
          "%d/%d distinct hashtag sets"
          % (n, len(set(titles)), n, len(set(descs)), n, len(set(hashsets)), n))

    # Never let a self-check consume the real no-repeat rotation.
    history.discard()
    return ck.report()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Krishna Universe SEO self-check")
    ap.add_argument("-n", "--samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    return run(max(1, args.samples), args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
