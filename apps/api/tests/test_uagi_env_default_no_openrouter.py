"""U-AGI MODEL-DEFAULT config gate — the SERVED env config must NEVER resolve a
model tier to OpenRouter (OWNER DIRECTIVE, 2026-08-14).

Owner directive, verbatim intent: "do not use openrouter api key other than the
22 ai agents; the system default must be anthropic pro subs quota (token saved
in env)."

Finding-1 enforcement. ``llm_client.get_model()`` only applies the
Anthropic-first code default (``_DEFAULT_MODEL_BY_TIER`` / ``FALLBACK_MODEL``)
when ``AETHER_MODEL_<TIER>`` is UNSET. Every ``.env`` a deployment loads sets
those vars EXPLICITLY, so a stale OpenRouter id there silently overrides the
code default in production — which is exactly how the system default stayed
OpenRouter after the code flip. This gate fails loudly if:

  * the committed template ``.env.example`` (always present) resolves any
    ``AETHER_MODEL_*`` tier — or the D-0014 ``AETHER_MODEL_FALLBACK`` — to a
    non-anthropic provider, so ``cp .env.example .env`` can never reseed the
    OpenRouter-as-default problem; and
  * any live served ``.env`` this host actually reads for prod/test/dev
    resolves a tier to OpenRouter.

It is deliberately narrow: only ``AETHER_MODEL_*`` tier/fallback keys are read
from a dotenv file — no other key (and therefore no secret, incl.
``CLAUDE_CODE_OAUTH_TOKEN``) is parsed, returned or surfaced.

Served-path discovery (2026-08-18, SUITE-RED-2). The repo's ``start-api.sh`` /
``start-worker.sh`` launchers are decommissioned-Abacus-host artefacts — they
still ``cd``/``done <`` against ``/home/ubuntu/github_repos/...`` and are not
what any environment on the current Hostinger VPS actually runs. The real
served configs are the ``EnvironmentFile=`` targets of the
``aether-{prod,test,dev}-*`` systemd units (see ``/etc/aether/ENVIRONMENTS.md``
and each unit's ``EnvironmentFile=``): ``/root/prod/app/.env``,
``/root/test/app/.env`` and ``/root/dev/aether-staging/.env``. All three are
``root:600`` — unreadable to the non-root account these tests run as — so this
gate cannot open them; it SKIPS (never silently passes) for any served path it
can positively confirm exists but cannot read, and it never lets a permission
failure surface as a false green **or** as an uncaught crash: CPython's
``pathlib.Path.exists()`` (unlike ``os.path.exists()``) re-raises ``EACCES``
instead of swallowing it — <=3.12 (the interpreter these tests run under);
walking a candidate under an inaccessible ancestor directory (e.g. the stale
``/home/ubuntu`` reference above, on this account) must not crash the test
either, so existence itself is treated as "unknown, not verified" rather than
letting ``PermissionError`` escape as a test-harness error.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import NamedTuple

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


#: The three environments this Hostinger VPS host actually serves, and the
#: exact file each one's systemd unit loads via ``EnvironmentFile=`` (see
#: ``/etc/aether/ENVIRONMENTS.md`` and ``systemctl cat aether-{prod,test,dev}-api``).
#: Not discoverable from ``_REPO_ROOT`` or from the (decommissioned-Abacus)
#: launcher scripts, so listed explicitly — this is the REAL current layout,
#: not a guess.
_VPS_SERVED_ENV_PATHS: tuple[Path, ...] = (
    Path("/root/prod/app/.env"),
    Path("/root/test/app/.env"),
    Path("/root/dev/aether-staging/.env"),
)


class _Unverified(NamedTuple):
    """A served-.env candidate that exists (or might exist) but that this
    account could not read — named explicitly so a skip/warning can say
    exactly what was not checked and why, rather than passing silently."""

    path: Path
    reason: str


def _safe_exists(path: Path) -> bool | None:
    """``Path.exists()``, except a permission failure while merely walking the
    path (e.g. an inaccessible ancestor directory) returns ``None`` — "unknown"
    — instead of propagating. ``pathlib.Path.exists()`` only swallows
    ``ENOENT``/``ENOTDIR``/``ELOOP``, not ``EACCES``, so it re-raises
    ``PermissionError`` where ``os.path.exists()`` would return ``False``; a
    config gate must never crash on that, but it also must not silently
    report "absent" for a path whose existence it never actually established."""
    try:
        return path.exists()
    except PermissionError:
        return None


def _served_env_candidates() -> list[Path]:
    """Every path this deployment's launchers/services load: the real VPS
    served layout, the repo-root ``.env``, plus every path the (legacy) start
    scripts declare. Order is stable; duplicates collapse. No existence or
    readability filtering happens here — that is ``_classify_served_env``'s job,
    so a permission failure here can never crash candidate discovery."""
    candidates: list[Path] = [_REPO_ROOT / ".env", *_VPS_SERVED_ENV_PATHS]
    for script in ("start-api.sh", "start-worker.sh"):
        script_path = _REPO_ROOT / script
        if not script_path.exists():
            continue
        for line in script_path.read_text().splitlines():
            match = _ENV_SOURCE_RE.match(line)
            if match:
                candidates.append(Path(match.group("path")))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _classify_served_env() -> tuple[list[Path], list[_Unverified]]:
    """Split ``_served_env_candidates()`` into paths this account can actually
    read (the invariant gets enforced against these) and paths that exist —
    or whose existence could not even be determined — but that this account
    could not read (each paired with a precise, nameable reason). A candidate
    that is confirmed absent is dropped silently, exactly as before (the CI /
    bare-checkout case)."""
    readable: list[Path] = []
    unverified: list[_Unverified] = []
    for path in _served_env_candidates():
        exists = _safe_exists(path)
        if exists is None:
            unverified.append(
                _Unverified(
                    path,
                    f"cannot determine whether {path} exists: an ancestor "
                    "directory denies traversal to this account (requires "
                    "root, or that ancestor's owner, to verify)",
                )
            )
            continue
        if not exists:
            continue
        try:
            path.read_text()
        except PermissionError:
            mode = oct(path.stat().st_mode & 0o777)
            unverified.append(
                _Unverified(
                    path,
                    f"{path} exists (mode {mode}) but is not readable by this "
                    "account (requires root, or that file's owner, to verify)",
                )
            )
            continue
        readable.append(path)
    return readable, unverified


def test_env_example_declares_anthropic_first_tier_defaults():
    """The committed template that every ``cp .env.example .env`` seeds must
    default every tier — and the fallback — to a bare ``claude-*`` the Anthropic
    subscription serves, so a fresh dev machine / deployment never reintroduces
    OpenRouter as the system default (Finding 2)."""
    _assert_no_openrouter_default(_REPO_ROOT / ".env.example")


def test_live_served_env_files_never_default_to_openrouter():
    """Every served ``.env`` this host actually reads (prod/test/dev's systemd
    ``EnvironmentFile=`` targets, the repo-root ``.env``, and any path the
    legacy start scripts declare) must resolve EVERY tier to the operator
    Anthropic subscription — Finding 1's enforcement, so the flip is no longer
    an unenforced 'at land time' step.

    A served path this account cannot read (prod/test/dev are ``root:600`` on
    this host) is never treated as a silent pass: if NOTHING could be verified
    at all, the test skips loudly, naming every unread path and why. If at
    least one served path WAS readable and verified, the test still surfaces
    (via a visible warning, not silence) any sibling served path it could not
    check, while still failing hard on any readable path that violates the
    invariant. Only a genuinely empty candidate set (e.g. a bare CI checkout
    with no served .env anywhere) skips with the original, unqualified
    reason."""
    verified, unverified = _classify_served_env()
    if not verified and not unverified:
        pytest.skip("no served .env present in this tree")
    for path in verified:
        _assert_no_openrouter_default(path)
    if unverified:
        detail = "; ".join(f"{u.path}: {u.reason}" for u in unverified)
        message = (
            f"{len(unverified)} served .env path(s) were NOT verified against "
            f"the openrouter-default invariant on this host: {detail}"
        )
        if not verified:
            pytest.skip(message)
        warnings.warn(message, stacklevel=1)
