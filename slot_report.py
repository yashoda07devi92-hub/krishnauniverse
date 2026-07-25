#!/usr/bin/env python3
"""
Which upload slot is actually working? Answer it with data, not guesses.

The reel workflow posts at 4 fixed times a day, and a 5th slot was removed at
some point because it "got almost no views". That decision was made by eye. This
script reads the real numbers off the channel and groups every published video by
the hour it went live (in US Eastern, since that is the target audience), so the
slots can be compared properly.

It also splits Shorts from long-form, because they are distributed completely
differently and averaging them together hides the answer.

WHAT IT PRINTS
--------------
  * views per publish-hour slot: count, median, mean, best
  * the same broken down by weekday vs weekend
  * the individual videos behind each slot, so an outlier is visible

Median matters more than mean here: one lucky video at 40,000 views will drag a
mean upward and make a dead slot look healthy.

SCOPE
-----
Reading your own channel's stats needs more than the upload scope. Reuse the
token minted for retitle_existing.py:

    python retitle_existing.py --authorize     # if you have not already

USAGE
-----
    python slot_report.py                  # all videos
    python slot_report.py --shorts-only
    python slot_report.py --max 200 --detail
"""

import argparse
import logging
import os
import statistics
import sys
from datetime import datetime, timezone

from modules.config import setup_logging

# Reuse the auth + fetch helpers rather than duplicating them.
import retitle_existing as manage

log = logging.getLogger("krishna.slots")

TARGET_TZ = "America/New_York"  # the audience the channel is written for

# YouTube treats a video as a Short based on aspect ratio and length; the API
# does not expose a clean flag, so duration is used as the practical proxy.
SHORT_MAX_SECONDS = 180


def _target_zone():
    """US Eastern with correct DST handling, falling back to a fixed offset."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(TARGET_TZ)
    except Exception as exc:
        log.warning("zoneinfo unavailable (%s); falling back to fixed UTC-4.", exc)
        from datetime import timedelta

        return timezone(timedelta(hours=-4))


def _parse_iso(value):
    """Parse the RFC-3339 timestamps the YouTube API returns."""
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _parse_duration(iso):
    """ISO-8601 duration (PT1M23S) -> seconds. Returns None if unparseable."""
    if not iso or not iso.startswith("PT"):
        return None
    total, number = 0, ""
    for ch in iso[2:]:
        if ch.isdigit():
            number += ch
        elif ch in "HMS" and number:
            total += int(number) * {"H": 3600, "M": 60, "S": 1}[ch]
            number = ""
        else:
            number = ""
    return total or None


def fetch_all(youtube, max_items):
    playlist_id = manage._uploads_playlist_id(youtube)
    if not playlist_id:
        return []
    ids = manage._list_video_ids(youtube, playlist_id, max_items=max_items)
    rows = []
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(chunk)
        ).execute()
        rows.extend(resp.get("items", []))
    return rows


def summarise(videos, zone, shorts_only=False, longform_only=False):
    buckets = {}
    skipped = 0
    for v in videos:
        published = _parse_iso(v.get("snippet", {}).get("publishedAt"))
        seconds = _parse_duration(v.get("contentDetails", {}).get("duration"))
        try:
            views = int(v.get("statistics", {}).get("viewCount", 0))
        except Exception:
            views = 0
        if published is None:
            skipped += 1
            continue

        is_short = seconds is not None and seconds <= SHORT_MAX_SECONDS
        if shorts_only and not is_short:
            continue
        if longform_only and is_short:
            continue

        local = published.astimezone(zone)
        key = local.hour
        buckets.setdefault(key, []).append({
            "views": views,
            "title": v["snippet"].get("title", ""),
            "id": v["id"],
            "when": local,
            "weekend": local.weekday() >= 5,
            "seconds": seconds,
        })
    if skipped:
        log.warning("%d video(s) had no parseable publish time.", skipped)
    return buckets


def _stats(views):
    return {
        "n": len(views),
        "median": int(statistics.median(views)) if views else 0,
        "mean": int(statistics.fmean(views)) if views else 0,
        "best": max(views) if views else 0,
        "worst": min(views) if views else 0,
    }


def print_report(buckets, detail=False):
    if not buckets:
        print("No videos matched the filter.")
        return

    all_views = [item["views"] for items in buckets.values() for item in items]
    overall = _stats(all_views)

    print()
    print("=" * 78)
    print(f"{'Publish hour (US Eastern)':<28}{'videos':>7}{'median':>9}{'mean':>9}{'best':>9}{'vs all':>10}")
    print("-" * 78)
    for hour in sorted(buckets):
        items = buckets[hour]
        s = _stats([i["views"] for i in items])
        delta = (s["median"] / overall["median"] - 1) * 100 if overall["median"] else 0
        label = f"{hour:02d}:00 - {hour:02d}:59"
        print(f"{label:<28}{s['n']:>7}{s['median']:>9}{s['mean']:>9}{s['best']:>9}{delta:>9.0f}%")
    print("-" * 78)
    print(f"{'ALL SLOTS':<28}{overall['n']:>7}{overall['median']:>9}{overall['mean']:>9}{overall['best']:>9}")
    print("=" * 78)

    # Weekday vs weekend, because a slot can be strong on one and dead on the other.
    weekday = [i["views"] for items in buckets.values() for i in items if not i["weekend"]]
    weekend = [i["views"] for items in buckets.values() for i in items if i["weekend"]]
    if weekday and weekend:
        wd, we = _stats(weekday), _stats(weekend)
        print()
        print(f"Weekday : {wd['n']:>4} videos, median {wd['median']}")
        print(f"Weekend : {we['n']:>4} videos, median {we['median']}")

    print()
    print("How to read this:")
    print("  * MEDIAN is the number to trust. One lucky video inflates the mean and")
    print("    can make a dead slot look healthy.")
    print("  * A slot needs at least ~8-10 videos before its median means anything.")
    print("  * Publish hour is when the video went PUBLIC, which is the cron time")
    print("    PLUS the GitHub Actions queue delay PLUS the render time - usually")
    print("    30-45 minutes later than the cron suggests.")

    if detail:
        for hour in sorted(buckets):
            print()
            print(f"--- {hour:02d}:00 ET " + "-" * 55)
            for item in sorted(buckets[hour], key=lambda x: -x["views"]):
                kind = "short" if (item["seconds"] or 0) <= SHORT_MAX_SECONDS else "long "
                print(f"  {item['views']:>7} views  {kind}  "
                      f"{item['when']:%Y-%m-%d %a %H:%M}  {item['title'][:44]}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare view performance by upload slot."
    )
    parser.add_argument("--max", type=int, default=200, help="How many recent videos to pull.")
    parser.add_argument("--shorts-only", action="store_true", help="Only videos <= 3 minutes.")
    parser.add_argument("--longform-only", action="store_true", help="Only videos > 3 minutes.")
    parser.add_argument("--detail", action="store_true", help="List the videos behind each slot.")
    args = parser.parse_args(argv)

    setup_logging()
    from googleapiclient.discovery import build

    creds = manage._credentials()
    if creds is None:
        return 1
    youtube = build("youtube", "v3", credentials=creds)

    videos = fetch_all(youtube, args.max)
    log.info("Fetched %d video(s).", len(videos))

    zone = _target_zone()
    buckets = summarise(
        videos, zone,
        shorts_only=args.shorts_only,
        longform_only=args.longform_only,
    )
    print_report(buckets, detail=args.detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
