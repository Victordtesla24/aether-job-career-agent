"""MODELS-LIVE — failing tests for two err-001 hardening observations found
during test-authorship on top of the keyword-only classifier landed at
commit 15c8aea ("fix(models-live): rework err-001 to keyword-only transient
classifier").

Sibling to ``test_ml_agents_err_001.py`` (kept separate so none of the 9
already-passing tests there are touched). This file must be run under the
same shared ``aether_test`` schema lock as the rest of the suite:
    flock /tmp/aether-pytest.lock -- python -m pytest \
        tests/test_ml_agents_err_001_obs.py -v

No production code is modified by this file — a fixer session addresses
both defects; this file only proves they exist.

---------------------------------------------------------------------------
OBS-A — DIGIT-KEYWORD CUID/IDENTIFIER COLLISION
---------------------------------------------------------------------------
``_is_transient_failure`` (apps/api/app/routers/agents.py:1786) matches
``_TRANSIENT_FAILURE_KEYWORDS`` — which includes the bare digit strings
"429", "502", "503", "504" — as an unanchored substring anywhere in the
lower-cased ``run["error"]``:

    error = (run.get("error") or "").lower()
    return any(keyword in error for keyword in _TRANSIENT_FAILURE_KEYWORDS)

A GENUINE (non-transient) failure whose message happens to embed one of
those digit runs inside an unrelated identifier — a cuid, a record id, a
field name — is wrongly classified transient and the card is shown
"active", hiding a real failure from the operator. This is the same class
of over-suppression bug the keyword-only rework was meant to fix (masking
genuine breakage), just via a different vector (digit collision instead of
the old costUsd-first heuristic).

---------------------------------------------------------------------------
OBS-B — GET /agents (list_agents) STATUS CONSISTENCY WITH /agents/catalog
---------------------------------------------------------------------------
Investigated both endpoints (apps/api/app/routers/agents.py):

  * ``GET /agents/catalog`` → ``agent_catalog()`` (~line 1806). Per-agent
    ``status`` is one of ``"active" | "paused" | "error" | "planned"``,
    derived via the windowed, keyword-only transient classifier
    (``_is_transient_failure`` + the 3-consecutive "chronic" guard) over
    ``AgentRunRepository.recent_runs_by_agent`` (last 3 runs/agent). A lone
    transient-worded failure on an otherwise-healthy agent is NOT painted
    "error" — it shows "active".

  * ``GET /agents`` → ``list_agents()`` (~line 1293). Per-agent ``status``
    is the RAW ``AgentRun.status`` enum value verbatim
    (``"queued" | "running" | "completed" | "failed"``, or the synthetic
    ``"idle"`` when there is no run at all) from
    ``AgentRunRepository.last_run_by_agent`` (single latest run/agent). NO
    transient classification, NO windowing — it is a bare passthrough:

        agents.append({
            "name": name,
            "status": run["status"] if run else "idle",
            ...
        })

  Both endpoints read the SAME underlying ``AgentRun`` rows for the same
  ``userId``/``agentName``, so there is no data-source skew — only a
  classification skew. The two vocabularies are NOT identical strings
  ("active"/"error" vs. "completed"/"failed"/"queued"/"running"/"idle"), so
  "consistent" here is defined SEMANTICALLY, matching the brief:
    - catalog "error"  ⇔ hard-failed
    - list    "failed" ⇔ hard-failed
  A transient blip must be NOT-hard-failed on both; a genuine failure must
  be hard-failed on both.

  The Agents screen (Orchestration.tsx) reads ``summary.status`` from this
  exact ``GET /agents`` list (via ``AgentSummary``) — so today, the instant
  a transient upstream blip lands, the Agents-screen catalog cards read
  healthy ("active") while the very same agent's orchestration node/summary
  reads hard-failed ("failed") — the operator-visible inconsistency this
  observation targets.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.db import new_id

# Same agent the primary err-001 RCA used: Resume Tailoring Agent.
_BACKEND = "tailor"
_CATALOG_KEY = "resumeTailoring"

_GENUINE_ERROR = (
    "KeyError: 'summary' — resume section missing required field during "
    "tailoring"
)


def _seed_run(
    cur,
    user_id: str,
    *,
    status: str,
    error: str | None = None,
    cost_usd: float | None = None,
    created_at: datetime,
    agent_name: str = _BACKEND,
) -> None:
    """Insert one AgentRun row. Mirrors the seeding helper in
    test_ml_agents_err_001.py (kept duplicated rather than imported so this
    file has no import-time coupling to the sibling module).
    """
    cur.execute(
        '''
        INSERT INTO "AgentRun"
            ("id", "userId", "agentName", "status", "error", "costUsd",
             "output", "startedAt", "completedAt", "createdAt")
        VALUES (%s, %s, %s, %s::"AgentRunStatus", %s, %s, %s::jsonb,
                %s, %s, %s)
        ''',
        (
            new_id(), user_id, agent_name, status, error, cost_usd,
            json.dumps({}), created_at, created_at, created_at,
        ),
    )


def _catalog_entry(client, auth_headers, key: str) -> dict:
    res = client.get("/agents/catalog", headers=auth_headers)
    assert res.status_code == 200, res.text
    by_key = {a["key"]: a for a in res.json()["agents"]}
    assert key in by_key, f"{key!r} missing from catalog: {sorted(by_key)}"
    return by_key[key]


def _list_agents_entry(client, auth_headers, name: str) -> dict:
    res = client.get("/agents", headers=auth_headers)
    assert res.status_code == 200, res.text
    by_name = {a["name"]: a for a in res.json()}
    assert name in by_name, f"{name!r} missing from GET /agents: {sorted(by_name)}"
    return by_name[name]


# ---------------------------------------------------------------------------
# OBS-A — digit-keyword substring collision with a genuine failure's own
# embedded identifier (cuid / field name / record id)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "genuine_message,embedded_digit_keyword",
    [
        # Realistic cuid (Prisma default id shape: c + 24 lowercase alnum)
        # that happens to contain "429" as a run of digits inside the id,
        # not as a standalone HTTP-status token.
        ("Job c429k2j9x0000ab12cd34ef56 not found", "429"),
        # Realistic record-id collision on "502".
        ("Reference id ref502k9m0000ab12cd34ef56 not found in database", "502"),
        # Realistic field-name collision on "503" (KeyError-style genuine
        # agent-logic failure — never transient wording).
        ("KeyError: 'field_503_value' missing from tailoring payload", "503"),
        # Realistic field-name collision on "504", deliberately avoiding the
        # separate "timeout" keyword substring (e.g. NOT "...timeout_504...").
        ("Field validation error: attribute_504_code is invalid", "504"),
    ],
)
def test_genuine_failure_with_digit_embedded_in_identifier_shows_error(
    client, auth_headers, test_user_id, db_session,
    genuine_message, embedded_digit_keyword,
):
    """FAILS NOW (OBS-A): ``_is_transient_failure`` matches "429"/"502"/
    "503"/"504" as a bare, unanchored substring anywhere in the lower-cased
    error message — including inside a cuid/record-id/field-name that has
    nothing to do with an HTTP status or transient upstream signal. Each
    ``genuine_message`` here is a GENUINE (non-transient) agent-logic
    failure that merely happens to embed the digit run
    ``embedded_digit_keyword`` inside an identifier, and contains no other
    transient-keyword substring ("temporarily unavailable" / "rate limit" /
    "rate-limited" / "timeout" / "timed out" / "overloaded" /
    "service unavailable" / "try again") — verified by construction.

    Expected (post-fix, boundary-anchored) contract: a genuine failure must
    surface as ``status == "error"`` regardless of digits embedded in an
    unrelated identifier.

    Actual (current 15c8aea, keyword-only substring match): the digit run
    matches ``_TRANSIENT_FAILURE_KEYWORDS`` as a plain substring, so
    ``_is_transient_failure`` wrongly returns True and the catalog shows
    "active" — hiding a genuine failure behind a healthy-looking card.
    """
    # Sanity: confirm the fixture message contains ONLY the intended digit
    # collision and no other transient keyword, so a failure here can only
    # be attributed to the digit-substring bug under test.
    from app.routers.agents import _TRANSIENT_FAILURE_KEYWORDS

    lowered = genuine_message.lower()
    matched = [kw for kw in _TRANSIENT_FAILURE_KEYWORDS if kw in lowered]
    assert matched == [embedded_digit_keyword], (
        f"fixture message {genuine_message!r} matches transient keywords "
        f"{matched!r}, expected only [{embedded_digit_keyword!r}] — fixture "
        "is not isolating the digit-collision bug cleanly"
    )

    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed", error=genuine_message, cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "error", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} for a GENUINE "
        f"failure {genuine_message!r} that merely embeds the digit run "
        f"{embedded_digit_keyword!r} inside an identifier — "
        "_is_transient_failure's unanchored substring match wrongly treats "
        "this as a transient upstream signal (429/502/503/504 anywhere in "
        "the message) and hides real breakage behind an 'active' card "
        "(ML-agents-err-001 OBS-A: digit-keyword cuid/identifier collision)"
    )


def test_real_transient_5xx_message_still_shows_active(
    client, auth_headers, test_user_id, db_session,
):
    """GUARD (must keep PASSING both now and after the OBS-A boundary-
    anchoring fix): a REAL transient upstream signal — "HTTP 503 Service
    Unavailable", where "503" is a standalone token, not embedded in an
    identifier, and the message also independently matches the
    "service unavailable" keyword phrase — must still classify transient
    and show "active". This guards against an over-correction that
    boundary-anchors "503" so aggressively it stops matching genuine
    provider 5xx wording too.
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed", error="HTTP 503 Service Unavailable",
            cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "active", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} for a genuine "
        "transient upstream 5xx message ('HTTP 503 Service Unavailable') — "
        "a boundary-anchoring fix for OBS-A must not stop matching real "
        "standalone HTTP-status tokens"
    )


# ---------------------------------------------------------------------------
# OBS-B — GET /agents (list_agents) status consistency with /agents/catalog
# ---------------------------------------------------------------------------


def _catalog_is_hard_failed(status: str) -> bool:
    """Catalog vocabulary: "error" is the only hard-failed state."""
    return status == "error"


def _list_agents_is_hard_failed(status: str) -> bool:
    """list_agents (raw AgentRun.status) vocabulary: "failed" is the only
    hard-failed state ("queued"/"running"/"completed"/"idle" are not).
    """
    return status == "failed"


def test_list_agents_transient_failure_not_reported_as_hard_failure(
    client, auth_headers, test_user_id, db_session,
):
    """FAILS NOW (OBS-B): seeds the agent's most-recent run as a TRANSIENT
    failure ("temporarily unavailable", costUsd=None — the exact live-RCA
    shape). ``GET /agents/catalog`` correctly treats this as not-hard-failed
    (status "active", proven by the sibling suite's test 1). But
    ``GET /agents`` (list_agents) is a bare passthrough of the raw
    ``AgentRun.status`` enum — it has no transient classification at all —
    so it reports the SAME agent's SAME run as ``status == "failed"``
    (hard-failed). The Agents screen's Orchestration view reads
    ``summary.status`` from this exact list, so the same agent looks
    healthy in the catalog grid and hard-failed in the orchestration
    node/summary at the same instant, for the same underlying blip.

    Expected (post-fix) contract: list_agents' reported status for this
    agent must be semantically NOT-hard-failed, consistent with the
    catalog's "active".
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed",
            error="The AI service is temporarily unavailable. Please try again in a moment.",
            cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    catalog_entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    list_entry = _list_agents_entry(client, auth_headers, _BACKEND)

    # Sanity anchor: the catalog side of this is already correct (proven
    # independently by the sibling suite) — isolates the failure to the
    # list_agents side under test.
    assert catalog_entry["status"] == "active", (
        f"precondition failed: {_CATALOG_KEY} catalog status = "
        f"{catalog_entry['status']!r}, expected 'active' — cannot isolate "
        "the list_agents consistency defect if the catalog side itself "
        "regressed"
    )

    assert not _list_agents_is_hard_failed(list_entry["status"]), (
        f"GET /agents reports {_BACKEND!r} status={list_entry['status']!r} "
        "(hard-failed) for the SAME transient blip that "
        f"GET /agents/catalog correctly reports as {catalog_entry['status']!r} "
        "(not hard-failed) for the SAME agent/run — list_agents is a bare "
        "passthrough of the raw AgentRun.status with no transient "
        "classification, so the Agents screen (catalog cards) and the "
        "Orchestration view (summary.status from GET /agents) disagree "
        "about whether this agent is healthy (ML-agents-err-001 OBS-B)"
    )

    assert _catalog_is_hard_failed(catalog_entry["status"]) == \
        _list_agents_is_hard_failed(list_entry["status"]), (
        "semantic status mismatch between endpoints for the same agent/run: "
        f"catalog={catalog_entry['status']!r} "
        f"(hard_failed={_catalog_is_hard_failed(catalog_entry['status'])}) "
        f"vs list_agents={list_entry['status']!r} "
        f"(hard_failed={_list_agents_is_hard_failed(list_entry['status'])}) "
        "(ML-agents-err-001 OBS-B)"
    )


def test_list_agents_genuine_failure_reported_consistently_as_hard_failure(
    client, auth_headers, test_user_id, db_session,
):
    """GUARD (must keep PASSING both now and after the OBS-B fix): a
    GENUINE (non-transient) failure is already reported hard-failed by
    BOTH endpoints today — catalog "error", list_agents raw "failed" — so
    there is no regression risk here; a fix for the transient case must not
    accidentally suppress this genuine case on the list_agents side.
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed", error=_GENUINE_ERROR, cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    catalog_entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    list_entry = _list_agents_entry(client, auth_headers, _BACKEND)

    assert catalog_entry["status"] == "error", (
        f"precondition failed: {_CATALOG_KEY} catalog status = "
        f"{catalog_entry['status']!r}, expected 'error' for a genuine "
        "failure"
    )
    assert list_entry["status"] == "failed", (
        f"GET /agents reports {_BACKEND!r} status={list_entry['status']!r} "
        "for a genuine failure, expected raw 'failed'"
    )
    assert _catalog_is_hard_failed(catalog_entry["status"]) == \
        _list_agents_is_hard_failed(list_entry["status"]), (
        "genuine-failure guard: catalog and list_agents must agree this "
        f"agent is hard-failed — catalog={catalog_entry['status']!r}, "
        f"list_agents={list_entry['status']!r} (ML-agents-err-001 OBS-B "
        "guard)"
    )
