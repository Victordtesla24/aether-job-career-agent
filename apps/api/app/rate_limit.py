"""Lightweight in-process rate limiting for the auth endpoints.

The auth surface (``/auth/register`` and ``/auth/login``) is public and a
natural brute-force / signup-abuse target, so each client IP is capped at a
small number of calls per rolling window. ``slowapi`` is not a dependency and
would pull Redis-style infrastructure we do not need here — a per-process
sliding-window counter keyed by client IP is sufficient to blunt scripted
abuse against a single API worker.

The limiter instance lives on ``app.state`` (see ``app.main.create_app``) so
that each constructed app — and therefore each test — gets an isolated
counter, while the single long-lived production app shares one counter across
all requests to that worker.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

#: Defaults: 5 auth calls per client IP per 60s window (contract guidance).
DEFAULT_MAX_CALLS = 5
DEFAULT_WINDOW_SECONDS = 60.0


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window counter keyed by an arbitrary string.

    ``allow(key)`` records the call and returns ``False`` once more than
    ``max_calls`` calls have landed within the trailing ``window_seconds``.
    Timestamps use a monotonic clock so wall-clock adjustments cannot widen or
    shrink the window.
    """

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return False
            hits.append(current)
            return True


def build_auth_rate_limiter() -> SlidingWindowRateLimiter:
    """Construct the auth limiter, honouring optional env overrides.

    ``AUTH_RATE_LIMIT_MAX`` / ``AUTH_RATE_LIMIT_WINDOW_SECONDS`` allow tuning
    per environment without a code change; malformed values fall back to the
    safe defaults rather than crashing app construction.
    """

    def _int_env(name: str, default: int) -> int:
        try:
            value = int(os.environ.get(name, "").strip() or default)
        except ValueError:
            return default
        return value if value > 0 else default

    def _float_env(name: str, default: float) -> float:
        try:
            value = float(os.environ.get(name, "").strip() or default)
        except ValueError:
            return default
        return value if value > 0 else default

    return SlidingWindowRateLimiter(
        max_calls=_int_env("AUTH_RATE_LIMIT_MAX", DEFAULT_MAX_CALLS),
        window_seconds=_float_env("AUTH_RATE_LIMIT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS),
    )


def _client_ip(request: Request) -> str:
    """Resolve the caller's real client IP from the trusted socket peer.

    Uvicorn runs with its default ``proxy_headers=True`` /
    ``forwarded_allow_ips='127.0.0.1'``, so its ``ProxyHeadersMiddleware``
    already rewrites ``scope['client']`` to the genuine external caller when the
    request arrives through the single trusted ``nginx → 127.0.0.1`` hop.
    Reading ``request.client.host`` therefore yields the real client IP.

    We deliberately do NOT parse ``X-Forwarded-For`` ourselves: that header is
    fully attacker-controlled end-to-end, so keying on its left-most entry would
    let any caller mint a fresh limiter bucket per request (a unique spoofed
    value each time) and slip past the limiter entirely — defeating the whole
    brute-force / signup-abuse defence. The socket peer cannot be spoofed by the
    client, so it is the only trustworthy key here.
    """
    return request.client.host if request.client else "unknown"


def enforce_auth_rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 when the caller exceeds the auth call budget.

    A missing limiter on ``app.state`` (defensive; ``create_app`` always sets
    one) degrades to no-op rather than failing the request.
    """
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "auth_rate_limiter", None
    )
    if limiter is None:
        return
    if not limiter.allow(_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(int(limiter.window_seconds))},
        )
