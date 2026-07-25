# Krishna Universe Katha

Automated **daily long-form (5-7 min) moral-story videos for kids** for YouTube.
Each day the pipeline writes a brand-new moral story, narrates it with a warm
storyteller voice, builds a 1920x1080 HD video with real stock footage,
readable captions, an intro title card, soft music and an outro call-to-action,
then uploads it to YouTube at **US prime time**.

> Separate from the Krishna Universe reels/shorts pipeline - this repo has its own
> schedule, config and YouTube upload step, so it does not affect any shorts.

## How it works

```
generate.py
  1. story.py        -> Gemini writes a ~950-word moral story (stories.json fallback)
  2. tts.py          -> edge-tts narration (gTTS fallback), chunked for long text
  3. video_composer  -> 1920x1080 HD: scene-switching Pexels footage + crossfades,
                        intro title card, full-length captions, soft music, outro CTA
  4. thumbnail.py    -> bold 1280x720 thumbnail
  5. manifest.json   -> records the episode
upload_youtube.py    -> uploads pending episodes (+ thumbnail) to YouTube
```

Everything is defensive: if Gemini or Pexels keys are missing it falls back to
bundled stories and a calm gradient background, so a video is always produced.

## Schedule

Defined in `.github/workflows/auto-longform.yml`:

| Cron (UTC)     | US Eastern | US Pacific | IST     |
|----------------|------------|------------|---------|
| `30 22 * * *`  | 6:30 PM ET | 3:30 PM PT | 4:00 AM |

One video per day, aimed at the US early-evening viewing window (best for
long watch-time content). Edit the cron to change the time.

## Setup (one time)

Add these as **GitHub repository Secrets** (Settings -> Secrets and variables -> Actions):

| Secret | Required | Purpose |
|--------|----------|---------|
| `GEMINI_API_KEY` | recommended | AI story writing (free: aistudio.google.com/app/apikey) |
| `PEXELS_API_KEY` | recommended | HD stock footage (free: pexels.com/api) |
| `YT_CLIENT_SECRET_JSON` | for upload | OAuth client secret JSON (Google Cloud Console) |
| `YT_TOKEN_JSON` | for upload | Authorized OAuth token JSON |
| `TTS_VOICE` | optional | Override narrator voice (default `en-US-AriaNeural`) |

Mint the YouTube token once locally:

```bash
pip install -r requirements.txt
python upload_youtube.py --authorize   # opens a browser, prints YT_TOKEN_JSON
```

> Tip: To keep the YouTube Data API daily quota (10,000 units; ~1600 per
> upload) comfortable when this shares a channel with the Krishna Universe reels,
> 4 reels + 1 long-form = ~8,000 units/day, which stays safely under the cap.

## Run it manually

GitHub: **Actions -> Krishna Universe Auto Longform -> Run workflow**
- `diagnose_only=true` - just check secrets, make nothing
- `selftest=true` - build a video but do NOT upload (downloadable as an artifact)

Locally:

```bash
pip install -r requirements.txt
python generate.py                 # one episode
python generate.py --count 2       # a batch
python generate.py --lesson honesty --topic "a child finds a lost wallet"
```

## Configuration

Tune `config.json` - duration, captions, fonts, colors, music volume, Gemini
model, Pexels keywords, YouTube category/tags, intro/outro, etc.
