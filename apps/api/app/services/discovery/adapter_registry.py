"""Source-key → adapter-class registry (P2-S02)."""
from __future__ import annotations

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

ADAPTERS: dict[str, type[BaseAdapter]] = {
    # Live sources — these fetch REAL postings in production.
    SeekAdapter.source: SeekAdapter,  # AU jobs via Firecrawl
    GreenhouseAdapter.source: GreenhouseAdapter,
    LeverAdapter.source: LeverAdapter,
    AshbyAdapter.source: AshbyAdapter,
    WorkableAdapter.source: WorkableAdapter,
    RemotiveAdapter.source: RemotiveAdapter,
    RemoteOkAdapter.source: RemoteOkAdapter,
    WellfoundAdapter.source: WellfoundAdapter,
    # Legacy fixture-only sources (no live mode; skipped in production).
    LinkedInAdapter.source: LinkedInAdapter,
    IndeedAdapter.source: IndeedAdapter,
}


def get_adapter_class(source: str) -> type[BaseAdapter]:
    """Look up the adapter class for a source key; raise on unknown sources."""
    try:
        return ADAPTERS[source]
    except KeyError:
        raise KeyError(
            f"Unknown discovery source '{source}'. Known: {sorted(ADAPTERS)}"
        ) from None


def all_sources() -> list[str]:
    return sorted(ADAPTERS)
