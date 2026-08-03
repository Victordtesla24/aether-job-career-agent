"""LIVE proof that SmartRecruiters description coverage CONVERGES (BLOCKER-SR-DETAIL).

Runs the REAL adapter against the REAL SmartRecruiters API twice, persisting each
sweep's results through the REAL ``JobRepository`` upsert the scout uses, and
prints:

* the board's description coverage before and after each sweep;
* the posting ids each sweep spent its detail budget on;
* that the two sweeps enriched DISJOINT sets of postings — i.e. nothing is
  starved permanently by a fixed cap over a stable list order.

Deliberate limits, so this probe cannot distort the board it measures:

* it persists ONLY postings the user's board ALREADY holds. New postings are
  reported but not inserted, because deciding whether a NEW posting belongs on
  the board is the qualification agent's job (``ScoutAgent.run``), not this
  script's.
* it never writes a description it did not fetch from SmartRecruiters in this
  process, and never writes an empty one over a real one.

``fetch_json`` is wrapped only to RECORD which detail URLs the adapter chose to
fetch; the wrapper delegates to the real function and changes no behaviour.

Usage::

    python3 apps/api/scripts/smartrecruiters_convergence_probe.py [user-email] [sweeps]

The email defaults to ``AETHER_CRON_EMAIL``. Run it from the repo root with the
production environment loaded (``DATABASE_URL`` pointing at the live schema).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_connection  # noqa: E402
from app.repositories.job import JobRepository  # noqa: E402
from app.services.dedup import normalize_source_url  # noqa: E402
from app.services.discovery import smartrecruiters_adapter as mod  # noqa: E402

_DETAIL_MARK = "/postings/"


def _user_id(email: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" WHERE lower("email") = lower(%s)', (email,))
            row = cur.fetchone()
    if not row:
        raise SystemExit(f"no such user: {email}")
    return row[0]


def _coverage(user_id: str) -> tuple[int, int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*), count(*) FILTER (WHERE length(btrim("description")) > 0) '
                'FROM "Job" WHERE "userId" = %s AND "source" = %s',
                (user_id, mod.SOURCE),
            )
            total, with_description = cur.fetchone()
    return int(total), int(with_description)


def _existing_urls(user_id: str) -> set[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "sourceUrl" FROM "Job" WHERE "userId" = %s AND "source" = %s '
                'AND "sourceUrl" IS NOT NULL',
                (user_id, mod.SOURCE),
            )
            return {row[0] for row in cur.fetchall()}


def _sweep(user_id: str, index: int) -> tuple[set[str], dict[str, str]]:
    real_fetch_json = mod.fetch_json
    detail_ids: set[str] = set()

    def recording_fetch_json(url: str, timeout: int = 15):
        marker = url.rsplit(_DETAIL_MARK, 1)
        if len(marker) == 2 and "?" not in marker[1]:
            detail_ids.add(marker[1])
        return real_fetch_json(url, timeout=timeout)

    mod.fetch_json = recording_fetch_json
    started = time.monotonic()
    try:
        jobs = mod.SmartRecruitersAdapter().fetch(query="", location="Melbourne")
    finally:
        mod.fetch_json = real_fetch_json
    elapsed = time.monotonic() - started

    known = _existing_urls(user_id)
    repo = JobRepository()
    updated = 0
    url_by_posting: dict[str, str] = {}
    for job in jobs:
        url = normalize_source_url(job.get("sourceUrl"))
        if not url:
            continue
        url_by_posting[url.rsplit("/", 1)[-1]] = url
        if url in known and job.get("description", "").strip():
            repo.create(user_id, job)
            updated += 1

    total, with_description = _coverage(user_id)
    print(
        f"sweep {index}: {len(jobs)} applicable posting(s) returned, "
        f"{len(detail_ids)} detail GET(s), {elapsed:.1f}s wall-clock, "
        f"{updated} existing board row(s) re-persisted with a real description; "
        f"board coverage now {with_description}/{total}"
    )
    return detail_ids, url_by_posting


def main() -> int:
    email = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("AETHER_CRON_EMAIL", "")
    )
    if not email:
        raise SystemExit("usage: smartrecruiters_convergence_probe.py <user-email> [sweeps]")
    if os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR"):
        raise SystemExit(
            "AETHER_DISCOVERY_FIXTURE_DIR is set — this probe must run LIVE, refusing"
        )
    sweeps = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    user_id = _user_id(email)
    total, with_description = _coverage(user_id)
    print(f"user {email}: board coverage before {with_description}/{total} smartrecruiters row(s)")
    print(f"budget/sweep={mod._DETAIL_BUDGET_PER_SWEEP} concurrency={mod._DETAIL_CONCURRENCY}")

    seen: list[set[str]] = []
    urls: dict[str, str] = {}
    for index in range(1, sweeps + 1):
        fetched, url_by_posting = _sweep(user_id, index)
        seen.append(fetched)
        urls.update(url_by_posting)

    board_urls = _existing_urls(user_id)
    for i in range(len(seen)):
        for j in range(i + 1, len(seen)):
            overlap = seen[i] & seen[j]
            on_board = {p for p in overlap if urls.get(p) in board_urls}
            print(
                f"sweeps {i + 1} vs {j + 1}: {len(overlap)} posting(s) fetched twice, "
                f"of which {len(on_board)} are rows ON the board. Only the latter "
                "would be budget wasted in production: the rest are postings this "
                "probe deliberately did not insert, so their text was never "
                "persisted for the cache to find."
            )
    union = set().union(*seen) if seen else set()
    print(f"distinct postings enriched across {sweeps} sweep(s): {len(union)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
