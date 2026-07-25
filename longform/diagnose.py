#!/usr/bin/env python3
"""
Quick secret/source diagnostic for Krishna Universe Katha.

Checks (WITHOUT making a video) whether the required API keys and YouTube
credentials are present and look usable, so a scheduled run can be debugged
fast. Exits 0 always (it is a report, not a gate) but prints a clear summary.
"""

import json
import logging
import os

from modules.config import setup_logging, get_env

log = logging.getLogger("krishna.diagnose")


def _status(name, present, detail=""):
    mark = "OK  " if present else "MISS"
    print(f"  [{mark}] {name}{(' - ' + detail) if detail else ''}")
    return present


def main():
    setup_logging()
    print("\n=== Krishna Universe Katha diagnostic ===\n")

    gemini = get_env("GEMINI_API_KEY")
    pexels = get_env("PEXELS_API_KEY")
    yt_secret = get_env("YT_CLIENT_SECRET_JSON")
    yt_token = get_env("YT_TOKEN_JSON")

    _status("GEMINI_API_KEY", bool(gemini),
            "story uses Gemini" if gemini else "will use stories.json fallback")
    _status("PEXELS_API_KEY", bool(pexels),
            "real HD footage" if pexels else "will use gradient fallback")

    secret_ok = False
    if yt_secret:
        try:
            json.loads(yt_secret)
            secret_ok = True
        except Exception:
            pass
    _status("YT_CLIENT_SECRET_JSON", secret_ok,
            "valid JSON" if secret_ok else "missing/invalid JSON")

    token_ok = False
    if yt_token:
        try:
            json.loads(yt_token)
            token_ok = True
        except Exception:
            pass
    _status("YT_TOKEN_JSON", token_ok,
            "valid JSON" if token_ok else "missing/invalid JSON")

    print("\nSummary:")
    print("  - Video can be generated:", "YES" if True else "NO",
          "(Gemini optional; stories.json fallback always works)")
    print("  - Upload to YouTube possible:", "YES" if (secret_ok and token_ok) else "NO")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
