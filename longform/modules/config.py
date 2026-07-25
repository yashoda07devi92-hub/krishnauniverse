"""
Central configuration, environment, path and logging helpers for
Krishna Universe Katha.

Every other module imports from here so that paths, the loaded config.json and
logging stay consistent across the project.
"""

import json
import logging
import os
from pathlib import Path

# --------------------------------------------------------------------------
# Optional .env support (never hard-fail if python-dotenv is missing)
# --------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


# --------------------------------------------------------------------------
# Project paths
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
CLIPS_DIR = ASSETS_DIR / "clips"
IMAGES_DIR = ASSETS_DIR / "images"
MUSIC_DIR = ASSETS_DIR / "music"
CACHE_DIR = ASSETS_DIR / "cache"
OUTPUT_DIR = BASE_DIR / "output"

CONFIG_PATH = BASE_DIR / "config.json"
STORIES_PATH = BASE_DIR / "stories.json"

for _d in (ASSETS_DIR, CLIPS_DIR, IMAGES_DIR, MUSIC_DIR, CACHE_DIR, OUTPUT_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover - defensive
        pass


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------
_DEFAULT_CONFIG = {
    "channel": {
        "name": "Krishna Universe",
        "cta": "राधे राधे। ऐसी ही कथाओं के लिए चैनल को Subscribe कीजिए।",
    },
    # NOTE: config.json currently overrides every key below, so none of these
    # are live. They are corrected anyway because they are the SECOND copy of
    # the same settings: if config.json is ever missing or loses a key, these
    # silently restored the English children's-story channel - 720p/18fps,
    # motion off (a literal slideshow), an American voice and English tags.
    "video": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "target_duration_seconds": 390,
        "min_duration_seconds": 300,
        "max_duration_seconds": 480,
        "scene_cut_seconds": 4.0,
        "clip_cut_seconds": 3.0,
        "preset": "veryfast",
        "crf": 23,
    },
    "story": {
        "target_words": 900,
        "min_words": 700,
        "max_words": 1150,
    },
    "motion": {"overscan": 1.22, "zoom_amount": 0.08, "real_every": 3},
    "palette": {
        "gradient_top": [46, 30, 74],
        "gradient_bottom": [14, 10, 28],
        "solid_fallback": [30, 20, 50],
    },
    "captions": {
        "enabled": True,
        "fontsize": 38,
        "color": "#FFF6E0",
        "stroke_color": "black",
        "stroke_width": 3,
        "font": "ignored-see-textrender",
        "words_per_group": 7,
        "position_y_ratio": 0.82,
        "bg_opacity": 0.42,
        "bg_color": "#000000",
        "rounded": True,
    },
    "intro": {"enabled": True, "duration_seconds": 4.0, "fontsize": 64},
    "outro": {"enabled": True, "duration_seconds": 5.0, "fontsize": 46},
    "transitions": {"crossfade_seconds": 0.4},
    "grade": {"enabled": True, "saturation": 1.1, "brightness": 6, "contrast": 0.08},
    "tts": {"voice": "hi-IN-MadhurNeural", "rate": "-10%", "pitch": "+0Hz",
            "fallback_lang": "hi", "fallback_tld": "co.in"},
    "gemini": {
        "model": "gemini-2.0-flash",
        "model_candidates": [
            "gemini-2.0-flash",
            "gemini-flash-latest",
            "gemini-2.5-flash",
        ],
        "temperature": 0.95,
    },
    "pexels": {
        "orientation": "landscape",
        "min_clips": 16,
        "per_query": 20,
        "default_keywords": [
            "river water flowing sunlight",
            "peacock dancing slow motion",
            "cows grazing green field india",
            "oil lamp diya flame dark",
            "indian temple architecture",
            "forest sunlight rays trees",
        ],
    },
    "music": {"enabled": True, "volume": 0.12, "synth_fallback": True, "synth_volume": 0.08},
    "ai_images": {
        "enabled": True,
        "model": "flux",
        "style": "cinematic indian mythological art, dramatic warm lighting, rich saffron and deep blue palette, highly detailed, volumetric god rays, soft film grain, painterly, devotional, beautiful",
        "max_images": 14,
        "width": 1920,
        "height": 1080,
        "workers": 3,
        # motion MUST default to True. False was the shipped default and it is
        # literally what made the long-form a crossfaded photo sequence.
        "motion": True,
        "time_budget_seconds": 300,
        "min_required": 1,
    },
    "youtube": {
        "category_id": "24",
        "privacy_status": "public",
        "made_for_kids": False,
        "default_language": "hi",
        "default_audio_language": "hi",
        "hashtags": "#कृष्णकथा #श्रीकृष्ण #भक्ति",
        "default_tags": [
            "कृष्ण कथा", "krishna story in hindi", "श्रीकृष्ण कथा",
            "भक्ति कथा", "गीता उपदेश", "महाभारत कथा",
        ],
    },
}


def _deep_merge_defaults(data, defaults):
    """Recursively fill in any missing keys from defaults (in-place)."""
    for key, val in defaults.items():
        if key not in data:
            data[key] = val
        elif isinstance(val, dict) and isinstance(data.get(key), dict):
            _deep_merge_defaults(data[key], val)
    return data


def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return _deep_merge_defaults(data, _DEFAULT_CONFIG)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Could not load config.json (%s); using defaults.", exc)
        return dict(_DEFAULT_CONFIG)


cfg = _load_config()


# --------------------------------------------------------------------------
# Environment helpers
# --------------------------------------------------------------------------
def get_env(name, default=None):
    """Read an env var, treating blank/placeholder values as unset."""
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip()
    if not val:
        return default
    placeholders = {
        "your_key_here", "your-key-here", "your_gemini_api_key_here",
        "your_pexels_api_key_here", "changeme", "change_me", "todo",
        "none", "null", "xxx", "placeholder",
    }
    if val.lower() in placeholders:
        return default
    return val


def get_cfg(path, default=None):
    """Read a nested config value with a dotted path, e.g. 'video.fps'."""
    node = cfg
    try:
        for part in path.split("."):
            node = node[part]
        return node
    except Exception:
        return default


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
_LOGGING_CONFIGURED = False


def setup_logging(level=logging.INFO):
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return logging.getLogger("krishna")
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    _LOGGING_CONFIGURED = True
    return logging.getLogger("krishna")
