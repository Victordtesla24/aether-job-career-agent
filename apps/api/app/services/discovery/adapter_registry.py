"""Source-key → adapter-class registry (P2-S02).

Two views:

- ``_ALL_ADAPTERS`` — every adapter that EXISTS in the codebase, including the
  ToS-non-compliant Seek adapter. ``get_adapter_class`` resolves against this so
  fixture tests and the explicit ``AETHER_ENABLE_SEEK`` opt-in can still
  instantiate it.
- ``ADAPTERS`` / ``build_live_registry()`` — the LIVE registry the scout fans
  out over. Seek is EXCLUDED here by default (ADR-P6-SEEK): Seek's ToS and
  robots.txt prohibit automated scraping (seek-tos-check.md verdict
  SCRAPING-PROHIBITED; probe-13 10/10 cards HTTP 403), so no automated
  seek.com.au scraping runs in the sync path. It is re-added ONLY when
  ``AETHER_ENABLE_SEEK`` is explicitly truthy (e.g. a future licensed Seek
  partnership) — default OFF, with the honest reason above.
"""
from __future__ import annotations

import os

from app.services.discovery.adzuna_adapter import AdzunaAdapter
from app.services.discovery.ashby_adapter import AshbyAdapter
from app.services.discovery.base_adapter import BaseAdapter
from app.services.discovery.greenhouse_adapter import GreenhouseAdapter
from app.services.discovery.indeed_adapter import IndeedAdapter
from app.services.discovery.lever_adapter import LeverAdapter
from app.services.discovery.linkedin_adapter import LinkedInAdapter
from app.services.discovery.remoteok_adapter import RemoteOkAdapter
from app.services.discovery.remotive_adapter import RemotiveAdapter
from app.services.discovery.seek_adapter import SeekAdapter
from app.services.discovery.wellfound_adapter import WellfoundAdapter
from app.services.discovery.workable_adapter import WorkableAdapter

#: Sources gated out of the live sync path unless explicitly re-enabled. Seek
#: scraping is ToS-prohibited (ADR-P6-SEEK) — the adapter stays in the codebase
#: but never runs automatically.
_COMPLIANCE_GATED: dict[str, tuple[type[BaseAdapter], str]] = {
    "seek": (SeekAdapter, "AETHER_ENABLE_SEEK"),
}

#: Every known adapter (includes the compliance-gated Seek adapter). Used only
#: by ``get_adapter_class`` — NOT the live scout registry.
_ALL_ADAPTERS: dict[str, type[BaseAdapter]] = {
    # Live compliant sources — these fetch REAL postings in production.
    GreenhouseAdapter.source: GreenhouseAdapter,
    LeverAdapter.source: LeverAdapter,
    AshbyAdapter.source: AshbyAdapter,
    WorkableAdapter.source: WorkableAdapter,
    AdzunaAdapter.source: AdzunaAdapter,  # licensed AU aggregator (env creds)
    RemotiveAdapter.source: RemotiveAdapter,
    RemoteOkAdapter.source: RemoteOkAdapter,
    WellfoundAdapter.source: WellfoundAdapter,
    # ToS-non-compliant — resolvable but excluded from the live registry.
    SeekAdapter.source: SeekAdapter,
    # Legacy fixture-only sources (no live mode; skipped in production).
    LinkedInAdapter.source: LinkedInAdapter,
    IndeedAdapter.source: IndeedAdapter,
}

#: The live registry, minus every compliance-gated source (Seek by default).
_COMPLIANT_ADAPTERS: dict[str, type[BaseAdapter]] = {
    source: cls
    for source, cls in _ALL_ADAPTERS.items()
    if source not in _COMPLIANCE_GATED
}


def _flag_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "").strip().lower() in {"1", "true", "yes", "on"}


def build_live_registry() -> dict[str, type[BaseAdapter]]:
    """The scout's adapter set: compliant sources plus any compliance-gated
    source whose explicit enable flag is truthy (default OFF)."""
    live = dict(_COMPLIANT_ADAPTERS)
    for source, (cls, env_var) in _COMPLIANCE_GATED.items():
        if _flag_enabled(env_var):
            live[source] = cls
    return live


#: Evaluated at import (production sets AETHER_ENABLE_SEEK, if ever, via the
#: process environment before startup). The scout iterates this mapping.
ADAPTERS: dict[str, type[BaseAdapter]] = build_live_registry()


def get_adapter_class(source: str) -> type[BaseAdapter]:
    """Look up the adapter class for a source key; raise on unknown sources.

    Resolves against ALL known adapters (including the compliance-gated Seek
    adapter) so fixture tests and the opt-in path can still instantiate it.
    """
    try:
        return _ALL_ADAPTERS[source]
    except KeyError:
        raise KeyError(
            f"Unknown discovery source '{source}'. Known: {sorted(_ALL_ADAPTERS)}"
        ) from None


def all_sources() -> list[str]:
    """Live compliant sources the scout runs (Seek excluded by default).

    Excludes sources that have NO live-HTTP implementation at all — i.e.
    their adapter inherits ``BaseAdapter._fetch_live``'s ``NotImplementedError``
    stub unmodified (legacy fixture-only adapters such as LinkedIn/Indeed).
    Those stay in ``ADAPTERS`` so the scout can still fan out over them and
    honestly record a per-source "skipped" status at run time, but this
    function's contract is "live" sources ahead of any run, so a source that
    can never actually go live must not be reported as one (ML-audit-source-
    disclosure-001).
    """
    return sorted(
        source
        for source, cls in ADAPTERS.items()
        if cls._fetch_live is not BaseAdapter._fetch_live
    )
