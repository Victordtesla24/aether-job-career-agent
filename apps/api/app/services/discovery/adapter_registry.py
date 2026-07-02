"""Source-key → adapter-class registry (P2-S02)."""
from __future__ import annotations

from app.services.discovery.base_adapter import BaseAdapter
from app.services.discovery.indeed_adapter import IndeedAdapter
from app.services.discovery.linkedin_adapter import LinkedInAdapter
from app.services.discovery.seek_adapter import SeekAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    SeekAdapter.source: SeekAdapter,
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
