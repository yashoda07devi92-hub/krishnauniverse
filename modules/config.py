"""
Central configuration, environment, path and logging helpers for
Krishna Universe.

Everything else in the project imports from here so that paths, the loaded
config.json and logging are consistent across modules.
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
QUOTES_PATH = BASE_DIR / "quotes.json"

# Make sure the directories that we write to exist.
for _d in (ASSETS_DIR, CLIPS_DIR, IMAGES_DIR, MUSIC_DIR, CACHE_DIR, OUTPUT_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover - defensive
        pass


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------
_DEFAULT_CONFIG = {
    "channel": {"name": "Krishna Universe"},
    "video": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "target_duration_seconds": 60,
        "clip_cut_seconds": 3.0,
        "background_zoom": 1.08,
    },
    # These are the LAST-RESORT defaults used only when config.json is missing a
    # key. They were left over from the cute-pets channel this was ported from,
    # which meant a single missing key could silently put an English voice, a
    # pastel palette or a "cute puppy" footage search into a Hindi Krishna reel -
    # with no error to show why.
    "palette": {
        "gradient_top": [255, 196, 118],
        "gradient_bottom": [138, 76, 158],
        "solid_fallback": [216, 138, 76],
    },
    "captions": {"enabled": False, "fontsize": 78, "color": "white"},
    "hook": {"enabled": True, "duration_seconds": 2.5},
    "tts": {"voice": "hi-IN-MadhurNeural", "rate": "-10%", "pitch": "+0Hz"},
    "gemini": {"model": "gemini-2.0-flash"},
    "pexels": {"default_keywords": ["river water flowing sunlight",
                                    "peacock feathers close up",
                                    "oil lamp diya flame dark"]},
    "music": {"enabled": True, "volume": 0.16},
    "youtube": {"category_id": "24", "privacy_status": "public",
                "default_language": "hi", "default_audio_language": "hi"},
}


def _load_config():
    """Load config.json, falling back to sane defaults on any error."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # shallow-merge defaults for any missing top-level keys
        for key, val in _DEFAULT_CONFIG.items():
            data.setdefault(key, val)
        return data
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Could not load config.json (%s); using defaults.", exc)
        return dict(_DEFAULT_CONFIG)


# The single shared config object.
cfg = _load_config()


# --------------------------------------------------------------------------
# Environment helpers
# --------------------------------------------------------------------------
def get_env(name, default=None):
    """Read an environment variable, treating blank/placeholder as unset.

    Placeholders such as 'your_key_here', 'changeme', 'xxx' are treated as if
    the variable were not set so that callers can fall back gracefully.
    """
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip()
    if not val:
        return default
    lowered = val.lower()
    placeholders = {
        "your_key_here",
        "your-key-here",
        "your_gemini_api_key_here",
        "your_pexels_api_key_here",
        "changeme",
        "change_me",
        "todo",
        "none",
        "null",
        "xxx",
        "placeholder",
    }
    if lowered in placeholders:
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
    """Configure root logging once with a clean, readable format."""
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
