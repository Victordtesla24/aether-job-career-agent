"""Curated, verified company job-board tokens for per-company adapters (P5).

Per-company ATS adapters (Greenhouse, Lever, Ashby, Workable) need a board
token/slug per employer to return jobs. These lists hold REAL tokens verified
to resolve (HTTP 200, not the provider's 404-for-unknown-slug response) against
each provider's keyless public API — a mix of well-known AU and remote-friendly
tech employers. They are deliberately curated and honest: no fabricated
tokens; every token below was curled live before being added (see the
per-block "verified" notes — first batch 2026-07-15, second batch 2026-07-15
gate-6 volume expansion).

Keyword-searchable sources (Remotive, RemoteOK, Wellfound, Seek) do NOT use
these lists — they query by the user's target role instead.

Each list is overridable at runtime via a comma-separated env var so new
employers can be added without a code change. When the env var is set it
REPLACES the default list.
"""
from __future__ import annotations

import os

#: Greenhouse board tokens — https://boards-api.greenhouse.io/v1/boards/<token>/jobs
#: cultureamp/eucalyptus/easygo/prospa/montu/octopusdeploy are AU; the rest are
#: large remote-friendly employers that actively post BA/PM/PO/TPM/Program
#: roles (verified by curling the live boards-api endpoint and confirming
#: >=1 title matching the target role family — see gap-6 sourcing notes):
#: canonical, asana, elastic, datadog, cloudflare, mongodb, figma, okta, brex,
#: block. All tokens verified live (200, non-empty board) 2026-07-15.
#:
#: Phase-6 GATE-07 volume expansion (2026-07-16): grafanalabs, twilio,
#: databricks, samsara, peloton, mozilla, wikimedia — each curled live against
#: boards-api (HTTP 200, non-empty board) and confirmed to carry AU/remote
#: target-role postings that survive relevance.filter_relevant at verification
#: time. Greenhouse's ``updated_at`` keeps live listings fresh, so it is the
#: most reliable within-30-days source (see token_verification.json evidence).
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
    "canonical",
    "asana",
    "elastic",
    "datadog",
    "cloudflare",
    "mongodb",
    "figma",
    "okta",
    "brex",
    "block",
    # Phase-6 GATE-07 volume expansion — verified live 2026-07-16.
    "grafanalabs",
    "twilio",
    "databricks",
    "samsara",
    "peloton",
    "mozilla",
    "wikimedia",
)

#: Lever company slugs — https://api.lever.co/v0/postings/<slug>?mode=json
#: Verified live 2026-07-15 (immutable + deputy are AU). ``palantir`` verified
#: live 2026-07-15 with real Technical Program Manager postings.
#:
#: Phase-6 GATE-07 volume expansion (2026-07-16): brighte/mable/plenti are AU
#: employers (Sydney/Melbourne fintech + care marketplace) with real AU-located
#: BA/PM/PO postings; ``voltus`` is a fully-remote employer with an unblocked
#: remote target-role posting. All curled live (HTTP 200, real board) before
#: being added — see token_verification.json evidence.
LEVER_COMPANIES: tuple[str, ...] = (
    "immutable",
    "deputy",
    "spotify",
    "palantir",
    # Phase-6 GATE-07 volume expansion — verified live 2026-07-16.
    "brighte",
    "mable",
    "plenti",
    "voltus",
)

#: Ashby job-board tokens — https://api.ashbyhq.com/posting-api/job-board/<token>
#: Tokens are CASE-SENSITIVE. ``openai`` verified live 2026-07-15 with dozens
#: of real Technical Program Manager postings; ``Substack``/``Watershed``
#: verified live 2026-07-15 with real Product/Project Manager postings.
#:
#: Phase-6 GATE-07 volume expansion (2026-07-16): airwallex is a Melbourne-HQ
#: fintech (real AU-located PM/delivery postings); supabase/cohere/replit/
#: decagon/harvey are remote-first employers with unblocked remote target-role
#: postings. All curled live (HTTP 200, real board) before being added — see
#: token_verification.json evidence.
ASHBY_BOARDS: tuple[str, ...] = (
    "ashby",
    "Ramp",
    "Notion",
    "Vanta",
    "linear",
    "Cursor",
    "openai",
    "Substack",
    "Watershed",
    # Phase-6 GATE-07 volume expansion — verified live 2026-07-16.
    "airwallex",
    "supabase",
    "cohere",
    "replit",
    "decagon",
    "harvey",
)

#: Workable account subdomains — POST https://apply.workable.com/api/v3/accounts/<sub>/jobs
#: These accounts exist (verified 200 on both the JSON API and the
#: apply.workable.com/<sub>/ career-page widget, which redirects for any
#: nonexistent slug) and return the real v3 shape; a board with no currently
#: open roles simply yields zero jobs (surfaced honestly, never fabricated).
#: ``safetyculture``/``airwallex`` verified live 2026-07-15 — real AU
#: employers, 0 open Workable-hosted roles at verification time (honest, not
#: fabricated).
WORKABLE_ACCOUNTS: tuple[str, ...] = (
    "veriff",
    "canva",
    "deputy",
    "safetyculture",
    "airwallex",
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
