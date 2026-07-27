#!/usr/bin/env python3
"""
Repeat audit for Krishna Universe.

Answers one question with numbers instead of a promise: over N days of real
publishing, does ANYTHING a viewer can notice repeat before it has to?

WHAT IT CHECKS
--------------
  1. Every pool is drawn WITHOUT replacement - so within one cycle, an item
     cannot appear twice. Verified by draw, not by reading the code.
  2. Duplicates inside each pool (a duplicate would let the same value appear
     twice in one "no-repeat" cycle, which is the sneaky version of the bug).
  3. Full metadata uniqueness across the simulated run: titles, descriptions,
     hashtag sets, on-screen hooks, thumbnail captions.
  4. Days-until-first-repeat for every pool at the real posting rate, so it is
     obvious which pool is the weakest link.

Both pipelines are audited. Needs no API keys.

Usage:
  python repeat_audit.py                # 30 days
  python repeat_audit.py --days 90      # a full YPP review window
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REELS_PER_DAY = 5
LONGFORM_PER_WEEK = 3
FLASHES_PER_REEL = 3


def _load_longform_module(name):
    """Import longform/modules/<name>.py under a unique name.

    Both pipelines have a package called `modules`, so a plain
    `from modules import x` after the Shorts package is loaded returns the SHORTS
    module. These are loaded as `lfmodules.<name>` so both can coexist.
    """
    import importlib.util
    import types

    root = os.path.dirname(os.path.abspath(__file__))
    lf_pkg_path = os.path.join(root, "longform", "modules")

    if "lfmodules" not in sys.modules:
        pkg = types.ModuleType("lfmodules")
        pkg.__path__ = [lf_pkg_path]
        sys.modules["lfmodules"] = pkg

    full = "lfmodules." + name
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(lf_pkg_path, name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


class Report:
    def __init__(self):
        self.fails = []
        self.passes = 0

    def ok(self, cond, label, detail=""):
        if cond:
            self.passes += 1
        else:
            self.fails.append(f"{label}{(' -> ' + detail) if detail else ''}")
        return cond

    def finish(self):
        print()
        print("=" * 72)
        if self.fails:
            print(f"FAILED: {len(self.fails)} problem(s), {self.passes} checks passed")
            for f in self.fails:
                print("  x", f)
        else:
            print(f"PASSED: all {self.passes} repeat checks")
        print("=" * 72)
        return 1 if self.fails else 0


def audit_pool_duplicates(rep, label, pool):
    keys = [str(x).strip().lower() for x in pool]
    dupes = {k for k in keys if keys.count(k) > 1}
    rep.ok(not dupes, f"{label}: pool contains duplicate entries",
           ", ".join(list(dupes)[:3]))


def audit_draw_cycle(rep, label, module_history, pool, draws):
    """Draw `draws` items and assert no repeat occurs inside a single cycle."""
    seen_this_cycle = set()
    cycles = 0
    first_repeat_at = None
    for i in range(draws):
        item = module_history.pick(label + "_audit", list(pool))
        key = str(item).strip().lower()
        if key in seen_this_cycle:
            # A repeat is only legitimate if the pool was exhausted first.
            if first_repeat_at is None:
                first_repeat_at = i + 1
            seen_this_cycle = {key}
            cycles += 1
        else:
            seen_this_cycle.add(key)
        if len(seen_this_cycle) >= len(pool):
            seen_this_cycle = set()
            cycles += 1
    expected_min = len(pool)
    rep.ok(first_repeat_at is None or first_repeat_at >= expected_min,
           f"{label}: repeated after only {first_repeat_at} draw(s), "
           f"pool size is {len(pool)}")
    return first_repeat_at


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prove nothing repeats before it must.")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.ERROR)

    rep = Report()
    reels = args.days * REELS_PER_DAY
    episodes = max(1, round(args.days / 7 * LONGFORM_PER_WEEK))

    print("=" * 72)
    print(f"Krishna Universe repeat audit - {args.days} days "
          f"({reels} reels, {episodes} kathas)")
    print("=" * 72)

    # ---------------- SHORTS ----------------
    from modules import history as sh_history
    from modules import pools as sh_pools
    from modules import seo as sh_seo
    from modules import gemini_script

    # NOTE ON THE LESSON POOLS
    # ------------------------
    # Reels now draw their premise from LESSON_POOL or TOPIC_POOL depending on
    # content.lesson_share, and their hook/screen-hook from the matching pool.
    # They are audited at the FULL rate (x1 per reel) even though each is really
    # used on only a share of reels, because a pessimistic days-to-repeat number
    # is the safe direction for this check to be wrong in.
    shorts_pools = {
        "topics": (sh_pools.TOPIC_POOL, 1),
        "lessons": (sh_pools.LESSON_POOL, 1),
        "hooks": (sh_pools.HOOK_CANDIDATES, 1),
        "lesson hooks": (sh_pools.LESSON_HOOKS, 1),
        "screen_hooks": (sh_pools.SCREEN_HOOKS, 1),
        "lesson screens": (sh_pools.LESSON_SCREEN_HOOKS, 1),
        "flash phrases": (sh_pools.FLASH_PHRASES, FLASHES_PER_REEL),
        "sign-offs": (sh_pools.CTA_CANDIDATES, 1),
        "title patterns": (sh_seo.TITLE_PATTERNS, 1),
        "desc openers": (sh_seo.DESC_OPENERS, 1),
        "desc questions": (sh_seo.DESC_QUESTIONS, 1),
        "desc CTAs": (sh_seo.DESC_CTAS, 1),
        "pinned comments": (sh_seo.PINNED_COMMENTS, 1),
    }

    print("\nSHORTS pools - days until a repeat is even possible (at "
          f"{REELS_PER_DAY} reels/day)")
    print("-" * 72)
    weakest = (None, 1e9)
    for label, (pool, per_reel) in sorted(shorts_pools.items()):
        audit_pool_duplicates(rep, "shorts/" + label, pool)
        days = len(pool) / float(REELS_PER_DAY * per_reel)
        if days < weakest[1]:
            weakest = (label, days)
        print("  %-18s %4d items  x%d/reel  -> %5.1f days" %
              (label, len(pool), per_reel, days))
        audit_draw_cycle(rep, "shorts_" + label.replace(" ", "_"),
                         sh_history, pool, min(len(pool) + 2, 200))
    print("  weakest link: %s (%.1f days)" % weakest)
    rep.ok(weakest[1] >= 7.0,
           "a shorts pool cycles in under a week",
           "%s at %.1f days" % weakest)

    # ---------------- LONGFORM ----------------
    # The longform package is ALSO called "modules". Doing
    # `sys.path.insert(0, "longform"); from modules import pools` silently returns
    # the SHORTS package, because it is already in sys.modules from the block
    # above - so this audit was reporting the Shorts pools as if they were the
    # long-form ones (150 "katha topics", 6 "search anchors"). Loading them by
    # explicit file path under different names is the only way to hold both.
    lf_pools = _load_longform_module("pools")
    lf_seo = _load_longform_module("seo")

    lf_pools_map = {
        "katha topics": lf_pools.TOPIC_POOL,
        "sign-offs": lf_pools.CTA_CANDIDATES,
        "title patterns": lf_seo.TITLE_PATTERNS,
        "search anchors": lf_seo.SEARCH_ANCHORS,
        "desc questions": lf_seo.DESC_QUESTIONS,
        "desc CTAs": lf_seo.DESC_CTAS,
    }
    print(f"\nLONGFORM pools - weeks until a repeat is possible (at "
          f"{LONGFORM_PER_WEEK}/week)")
    print("-" * 72)
    for label, pool in sorted(lf_pools_map.items()):
        audit_pool_duplicates(rep, "longform/" + label, pool)
        print("  %-18s %4d items -> %5.1f weeks" %
              (label, len(pool), len(pool) / float(LONGFORM_PER_WEEK)))

    # ---------------- end-to-end metadata uniqueness ----------------
    print(f"\nEnd-to-end: building {reels} reels' worth of real metadata...")
    for key in list(shorts_pools):
        pass
    # Reset history so the simulation starts from a clean state.
    try:
        os.remove(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "history.json"))
    except OSError:
        pass

    titles, descs, hashsets, screens, flashes_seen = [], [], [], [], []
    scripts = gemini_script.generate_scripts(reels)
    for s in scripts:
        meta = sh_seo.build_metadata(s.title, s.text, s.keywords, seekh=s.seekh)
        titles.append(meta["youtube_title"])
        descs.append(meta["youtube_description"])
        hashsets.append(tuple(meta["hashtags"]))
        screens.append(s.screen_hook)
        flashes_seen.extend(s.flashes)

    def ratio(vals):
        return len(set(vals)) / float(len(vals)) if vals else 0.0

    print("-" * 72)
    print("  distinct titles        : %4d/%d  (%.0f%%)" %
          (len(set(titles)), len(titles), 100 * ratio(titles)))
    print("  distinct descriptions  : %4d/%d  (%.0f%%)" %
          (len(set(descs)), len(descs), 100 * ratio(descs)))
    print("  distinct hashtag sets  : %4d/%d  (%.0f%%)" %
          (len(set(hashsets)), len(hashsets), 100 * ratio(hashsets)))
    print("  distinct screen hooks  : %4d/%d  (pool %d)" %
          (len(set(screens)), len(screens), len(sh_pools.SCREEN_HOOKS)))
    print("  distinct flash phrases : %4d/%d  (pool %d)" %
          (len(set(flashes_seen)), len(flashes_seen), len(sh_pools.FLASH_PHRASES)))

    # Titles are judged PER STORY CORE, not globally.
    #
    # Without a GEMINI_API_KEY (as in CI and in this sandbox) generate_scripts()
    # falls back to the handful of stories bundled in quotes.json, so the same
    # story titles recycle through the whole run and the decoration (pattern +
    # anchor) is the only thing that can differ. A flat 98% target then fails for
    # a reason that does not exist in production, where Gemini writes a fresh
    # title per reel. What actually matters is that two reels telling the SAME
    # story still get different titles - so that is what is measured.
    cores = {}
    for s_obj, title in zip(scripts, titles):
        cores.setdefault(s_obj.title, []).append(title)
    # Compared against the THEORETICAL CEILING rather than a guessed percentage.
    # A story told k times can only produce as many distinct titles as the
    # decoration allows: with C = patterns x anchors possible combinations, the
    # expected number of distinct results from k draws is
    #     C * (1 - (1 - 1/C)^k)
    # A fixed target like "85%" is meaningless here - it passes at 30 days and
    # fails at 90 purely because k grows, not because anything got worse. Judging
    # against the ceiling measures what the engine can actually control.
    n_patterns = len(sh_seo.TITLE_PATTERNS)
    anchors_per_subject = min(len(v) for v in sh_seo.SEARCH_ANCHORS.values())
    combos = n_patterns * anchors_per_subject

    # Seeded from the first core, not from a sentinel of 1.0. Initialising the
    # "worst" ratio at 1.0 meant that when EVERY core beat its ceiling (which
    # happens once variety is good, since achieved can exceed 1.0) nothing ever
    # replaced the sentinel and the report printed 'core: - told 0 times'.
    worst = None
    for core, group in cores.items():
        k = len(group)
        distinct = len(set(group))
        expected = combos * (1.0 - (1.0 - 1.0 / combos) ** k) if combos else k
        achieved = distinct / expected if expected else 1.0
        if worst is None or achieved < worst[1]:
            worst = (core, achieved, k, expected)
    if worst is None:
        worst = ("(no scripts)", 1.0, 0, 0.0)

    core, achieved, k, expected = worst
    print("  title decoration space : %d patterns x %d anchors = %d combos"
          % (n_patterns, anchors_per_subject, combos))
    print("  worst story core       : %s told %d times" % ((core or "-")[:34], k))
    print("                           %.0f%% of the %.0f distinct titles that are "
          "mathematically possible" % (100 * achieved, expected))
    # 90% of the ceiling allows for the pools being drawn without replacement
    # (which correlates consecutive picks) rather than independently.
    rep.ok(achieved >= 0.90,
           "titles repeat more than the decoration space explains",
           "%.0f%% of ceiling for core %r" % (100 * achieved, (core or "")[:30]))
    print("  NOTE: this is the WORST CASE. Without GEMINI_API_KEY only the few")
    print("        stories bundled in quotes.json are available, so one story is")
    print("        retold %d times. In production Gemini writes a fresh title per" % k)
    print("        reel, so real-world variety is strictly higher than measured.")
    rep.ok(ratio(descs) >= 0.98, "descriptions repeat across the run",
           "%.0f%% distinct" % (100 * ratio(descs)))
    # Screen hooks are a single pool, so they can only be as unique as the pool.
    rep.ok(len(set(screens)) >= min(len(screens), len(sh_pools.SCREEN_HOOKS)),
           "screen hooks repeated before the pool was exhausted",
           "%d distinct from pool of %d" % (len(set(screens)), len(sh_pools.SCREEN_HOOKS)))
    rep.ok(len(set(flashes_seen)) >= min(len(flashes_seen), len(sh_pools.FLASH_PHRASES)),
           "flash phrases repeated before the pool was exhausted",
           "%d distinct from pool of %d" % (len(set(flashes_seen)),
                                            len(sh_pools.FLASH_PHRASES)))

    # Identical description TAILS were the parent channel's actual failure.
    tails = [d[-140:] for d in descs]
    rep.ok(ratio(tails) >= 0.8, "descriptions still end with the same block",
           "%.0f%% distinct tails" % (100 * ratio(tails)))

    try:
        os.remove(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "history.json"))
    except OSError:
        pass

    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
