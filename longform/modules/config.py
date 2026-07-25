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
        "cta": "Subscribe for a brand-new moral story every single day!",
    },
    "video": {
        "width": 1280,
        "height": 720,
        "fps": 18,
        "target_duration_seconds": 300,
        "min_duration_seconds": 240,
        "max_duration_seconds": 430,
        "clip_cut_seconds": 8.0,
        "preset": "veryfast",
        "crf": 23,
    },
    "story": {
        "target_words": 800,
        "min_words": 620,
    },
    "palette": {
        "gradient_top": [25, 32, 64],
        "gradient_bottom": [10, 12, 28],
        "solid_fallback": [16, 20, 40],
    },
    "captions": {
        "enabled": True,
        "fontsize": 42,
        "color": "white",
        "stroke_color": "black",
        "stroke_width": 3,
        "font": "DejaVu-Sans-Bold",
        "words_per_group": 9,
        "position_y_ratio": 0.82,
        "bg_opacity": 0.42,
        "bg_color": "#000000",
        "rounded": True,
    },
    "intro": {"enabled": True, "duration_seconds": 4.0, "fontsize": 64},
    "outro": {"enabled": True, "duration_seconds": 5.0, "fontsize": 46},
    "transitions": {"crossfade_seconds": 0.4},
    "grade": {"enabled": True, "saturation": 1.1, "brightness": 6, "contrast": 0.08},
    "tts": {"voice": "en-US-AriaNeural", "rate": "-3%", "pitch": "+0Hz"},
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
            "children playing outdoor",
            "happy family sunset",
            "forest path sunlight",
            "village morning",
            "kids reading book",
            "nature landscape calm",
        ],
    },
    "music": {"enabled": True, "volume": 0.12, "synth_fallback": True, "synth_volume": 0.08},
    "ai_images": {
        "enabled": True,
        "model": "turbo",
        "style": "soft warm childrens storybook illustration, gentle cartoon style, wholesome, cinematic lighting, no text, no words, no letters",
        "max_images": 10,
        "width": 1280,
        "height": 720,
        "workers": 1,
        "motion": False,
        "time_budget_seconds": 200,
        "min_required": 1,
    },
    "youtube": {
        "category_id": "24",
        "privacy_status": "public",
        "made_for_kids": False,
        "hashtags": "#moralstories #bedtimestories #storiesforkids #moralofthestory #kidsstories",
        "default_tags": [
            "moral stories", "bedtime stories", "stories for kids",
            "short story with moral", "moral of the story", "english moral story",
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
