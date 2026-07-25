"""
No-repeat selection for the long-form storytelling pipeline.

Identical mechanism to modules/history.py on the Shorts side, but with its own
history file (longform/history.json) so the two pipelines never contend for the
same file when their schedules overlap. Long-form publishes 3 times a week, so
its 80-seed topic pool lasts about half a year before a single premise returns.

THE PROBLEM
-----------
Every pool in this project used to be sampled with `random.choice`, which puts
the item straight back in the bag. At 5 uploads a day that means a story idea, a
spoken hook or a thumbnail caption comes back around within days -- viewers see
it as "these videos are all the same", and YouTube's inauthentic-content policy
sees it as template-based output. Growing the pools helps but does not fix it:
random selection from 150 items still produces a collision surprisingly fast
(the birthday problem -- roughly a 50% chance of a repeat inside 15 draws).

THE FIX
-------
Draw WITHOUT replacement, and remember across runs. Every GitHub Actions run is
a fresh process with a fresh checkout, so "remember" has to mean a file on disk
that is committed back to the repo:

    history.json  ->  {"used": {"topics": [...], "hooks": [...]}, "cycles": {...}}

`pick()` only ever offers items absent from `used`. When a pool is genuinely
exhausted it resets, bumps a cycle counter, and starts again -- and even then the
repeated topic arrives with a different hook, screen hook, flash text, narrator
voice and title pattern, so the video is not a repeat in any way a viewer
notices.

TWO-PHASE COMMIT
----------------
`pick()` records into a pending buffer; nothing is written until `commit()` is
called, which generate.py does only after a reel has actually rendered. A run
that dies half way through therefore does not burn a topic.

Everything is best-effort: a missing, unreadable or corrupt history file degrades
to plain random selection rather than stopping a video from being made.
"""

import json
import logging
import os
import random

from .config import BASE_DIR

log = logging.getLogger("krishna.history")

HISTORY_PATH = os.path.join(str(BASE_DIR), "history.json")

_state = None      # {"used": {...}, "cycles": {...}}
_pending = {}      # {pool_name: [items picked this run, not yet committed]}


def _blank():
    return {"used": {}, "cycles": {}}


def _load():
    """Read history.json, tolerating anything that is not a usable file."""
    global _state
    if _state is not None:
        return _state
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("history.json is not an object")
        data.setdefault("used", {})
        data.setdefault("cycles", {})
        if not isinstance(data["used"], dict) or not isinstance(data["cycles"], dict):
            raise ValueError("history.json has unexpected structure")
        _state = data
        total = sum(len(v) for v in data["used"].values() if isinstance(v, list))
        log.info("Loaded history.json (%d remembered item(s)).", total)
    except FileNotFoundError:
        log.info("No history.json yet; starting a fresh rotation.")
        _state = _blank()
    except Exception as exc:
        # A corrupt file must never stop a video from being produced.
        log.warning("Could not read history.json (%s); starting fresh.", exc)
        _state = _blank()
    return _state


def _used(name):
    state = _load()
    values = state["used"].get(name)
    if not isinstance(values, list):
        values = []
        state["used"][name] = values
    return values


def _key(item):
    """Normalise so trivial casing/spacing differences still count as the same."""
    return " ".join(str(item).split()).lower()


def remaining(name, pool):
    """Items from `pool` that have not been used in the current cycle."""
    spent = {_key(x) for x in _used(name)}
    spent |= {_key(x) for x in _pending.get(name, [])}
    return [item for item in pool if _key(item) not in spent]


def pick(name, pool, count=1, rng=None):
    """Choose `count` unused item(s) from `pool`.

    Returns a single item when count == 1, otherwise a list. Resets the pool's
    history automatically once every item has been used.
    """
    rng = rng or random
    pool = [p for p in (pool or []) if str(p).strip()]
    if not pool:
        return None if count == 1 else []

    chosen = []
    for _ in range(max(1, int(count))):
        options = remaining(name, pool)
        if not options:
            # Pool exhausted: start a new cycle rather than refusing to pick.
            state = _load()
            state["used"][name] = []
            state["cycles"][name] = int(state["cycles"].get(name, 0)) + 1
            _pending[name] = []
            log.info(
                "Pool '%s' exhausted after %d item(s); starting cycle %d.",
                name, len(pool), state["cycles"][name],
            )
            options = list(pool)
        item = rng.choice(options)
        _pending.setdefault(name, []).append(item)
        chosen.append(item)

    return chosen[0] if count == 1 else chosen


def commit():
    """Move this run's picks into history and write the file.

    Called only after a reel has actually been produced, so a failed run does not
    consume its topic. Returns True on a successful write.
    """
    global _pending
    if not _pending:
        return False
    state = _load()
    moved = 0
    for name, items in _pending.items():
        target = _used(name)
        for item in items:
            if _key(item) not in {_key(x) for x in target}:
                target.append(item)
                moved += 1
    _pending = {}

    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
        log.info("history.json updated (+%d item(s)).", moved)
        return True
    except Exception as exc:
        log.warning("Could not write history.json (%s).", exc)
        return False


def discard():
    """Throw away this run's picks (used when a reel failed to render)."""
    global _pending
    _pending = {}


def status(pools):
    """Human-readable rotation state. `pools` is {name: pool_list}."""
    lines = []
    state = _load()
    for name, pool in sorted(pools.items()):
        left = len(remaining(name, pool))
        cycle = int(state["cycles"].get(name, 0)) + 1
        lines.append(
            f"{name:<14}{left:>4} of {len(pool):<4} unused   (cycle {cycle})"
        )
    return "\n".join(lines)
