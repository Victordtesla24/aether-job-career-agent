"""Build the Settings ``integrations`` catalog from the adapter registry.

The Job Board Integrations panel must show every known discovery source for
every authenticated user — paid or unpaid, zero Job rows or many. Live
adapters are default-on (``connected``). Compliance-gated and fixture-only
adapters stay visible with an honest ``not_configured`` detail. Inbox alert
provenance (``seek-alert``, …) is never a board row.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def build_integration_rows(
    *,
    availability: Sequence[Mapping[str, Any]],
    live_sources: Mapping[str, Any],
    job_counts: Mapping[str, Mapping[str, Any]],
    display_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Return one settings row per registry source, overlaying Job activity.

    ``availability`` is ``source_availability()`` output.
    ``live_sources`` is the key set of ``build_live_registry()``.
    ``job_counts`` maps source id → ``{"cnt": int, "last_seen": Any}``.
    ``display_names`` maps source id → human label.
    """
    live_keys = frozenset(live_sources.keys())
    rows: list[dict[str, Any]] = []
    for avail in availability:
        source = str(avail["source"])
        available = bool(avail.get("available"))
        reason = avail.get("reason")
        name = display_names.get(source) or (
            source.capitalize() if source.islower() else source
        )
        counts = job_counts.get(source)
        cnt = int(counts["cnt"]) if counts and counts.get("cnt") is not None else 0
        last_seen = counts.get("last_seen") if counts else None

        in_live = source in live_keys
        if available and in_live:
            status = "connected"
            if cnt > 0:
                if last_seen is not None:
                    detail = (
                        f"{cnt} jobs discovered · last sync "
                        f"{str(last_seen)[:16]} UTC"
                    )
                else:
                    detail = f"{cnt} jobs discovered"
            else:
                detail = "Default on · 0 jobs discovered"
        else:
            status = "not_configured"
            detail = str(reason) if reason else "Not currently active"

        rows.append(
            {
                "source": source,
                "name": name,
                "status": status,
                "detail": detail,
            }
        )
    return rows


def job_counts_from_source_rows(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    known_sources: frozenset[str],
) -> dict[str, dict[str, Any]]:
    """Keep only registry sources; drop alert provenance (``*-alert``, …)."""
    out: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        source = row.get("source")
        if not source or source not in known_sources:
            continue
        out[str(source)] = {
            "cnt": row.get("cnt", 0),
            "last_seen": row.get("last_seen"),
        }
    return out


def merge_last_sync_from_status(
    job_counts: dict[str, dict[str, Any]],
    status_rows: Sequence[Mapping[str, Any]],
) -> None:
    """If a scout ran but persisted 0 jobs, still surface lastSyncAt when useful.

    Only fills ``last_seen`` when the Job overlay has no timestamp yet and the
    status row has one — does not invent job counts.
    """
    for row in status_rows:
        source = row.get("source")
        if not source:
            continue
        key = str(source)
        last_sync: Optional[Any] = row.get("lastSyncAt")
        if last_sync is None:
            continue
        existing = job_counts.get(key)
        if existing is None:
            job_counts[key] = {"cnt": 0, "last_seen": last_sync}
        elif existing.get("last_seen") is None:
            existing["last_seen"] = last_sync
