"""Tiny keyless HTTP JSON fetcher for live discovery sources (D11).

Uses only the standard library (urllib) so no new runtime dependency is
introduced. Every call has a hard timeout and a browser-like User-Agent
(some public boards reject the default urllib UA).

Tests must NEVER hit this module — adapters run in fixture mode under
pytest (``AETHER_DISCOVERY_FIXTURE_DIR`` is set by conftest).
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 15
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 AetherJobAgent/1.0"
)


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    """GET ``url`` and decode the JSON body. Raises on HTTP/network errors."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))
