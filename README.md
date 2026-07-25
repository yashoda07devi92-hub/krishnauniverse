# 🐾 Krishna Universe — Faceless YouTube Shorts Automation

Fully automated, **free + open-source** pipeline for a faceless YouTube Shorts
channel in the **heartwarming cute pets & babies** niche (USA / English).

Each run:
1. ✍️ Writes a ~150-word wholesome script (Google **Gemini**, with a local
   `quotes.json` fallback so it works even with no API key).
2. 🎙️ Generates a warm USA female voiceover (**edge-tts**, falling back to
   **gTTS** automatically — including on GitHub runner `403`s).
3. 🎬 Builds a cinematic **1080×1920** reel: real **Pexels** footage with fast
   cuts, a scroll-stopping **5-second animated hook**, Ken-Burns image
   fallbacks, a keyless **Picsum** safety net, a warm-gradient last resort,
   plus animated timing-based captions and a subtle cinematic grade
   (warm wash + soft vignette).
4. ⬆️ Auto-uploads to **YouTube** (OAuth2). Optional Instagram (off by default).
5. ⏰ Runs **3× per day** at staggered USA times via GitHub Actions.

> **Copyright:** Only **Pexels** / **Picsum** free media + **AI** narration are
> used. No copyrighted or "viral" clips are referenced or downloaded. Add only
> royalty-free music to `assets/music/`.

---

## 🇬🇧 English Setup Guide

### 1. Get free API keys
| Key | Where | Cost |
|-----|-------|------|
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey | Free |
| `PEXELS_API_KEY` | https://www.pexels.com/api/ | Free |

### 2. YouTube OAuth (one-time)
1. In **Google Cloud Console**, create a project and enable the **YouTube Data
   API v3**.
2. Create an **OAuth client ID** (type: *Desktop app*) and download the JSON —
   its full contents become `YT_CLIENT_SECRET_JSON`.
3. Authorize once to mint a token. Easiest local way:
   ```bash
   python upload_youtube.py --authorize
   ```
   This prints the token JSON — copy it into the `YT_TOKEN_JSON` secret.
   *Alternatively* use the [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/):
   select scope `https://www.googleapis.com/auth/youtube.upload`, exchange for
   tokens, and copy the resulting JSON.

### 3. Add the GitHub Secrets
In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add these four (paste full JSON contents for the YouTube ones):

| Secret | Required | Purpose |
|--------|----------|---------|
| `GEMINI_API_KEY` | ✅ | AI script writing (falls back to `quotes.json`) |
| `PEXELS_API_KEY` | ✅ | Cute stock footage/photos |
| `YT_CLIENT_SECRET_JSON` | ✅ | YouTube OAuth client secret (full JSON) |
| `YT_TOKEN_JSON` | ✅ | Authorized YouTube token (full JSON) |
| `IG_USERNAME` / `IG_PASSWORD` | ⛔ optional | Instagram (off by default) |

### 4. Schedule (3 posts/day)
The workflow (`.github/workflows/auto-reel.yml`) runs at **12:00 / 17:00 /
22:00 UTC**, mapping to USA Eastern Time:

| UTC | ET (EST, winter) | ET (EDT, summer) | Slot |
|-----|------------------|------------------|------|
| 12:00 | 07:00 | 08:00 | Morning |
| 17:00 | 12:00 | 13:00 | Midday |
| 22:00 | 17:00 | 18:00 | Evening |

Each **scheduled** run makes exactly **one** reel and uploads it → 3 posts/day.
You can also trigger it manually (**Actions → Krishna Universe Auto Reel → Run
workflow**) with custom `days` / `per_day` / upload toggles.

### 5. Run locally
```bash
# (a) install
pip install -r requirements.txt
# also need system tools: ffmpeg + imagemagick (for captions/hook text)

# (b) generate ONE reel
python generate.py --days 1 --per-day 1

# (c) upload the newest reel to YouTube
python upload_youtube.py --limit 1 --privacy public
```

### 6. Background music (optional)
Drop one royalty-free track into `assets/music/` (e.g. `soft-piano.mp3`). It is
auto-mixed under the voiceover at ~12% volume. Sources: YouTube Audio Library,
Pixabay Music, Free Music Archive. Music files are gitignored.

---

## 🇮🇳 हिंदी गाइड (Hindi Guide)

### 1. फ्री API keys लें
- **`GEMINI_API_KEY`** — https://aistudio.google.com/app/apikey से फ्री में लें
  (AI से स्क्रिप्ट लिखने के लिए; key न हो तो `quotes.json` से अपने-आप काम चलेगा)।
- **`PEXELS_API_KEY`** — https://www.pexels.com/api/ से फ्री में लें
  (प्यारे जानवरों/बच्चों के मुफ्त वीडियो/फोटो के लिए)।

### 2. YouTube OAuth (एक बार का सेटअप)
1. **Google Cloud Console** में project बनाएं और **YouTube Data API v3** चालू करें।
2. **OAuth client ID** (*Desktop app*) बनाकर JSON डाउनलोड करें — इसकी पूरी
   contents `YT_CLIENT_SECRET_JSON` में जाएगी।
3. एक बार token बनाएं:
   ```bash
   python upload_youtube.py --authorize
   ```
   जो JSON दिखे उसे `YT_TOKEN_JSON` secret में डालें। या
   [OAuth Playground](https://developers.google.com/oauthplayground/) से scope
   `youtube.upload` चुनकर token बनाएं।

### 3. GitHub Secrets जोड़ें
रिपॉज़िटरी में **Settings → Secrets and variables → Actions** में ये चार secrets
डालें: `GEMINI_API_KEY`, `PEXELS_API_KEY`, `YT_CLIENT_SECRET_JSON`,
`YT_TOKEN_JSON` (YouTube वाली में पूरा JSON paste करें)। Instagram वाली
(`IG_USERNAME`/`IG_PASSWORD`) optional हैं और by default बंद हैं।

### 4. शेड्यूल (दिन में 3 बार)
Workflow हर दिन **12:00 / 17:00 / 22:00 UTC** पर चलता है, जो अमेरिका के सुबह,
दोपहर और शाम के समय से मेल खाता है। हर scheduled run में **एक** reel बनती और
अपलोड होती है — यानी रोज़ 3 posts।

### 5. लोकल रन
```bash
pip install -r requirements.txt        # साथ में ffmpeg + imagemagick चाहिए
python generate.py --days 1 --per-day 1 # एक reel बनाएं
python upload_youtube.py --limit 1      # YouTube पर अपलोड करें
```

### 6. बैकग्राउंड म्यूज़िक (वैकल्पिक)
`assets/music/` में कोई एक royalty-free गाना डालें — वह voiceover के नीचे ~12%
वॉल्यूम पर अपने-आप मिक्स हो जाएगा। (कॉपीराइट-फ्री म्यूज़िक ही इस्तेमाल करें।)

---

## 🗂️ Project Structure
```
krishnauniverse/
├── generate.py              # full pipeline CLI (--days/--per-day/--limit/--topic)
├── upload_youtube.py        # YouTube uploader CLI (--authorize/--limit/--privacy)
├── upload_instagram.py      # optional IG uploader (off by default)
├── config.json              # palette, voice, captions, hook, grade, posting settings
├── quotes.json              # 22+ pre-written fallback scripts
├── requirements.txt         # pinned, free deps (no openai-whisper; Pillow 9.5.0)
├── .env.example             # all env vars (no real secrets)
├── assets/music/.gitkeep    # drop royalty-free music here
├── modules/
│   ├── config.py            # paths, env, config, logging
│   ├── gemini_script.py     # Gemini -> quotes.json fallback; derived hook
│   ├── tts.py               # edge-tts -> gTTS fallback
│   ├── pexels_video.py      # robust Pexels VIDEO search (multi-pass)
│   ├── images.py            # Pexels PHOTOS + keyless Picsum images
│   ├── subtitles.py         # timing-based captions (no whisper)
│   ├── video_composer.py    # background chain + Ken-Burns + grade + hook
│   ├── youtube.py           # YouTube Data API v3 upload (OAuth2)
│   └── instagram.py         # optional instagrapi upload
└── .github/workflows/auto-reel.yml   # 3×/day schedule + manual dispatch
```

## ⚖️ License & Content Notes
- Footage/photos: **Pexels** & **Picsum** (free to use). Narration: **AI**-generated.
- Do **not** add copyrighted or third-party "viral" clips.
- Automated Instagram posting can violate IG's ToS and risk bans — it is **off
  by default** and provided for completeness only.
