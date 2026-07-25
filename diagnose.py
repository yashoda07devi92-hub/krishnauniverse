#!/usr/bin/env python3
"""
Krishna Universe - FAST health diagnostic (no video render).

Checks whether the runtime SECRETS actually work, so we know BEFORE spending
~15 minutes on a full reel render whether:
  * PEXELS_API_KEY returns real HD portrait footage  (else background = plain
    gradient, which is the usual cause of "every video looks the same/boring"),
  * GEMINI_API_KEY can generate a script (else the local quotes.json fallback
    is used - still fine, just not AI-written),
  * the YouTube secrets are present.

Run it from the "Diagnose Secrets" GitHub Action (workflow_dispatch). It prints
a clear PASS/FAIL summary in the run log. It installs only `requests` and
`google-generativeai`, so it finishes in well under a minute.
"""

import json
import os
import sys

# Reuse the project's env helper (filters blank/placeholder values).
try:
    from modules.config import get_env
except Exception:
    def get_env(name, default=None):
        v = os.environ.get(name)
        return v.strip() if v and v.strip() else default


LINE = "=" * 64


def _best_portrait_resolution(video_files):
    """Return (w, h, needs_upscale) for the best rendition to fill 1080x1920."""
    best = None
    best_score = float("-inf")
    for vf in video_files or []:
        w = vf.get("width") or 0
        h = vf.get("height") or 0
        if w <= 0 or h <= 0:
            continue
        scale = max(1080.0 / w, 1920.0 / h)
        upscale_penalty = 0.0 if scale <= 1.0 else (scale - 1.0) * 1_000_000.0
        res_reward = min(w * h, 4096 * 4096) / 1_000_000.0
        portrait_reward = 30.0 if h >= w else 0.0
        score = res_reward + portrait_reward - upscale_penalty
        if score > best_score:
            best_score = score
            best = (w, h, scale > 1.0)
    return best


def check_pexels():
    print(LINE)
    print("1) PEXELS  (decides the VIDEO BACKGROUND)")
    print(LINE)
    key = get_env("PEXELS_API_KEY")
    if not key:
        print("  RESULT: ❌ PEXELS_API_KEY is NOT set (or is a placeholder).")
        print("  EFFECT: No real footage -> every reel uses a PLAIN GRADIENT.")
        return False
    print(f"  Key detected (length {len(key)}). Testing a live search...")
    try:
        import requests
    except Exception as exc:
        print(f"  RESULT: ⚠️ could not import requests ({exc}).")
        return False
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": "puppies playing", "per_page": 5, "orientation": "portrait"},
            timeout=30,
        )
    except Exception as exc:
        print(f"  RESULT: ⚠️ network error contacting Pexels ({exc}).")
        return False

    print(f"  HTTP status: {resp.status_code} {getattr(resp, 'reason', '')}")
    if resp.status_code in (401, 403):
        print("  RESULT: ❌ KEY INVALID/FORBIDDEN. Pexels is rejecting the key.")
        print("  FIX: regenerate PEXELS_API_KEY at pexels.com/api and update the")
        print("       GitHub Secret named PEXELS_API_KEY (no quotes, no spaces).")
        try:
            print("  Body:", resp.text[:200])
        except Exception:
            pass
        return False
    if resp.status_code != 200:
        print(f"  RESULT: ⚠️ unexpected status {resp.status_code}.")
        try:
            print("  Body:", resp.text[:200])
        except Exception:
            pass
        return False

    try:
        videos = resp.json().get("videos", [])
    except Exception as exc:
        print(f"  RESULT: ⚠️ could not parse response ({exc}).")
        return False

    if not videos:
        print("  RESULT: ⚠️ key works but search returned 0 portrait videos.")
        return False

    hd_count = 0
    sample = []
    for v in videos:
        best = _best_portrait_resolution(v.get("video_files", []))
        if best:
            w, h, up = best
            if not up:
                hd_count += 1
            sample.append(f"{w}x{h}{'(upscaled)' if up else ''}")
    print(f"  RESULT: ✅ WORKING - got {len(videos)} clips; "
          f"{hd_count} are full-HD (no upscale).")
    print(f"  Sample best renditions: {', '.join(sample[:5])}")
    print("  EFFECT: backgrounds will be real atmosphere footage (river, peacock, cows, diya). 🎉")
    return hd_count > 0


def check_gemini():
    print(LINE)
    print("2) GEMINI  (decides the SCRIPT; optional - quotes.json fallback exists)")
    print(LINE)
    key = get_env("GEMINI_API_KEY")
    if not key:
        print("  RESULT: ⚠️ GEMINI_API_KEY not set -> using local quotes.json scripts.")
        return False
    print(f"  Key detected (length {len(key)}). Testing a tiny generation...")
    try:
        import google.generativeai as genai
    except Exception as exc:
        print(f"  RESULT: ⚠️ google-generativeai import failed ({exc}).")
        return False
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content("Reply with the single word: OK")
        txt = (getattr(resp, "text", "") or "").strip()
        if txt:
            print(f"  RESULT: ✅ WORKING - model replied: {txt[:40]!r}")
            return True
        print("  RESULT: ⚠️ model returned empty text -> quotes.json fallback.")
        return False
    except Exception as exc:
        print(f"  RESULT: ⚠️ Gemini call failed ({exc}). quotes.json fallback used.")
        return False


def check_youtube():
    print(LINE)
    print("3) YOUTUBE secrets (decides UPLOAD)")
    print(LINE)
    cs = get_env("YT_CLIENT_SECRET_JSON")
    tok = get_env("YT_TOKEN_JSON")
    ok = True
    for name, val in (("YT_CLIENT_SECRET_JSON", cs), ("YT_TOKEN_JSON", tok)):
        if not val:
            print(f"  {name}: ❌ missing")
            ok = False
            continue
        try:
            json.loads(val)
            print(f"  {name}: ✅ present and valid JSON")
        except Exception:
            print(f"  {name}: ⚠️ present but NOT valid JSON")
            ok = False
    return ok


def check_pollinations():
    print(LINE)
    print("4) POLLINATIONS  (decides whether KRISHNA APPEARS AT ALL)")
    print(LINE)
    key = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    if not key:
        print("  ❌ POLLINATIONS_TOKEN is NOT set.")
        print("  EFFECT: scene images get rate-limited (HTTP 429) and many fail.")
        print("  On this channel the generated images ARE the video - there is no")
        print("  stock footage of Krishna - so a rate-limited run produces a reel")
        print("  with no Krishna in it, only atmosphere footage.")
        print("  FIX: free key at https://enter.pollinations.ai (take the sk_ one)")
        return False
    print(f"  ✅ Key detected (length {len(key)}).")
    print("  EFFECT: per-scene Krishna images generate without rate limiting.")
    return True


def check_font():
    print(LINE)
    print("5) DEVANAGARI FONT  (decides whether HINDI TEXT IS READABLE)")
    print(LINE)
    try:
        from modules import textrender
    except Exception as exc:
        print(f"  ⚠️  Could not import textrender ({exc}).")
        return False

    path = textrender.find_font()
    if not path:
        print("  ❌ No font found at all. On-screen text will be skipped entirely.")
        return False
    print(f"  Font resolved: {path}")
    if textrender.has_devanagari_font():
        print("  ✅ It can draw Devanagari.")
        return True
    # This is the failure mode that does NOT announce itself.
    print("  ❌ This font CANNOT draw Devanagari - Hindi renders as empty boxes.")
    print("  Nothing raises an error, so the reel would upload looking broken.")
    print("  FIX: install fonts-noto-core or fonts-indic, or set KRISHNA_FONT.")
    print("  NOTE: there is no Ubuntu package called 'fonts-noto-devanagari' -")
    print("  a CI run already failed on that name. The workflow now discovers the")
    print("  font through fontconfig and downloads Noto directly if apt has none.")
    return False


def main():
    print("\n" + LINE)
    print(" Krishna Universe - SECRET / SOURCE DIAGNOSTIC")
    print(LINE)
    pex = check_pexels()
    gem = check_gemini()
    yt = check_youtube()
    poll = check_pollinations()
    font = check_font()

    print("\n" + LINE)
    print(" FINAL VERDICT")
    print(LINE)
    if pex:
        print(" ATMOSPHERE : ✅ Real footage available (Pexels working)")
    else:
        print(" ATMOSPHERE : ❌ No real footage (Pexels NOT working)")
    print(f" SCRIPT     : {'AI (Gemini)' if gem else 'quotes.json fallback (fine)'}")
    print(f" UPLOAD     : {'✅ secrets present' if yt else '❌ check YT secrets'}")
    print(f" KRISHNA IMG: {'✅ Pollinations key set' if poll else '❌ rate-limited, may render with NO Krishna'}")
    print(f" HINDI TEXT : {'✅ Devanagari font OK' if font else '❌ would render as EMPTY BOXES'}")
    print(LINE)
    if not font:
        print(" >> Fix the font FIRST. It is the only failure here that ships a")
        print("    broken-looking video while reporting success.")
    if not poll:
        print(" >> Then POLLINATIONS_TOKEN: without it the leela may not appear.")
    if not pex:
        print(" >> PEXELS_API_KEY affects the real atmosphere shots cut between scenes.")
    print("")
    print("(NOTE: this run is marked FAILED (red X) ON PURPOSE so the result")
    print(" can be read back remotely. The red X is EXPECTED and harmless -")
    print(" the FINAL VERDICT above is the real answer.)")
    # Intentionally exit non-zero so the job is marked failed and its log is
    # retrievable. The verdict is printed above regardless.
    return 1


if __name__ == "__main__":
    sys.exit(main())
