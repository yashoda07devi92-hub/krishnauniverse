#!/usr/bin/env python3
"""
Structural sanity check for the GitHub Actions workflows.

WHY THIS EXISTS
---------------
A broken workflow file does not fail loudly - GitHub simply refuses to register
the schedule, and the channel quietly stops posting until somebody notices. The
usual guard is `yaml.safe_load`, but PyYAML is not always available (it is not a
dependency of this project), so this checks the things that actually break these
files in practice: tab characters, wrong step indentation, malformed block
scalars, and invalid cron expressions.

It also verifies the scheduling invariants this channel depends on: that the
cron minute values avoid :00 and :30 (when the Actions scheduler is most
congested), and that the IST publish time each cron implies is inside a real
India prime-time window.

Usage:
  python check_workflows.py
"""

import glob
import re
import sys

# cron UTC + this lead = publish time. Measured at ~78 min average across five
# consecutive scheduled runs; see the comment block in auto-reel.yml.
LEAD_MINUTES = 80
LONGFORM_LEAD_MINUTES = 118
IST_OFFSET_MINUTES = 5 * 60 + 30

# The windows the owner asked for: morning puja, lunch, and evening through
# late night.
IST_WINDOWS = [
    ("morning puja", 6 * 60, 9 * 60),
    ("lunch", 12 * 60, 15 * 60),
    ("evening/night", 18 * 60, 24 * 60),
]

CRON_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


class Check:
    def __init__(self):
        self.fails = []
        self.passes = 0

    def ok(self, cond, msg):
        if cond:
            self.passes += 1
        else:
            self.fails.append(msg)
        return cond

    def report(self):
        print("=" * 66)
        if self.fails:
            print(f"FAILED: {len(self.fails)} problem(s), {self.passes} checks passed")
            for f in self.fails:
                print("  x", f)
        else:
            print(f"PASSED: all {self.passes} workflow checks")
        print("=" * 66)
        return 1 if self.fails else 0


def check_cron_syntax(check, expr, where):
    fields = expr.split()
    if not check.ok(len(fields) == 5,
                    f"{where}: cron has {len(fields)} fields, need 5 -> {expr!r}"):
        return False
    for i, (field, (lo, hi)) in enumerate(zip(fields, CRON_RANGES)):
        for part in field.split(","):
            if part == "*":
                continue
            if re.fullmatch(r"\*/\d+", part):
                continue
            m = re.fullmatch(r"(\d+)(?:-(\d+))?(?:/\d+)?", part)
            if not check.ok(bool(m), f"{where}: unparseable cron field {part!r} in {expr!r}"):
                continue
            a = int(m.group(1))
            check.ok(lo <= a <= hi,
                     f"{where}: cron field {i} value {a} outside {lo}-{hi} in {expr!r}")
            if m.group(2):
                b = int(m.group(2))
                check.ok(lo <= b <= hi,
                         f"{where}: cron range end {b} outside {lo}-{hi} in {expr!r}")
    return True


def ist_publish(minute, hour, lead):
    """Minutes-since-midnight IST at which a cron at hour:minute UTC publishes."""
    return ((hour * 60 + minute) + lead + IST_OFFSET_MINUTES) % (24 * 60)


def fmt(mins):
    return "%02d:%02d" % (mins // 60, mins % 60)


def main():
    check = Check()
    files = sorted(glob.glob(".github/workflows/*.yml"))
    check.ok(bool(files), "no workflow files found")

    schedule_rows = []

    for path in files:
        text = open(path, encoding="utf-8").read()
        lines = text.split("\n")
        name = path.split("/")[-1]
        is_longform = "longform" in name

        check.ok("\t" not in text, f"{name}: contains a TAB (invalid in YAML)")
        check.ok(bool(lines) and lines[0].startswith("name:"),
                 f"{name}: does not start with a name: key")
        check.ok(re.search(r"^on:", text, re.M) is not None,
                 f"{name}: no top-level on: trigger")
        check.ok(re.search(r"^jobs:", text, re.M) is not None,
                 f"{name}: no top-level jobs:")

        # Step headers must sit at exactly 6 spaces or the step silently becomes
        # part of the previous one.
        for i, line in enumerate(lines, 1):
            if re.match(r"^\s*- name: ", line):
                indent = len(line) - len(line.lstrip())
                check.ok(indent == 6,
                         f"{name}:{i}: step '- name:' at indent {indent}, expected 6")

        # A block scalar whose body is not indented deeper is a parse error.
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)(?:run|if): \|", line)
            if not m:
                continue
            base = len(m.group(1))
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    continue
                nind = len(nxt) - len(nxt.lstrip())
                check.ok(nind > base,
                         f"{name}:{i+1}: block scalar body indented {nind} <= {base}")
                break

        for i, line in enumerate(lines, 1):
            m = re.search(r'-\s*cron:\s*["\']([^"\']+)["\']', line)
            if not m:
                continue
            expr = m.group(1)
            if not check_cron_syntax(check, expr, f"{name}:{i}"):
                continue
            minute_f, hour_f = expr.split()[0], expr.split()[1]
            if not minute_f.isdigit() or not hour_f.isdigit():
                continue
            minute, hour = int(minute_f), int(hour_f)

            # Congested minutes: the scheduler drops and delays runs worst here.
            check.ok(minute not in (0, 30),
                     f"{name}:{i}: cron minute is :{minute:02d} - avoid :00/:30 "
                     f"(worst Actions scheduler congestion)")

            lead = LONGFORM_LEAD_MINUTES if is_longform else LEAD_MINUTES
            pub = ist_publish(minute, hour, lead)
            window = next((w for w, lo, hi in IST_WINDOWS if lo <= pub < hi), None)
            check.ok(window is not None,
                     f"{name}:{i}: cron {expr!r} publishes at {fmt(pub)} IST, "
                     f"outside every India prime-time window")
            schedule_rows.append((name, expr, fmt(pub), window or "OUTSIDE"))

    # --- quota arithmetic -------------------------------------------------
    # videos.insert costs 1,600 units and thumbnails.set 50, against a 10,000/day
    # quota. The quota day resets at midnight PACIFIC (07:00 UTC), NOT UTC
    # midnight, which is the easy thing to get wrong: crons before 07:00 UTC
    # belong to the PREVIOUS quota day.
    UNITS_PER_UPLOAD = 1650
    QUOTA = 10000
    reel_crons = []
    lf_crons = []
    for nm, expr, _, _ in schedule_rows:
        h = expr.split()[1]
        dow = expr.split()[4]
        if not h.isdigit():
            continue
        (lf_crons if "longform" in nm else reel_crons).append((int(h), dow))

    # Count reels landing in one quota window (07:00 UTC -> 07:00 UTC next day).
    daily_reels = [c for c in reel_crons if c[1] == "*"]
    gated_reels = [c for c in reel_crons if c[1] != "*"]
    per_quota_day = len(daily_reels) + len(gated_reels)
    check.ok(per_quota_day * UNITS_PER_UPLOAD <= QUOTA,
             f"non-longform quota day uses {per_quota_day * UNITS_PER_UPLOAD} "
             f"units, over the {QUOTA} limit")
    longform_day = len(daily_reels) + len(lf_crons)
    check.ok(longform_day * UNITS_PER_UPLOAD <= QUOTA,
             f"longform quota day uses {longform_day * UNITS_PER_UPLOAD} units, "
             f"over the {QUOTA} limit")
    check.ok(longform_day * UNITS_PER_UPLOAD <= QUOTA - UNITS_PER_UPLOAD,
             f"longform quota day uses {longform_day * UNITS_PER_UPLOAD} units, "
             f"leaving no margin for a retry (need <= {QUOTA - UNITS_PER_UPLOAD})")

    print("=" * 66)
    print("SCHEDULE (cron UTC -> publish IST, lead already applied)")
    print("=" * 66)
    for nm, expr, pub, window in schedule_rows:
        print("  %-20s %-18s -> %s IST   %s" % (nm, expr, pub, window))
    print()
    print("  quota: normal day %d reels = %d units | longform day %d uploads = %d units"
          % (per_quota_day, per_quota_day * UNITS_PER_UPLOAD,
             longform_day, longform_day * UNITS_PER_UPLOAD))
    print("  (ceiling %d, videos.insert 1600 + thumbnails.set 50)" % QUOTA)
    print()
    return check.report()


if __name__ == "__main__":
    sys.exit(main())
