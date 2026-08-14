"""U-AGI MODEL-DEFAULT config gate — the SERVED env config must NEVER resolve a
model tier to OpenRouter (OWNER DIRECTIVE, 2026-08-14).

Owner directive, verbatim intent: "do not use openrouter api key other than the
22 ai agents; the system default must be anthropic pro subs quota (token saved
in env)."

Finding-1 enforcement. ``llm_client.get_model()`` only applies the
Anthropic-first code default (``_DEFAULT_MODEL_BY_TIER`` / ``FALLBACK_MODEL``)
when ``AETHER_MODEL_<TIER>`` is UNSET. Every ``.env`` this deployment loads
(``start-api.sh:20`` / ``start-worker.sh:20`` export the repo-root ``.env`` into
the running process) sets those vars EXPLICITLY, so a stale OpenRouter id there
silently overrides the code default in production — which is exactly how the
system default stayed OpenRouter after the code flip. This gate fails loudly if:

  * the committed template ``.env.example`` (always present) resolves any
    ``AETHER_MODEL_*`` tier — or the D-0014 ``AETHER_MODEL_FALLBACK`` — to a
    non-anthropic provider, so ``cp .env.example .env`` can never reseed the
    OpenRouter-as-default problem; and
  * any live ``.env`` this deployment actually reads (the repo-root ``.env``,
    and every path the start scripts load) resolves a tier to OpenRouter.

It is deliberately narrow: only ``AETHER_MODEL_*`` tier/fallback keys are read
from a dotenv file — no other key (and therefore no secret, incl.
``CLAUDE_CODE_OAUTH_TOKEN``) is parsed, returned or surfaced.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.llm_client import resolve_provider

# apps/api/tests/<this file>  ->  parents[3] == repo root (the tree under test).
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The six tier vars ``get_model()`` reads, plus the D-0014 fallback var. A value
#: on any of these that ``resolve_provider`` maps to ``'openrouter'`` would make
#: OpenRouter the system default again — the regression this slice closes.
_MODEL_ENV_KEYS = frozenset(
    {f"AETHER_MODEL_{t}" for t in ("REASONING", "HEAVY", "STRUCTURED", "FAST", "LIGHT")}
    | {"AETHER_MODEL_FALLBACK"}
)

# Matches `done < /abs/path/.env` in the start scripts (single source of truth
# for which .env the running process actually loads).
_ENV_SOURCE_RE = re.compile(r"^\s*done\s*<\s*(?P<path>\S+)\s*$")


def _model_tier_assignments(path: Path) -> dict[str, str]:
    """Only the ``AETHER_MODEL_*`` tier/fallback key->value pairs from a dotenv
    file. Every other line (including any secret) is skipped, never returned."""
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in _MODEL_ENV_KEYS:
            continue
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def _assert_no_openrouter_default(path: Path) -> None:
    assignments = _model_tier_assignments(path)
    assert assignments, f"{path} declares no AETHER_MODEL_* tier defaults to check"
    offenders = {
        key: value
        for key, value in assignments.items()
        if resolve_provider(value) != "anthropic"
    }
    assert not offenders, (
        f"{path.name} resolves these model tiers to a non-anthropic provider — "
        f"the system default MUST be the operator Anthropic subscription (a bare "
        f"claude-* id), never OpenRouter: {offenders}"
    )


def _served_env_paths() -> list[Path]:
    """Every .env this deployment reads: the repo-root .env plus every path the
    start scripts load. Only existing files are returned."""
    candidates: set[Path] = {_REPO_ROOT / ".env"}
    for script in ("start-api.sh", "start-worker.sh"):
        script_path = _REPO_ROOT / script
        if not script_path.exists():
            continue
        for line in script_path.read_text().splitlines():
            match = _ENV_SOURCE_RE.match(line)
            if match:
                candidates.add(Path(match.group("path")))
    return sorted(p for p in candidates if p.exists())


def test_env_example_declares_anthropic_first_tier_defaults():
    """The committed template that every ``cp .env.example .env`` seeds must
    default every tier — and the fallback — to a bare ``claude-*`` the Anthropic
    subscription serves, so a fresh dev machine / deployment never reintroduces
    OpenRouter as the system default (Finding 2)."""
    _assert_no_openrouter_default(_REPO_ROOT / ".env.example")


def test_live_served_env_files_never_default_to_openrouter():
    """The live ``.env`` this deployment actually reads (``start-api.sh:20`` /
    ``start-worker.sh:20`` + the repo-root ``.env``) must resolve EVERY tier to
    the operator Anthropic subscription — Finding 1's enforcement, so the flip
    is no longer an unenforced 'at land time' step. Skipped only where no served
    ``.env`` exists (e.g. a bare CI checkout)."""
    served = _served_env_paths()
    if not served:
        pytest.skip("no served .env present in this tree")
    for path in served:
        _assert_no_openrouter_default(path)
