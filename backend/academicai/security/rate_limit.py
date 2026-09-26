"""In-process fixed-window rate limiting (spec 25).

Sufficient for a single-process MVP. A multi-process deployment needs a shared
store; the call sites do not change when that is swapped in.
"""
import threading
from collections import defaultdict

from flask import current_app, request

from .. import clock
from ..errors import RateLimitError

_lock = threading.Lock()
_hits = defaultdict(list)


def reset():
    with _lock:
        _hits.clear()


def limit(bucket, max_hits, per_seconds, key=None):
    """Record a hit and raise RateLimitError if the window is exhausted."""
    if not current_app.config.get("RATE_LIMIT_ENABLED", True):
        return
    identity = key or (request.remote_addr or "unknown")
    now_ts = clock.now().timestamp()
    window_start = now_ts - per_seconds
    composite = f"{bucket}:{identity}"
    with _lock:
        recent = [t for t in _hits[composite] if t >= window_start]
        if len(recent) >= max_hits:
            recent.append(now_ts)
            _hits[composite] = recent
            raise RateLimitError("Too many requests. Please try again later.")
        recent.append(now_ts)
        _hits[composite] = recent
