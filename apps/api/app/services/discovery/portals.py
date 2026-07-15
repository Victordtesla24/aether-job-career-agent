"""Curated, verified company job-board tokens for per-company adapters (P5).

Per-company ATS adapters (Greenhouse, Lever, Ashby, Workable) need a board
token/slug per employer to return jobs. These lists hold REAL tokens verified
to resolve (HTTP 200) against each provider's keyless public API as of
2026-07-15 — a mix of well-known AU and remote-friendly tech employers. They
are deliberately small and honest: no fabricated tokens.

Keyword-searchable sources (Remotive, RemoteOK, Wellfound, Seek) do NOT use
these lists — they query by the user's target role instead.

Each list is overridable at runtime via a comma-separated env var so new
employers can be added without a code change. When the env var is set it
REPLACES the default list.
"""
from __future__ import annotations

import os

#: Greenhouse board tokens — https://boards-api.greenhouse.io/v1/boards/<token>/jobs
#: (cultureamp/eucalyptus/easygo/prospa/montu/octopusdeploy are AU; the rest are
#: large remote-friendly employers). Verified live 2026-07-15.
GREENHOUSE_BOARDS: tuple[str, ...] = (
    "cultureamp",
    "eucalyptus",
    "easygo",
    "prospa",
    "montu",
    "octopusdeploy",
    "gitlab",
    "stripe",
    "anthropic",
)

#: Lever company slugs — https://api.lever.co/v0/postings/<slug>?mode=json
#: Verified live 2026-07-15 (immutable + deputy are AU).
LEVER_COMPANIES: tuple[str, ...] = (
    "immutable",
    "deputy",
    "spotify",
)

#: Ashby job-board tokens — https://api.ashbyhq.com/posting-api/job-board/<token>
#: Tokens are CASE-SENSITIVE. Verified live 2026-07-15.
ASHBY_BOARDS: tuple[str, ...] = (
    "ashby",
    "Ramp",
    "Notion",
    "Vanta",
    "linear",
    "Cursor",
)

#: Workable account subdomains — POST https://apply.workable.com/api/v3/accounts/<sub>/jobs
#: These accounts exist and return the real v3 shape; a board with no currently
#: open roles simply yields zero jobs (surfaced honestly, never fabricated).
WORKABLE_ACCOUNTS: tuple[str, ...] = (
    "veriff",
    "canva",
    "deputy",
)


def _resolve(env_var: str, default: tuple[str, ...]) -> list[str]:
    raw = os.environ.get(env_var)
    if raw is None:
        return list(default)
    return [token.strip() for token in raw.split(",") if token.strip()]


def greenhouse_boards() -> list[str]:
    return _resolve("AETHER_GREENHOUSE_BOARDS", GREENHOUSE_BOARDS)


def lever_companies() -> list[str]:
    return _resolve("AETHER_LEVER_COMPANIES", LEVER_COMPANIES)


def ashby_boards() -> list[str]:
    return _resolve("AETHER_ASHBY_BOARDS", ASHBY_BOARDS)


def workable_accounts() -> list[str]:
    return _resolve("AETHER_WORKABLE_ACCOUNTS", WORKABLE_ACCOUNTS)
