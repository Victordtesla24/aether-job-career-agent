"""In-process, identifier-keyed rate limiting for the auth endpoints.

The auth surface (``/auth/register`` and ``/auth/login``) is public and a
natural brute-force / signup-abuse target. Rate limiting here is keyed on the
**normalized submitted request identifier** — the email/username in the request
body — and deliberately NOT on the client IP.

Why not IP (the rejected design): in this deployment the API sits behind
``Envoy -> nginx -> uvicorn``. nginx forwards no ``X-Forwarded-For`` and
uvicorn's ``ProxyHeadersMiddleware`` trusts the loopback peer, so an IP-keyed
limiter is either bypassable (a forged ``X-Forwarded-For`` mints a fresh bucket
per request) or collapses every user into one global bucket (a site-wide auth
DoS). The client IP is not trustworthy here, so it is never used as a key. See
ADR D-0033 in ``docs/delivery/DECISIONS.md`` — including the honest residual:
identifier-keying does NOT stop distributed mass-registration from many
different emails (that needs CAPTCHA / verified client-IP / email verification).

Two limiters live on ``app.state`` (see ``app.main.create_app``) so each
constructed app — and therefore each test — gets isolated counters, while the
single long-lived production app shares them across all requests to that worker:

* ``login_rate_limiter`` — counts only FAILED logins, keyed by identifier. A
  successful login resets the identifier's counter, so legit users are never
  locked out by their own success. Default: 5 failures / 15 min per identifier.
* ``register_rate_limiter`` — counts every register attempt, keyed by email.
  Default: 3 attempts / hour per email (blunts re-registration spam on one
  address). Different emails are independent.

There is intentionally no low global bucket: a shared low ceiling would be a
user-visible DoS, exactly the failure mode the IP design suffered from.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

#: Login: at most 5 FAILED attempts per identifier per 15-minute window.
DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_LOGIN_WINDOW_SECONDS = 15 * 60.0

#: Register: at most 3 attempts per email per 1-hour window.
DEFAULT_REGISTER_MAX = 3
DEFAULT_REGISTER_WINDOW_SECONDS = 60 * 60.0


def normalize_identifier(identifier: str) -> str:
    """Canonical rate-limit key for an email/username: trimmed + lowercased.

    Normalizing means mixed-case or padded variants of the same identifier
    share one bucket, so an attacker cannot dodge the cap by toggling case or
    adding whitespace.
    """
    return identifier.strip().lower()


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window counter keyed by an arbitrary string.

    Timestamps use a monotonic clock so wall-clock adjustments cannot widen or
    shrink the window. Empty buckets are dropped as they age out so the map does
    not grow unbounded across many distinct identifiers.
    """

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _prune(hits: "deque[float]", cutoff: float) -> None:
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        """Non-recording read: ``True`` once the window already holds the cap.

        Used to gate an attempt *before* processing it (e.g. login) so the check
        itself never consumes budget.
        """
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                return False
            self._prune(hits, cutoff)
            if not hits:
                del self._hits[key]
                return False
            return len(hits) >= self.max_calls

    def record(self, key: str, now: float | None = None) -> None:
        """Record one hit against ``key`` (used for a failed login attempt)."""
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            self._prune(hits, cutoff)
            hits.append(current)

    def allow(self, key: str, now: float | None = None) -> bool:
        """Check-and-record: record and return ``True``, or ``False`` if capped.

        A rejected call is NOT recorded, so a hammering client cannot keep its
        own bucket perpetually full and thereby extend the lockout forever.
        Used for register, where every admitted attempt counts.
        """
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            self._prune(hits, cutoff)
            if len(hits) >= self.max_calls:
                return False
            hits.append(current)
            return True

    def reset(self, key: str) -> None:
        """Drop ``key``'s bucket entirely (used when a login succeeds)."""
        with self._lock:
            self._hits.pop(key, None)

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Whole seconds until ``key`` frees a slot — for the Retry-After header.

        That is when the oldest in-window hit expires. Always at least 1 so the
        header never advertises an immediate retry while still blocked.
        """
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            self._prune(hits, cutoff)
            if not hits:
                del self._hits[key]
                return 0
            remaining = hits[0] + self.window_seconds - current
            return max(1, math.ceil(remaining))


def _int_env(name: str, default: int) -> int:
    """Positive int from ``name``; malformed/non-positive values fall back."""
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    """Positive float from ``name``; malformed/non-positive values fall back."""
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def build_login_rate_limiter() -> SlidingWindowRateLimiter:
    """Login failure limiter, honouring optional env overrides.

    ``AUTH_LOGIN_MAX_FAILURES`` / ``AUTH_LOGIN_WINDOW_SECONDS`` tune per
    environment without a code change; malformed values fall back to defaults.
    """
    return SlidingWindowRateLimiter(
        max_calls=_int_env("AUTH_LOGIN_MAX_FAILURES", DEFAULT_LOGIN_MAX_FAILURES),
        window_seconds=_float_env(
            "AUTH_LOGIN_WINDOW_SECONDS", DEFAULT_LOGIN_WINDOW_SECONDS
        ),
    )


def build_register_rate_limiter() -> SlidingWindowRateLimiter:
    """Register attempt limiter, honouring optional env overrides.

    ``AUTH_REGISTER_MAX`` / ``AUTH_REGISTER_WINDOW_SECONDS`` tune per
    environment; malformed values fall back to defaults.
    """
    return SlidingWindowRateLimiter(
        max_calls=_int_env("AUTH_REGISTER_MAX", DEFAULT_REGISTER_MAX),
        window_seconds=_float_env(
            "AUTH_REGISTER_WINDOW_SECONDS", DEFAULT_REGISTER_WINDOW_SECONDS
        ),
    )


def _raise_429(retry_after: int, message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message,
        headers={"Retry-After": str(max(1, retry_after))},
    )


# --- Login: count only FAILED attempts, keyed by identifier ----------------


def guard_login_attempt(request: Request, identifier: str) -> None:
    """429 when this identifier has already hit its failed-login cap.

    Called before verifying credentials; a missing limiter (defensive —
    ``create_app`` always sets one) degrades to a no-op.
    """
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "login_rate_limiter", None
    )
    if limiter is None:
        return
    key = normalize_identifier(identifier)
    if limiter.is_blocked(key):
        _raise_429(
            limiter.retry_after(key),
            "Too many failed login attempts for this account. "
            "Please wait and try again.",
        )


def record_login_failure(request: Request, identifier: str) -> None:
    """Count one failed login against this identifier's bucket."""
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "login_rate_limiter", None
    )
    if limiter is None:
        return
    limiter.record(normalize_identifier(identifier))


def reset_login_failures(request: Request, identifier: str) -> None:
    """Clear this identifier's failure bucket after a successful login."""
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "login_rate_limiter", None
    )
    if limiter is None:
        return
    limiter.reset(normalize_identifier(identifier))


# --- Register: count every attempt, keyed by email -------------------------


def guard_register_attempt(request: Request, email: str) -> None:
    """Record this register attempt and 429 when the per-email cap is exceeded.

    A missing limiter (defensive) degrades to a no-op.
    """
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "register_rate_limiter", None
    )
    if limiter is None:
        return
    key = normalize_identifier(email)
    if not limiter.allow(key):
        _raise_429(
            limiter.retry_after(key),
            "Too many registration attempts for this email. "
            "Please wait and try again.",
        )
