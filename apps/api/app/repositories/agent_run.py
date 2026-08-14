"""AgentRun repository — execution audit trail (P2-S08)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "agentName", "status", "input", "output", "error", '
    '"costUsd", "startedAt", "completedAt", "createdAt"'
)

#: Rows that are still ``running`` but that no live process owns any more
#: (CRITICAL-1). TWO disjoint arms, and the split is the whole safety argument:
#:
#:   * ``heartbeatAt IS NOT NULL`` — the owning process DID stamp progress at
#:     least once, so a missing recent stamp is positive evidence that it died.
#:     Reconciled on heartbeat staleness alone, never on age: a legitimately
#:     long run keeps stamping and is therefore untouchable however old it gets.
#:   * ``heartbeatAt IS NULL`` — no stamp was EVER recorded (the row predates
#:     this watchdog, or its process died before execution began). There is no
#:     liveness evidence either way, so the generous wall-clock ceiling applies.
#:
#: Both timestamps are compared with ``NOW()`` so the naive ``timestamp``
#: columns round-trip through exactly the same server ``TimeZone`` conversion
#: that wrote them — self-consistent regardless of what that setting is.
_ABANDONED_PREDICATE = '''
    "status" = 'running'::"AgentRunStatus"
    AND (
        ("heartbeatAt" IS NOT NULL
         AND "heartbeatAt" < NOW() - make_interval(secs => %s))
        OR
        ("heartbeatAt" IS NULL
         AND COALESCE("startedAt", "createdAt")
             < NOW() - make_interval(secs => %s))
    )
'''

_heartbeat_column_ready = False


def ensure_heartbeat_column() -> None:
    """Additive, idempotent DDL for ``AgentRun.heartbeatAt`` (CRITICAL-1).

    ``AgentRun`` is Prisma-managed (``packages/db/src/schema.prisma``) and the
    column is declared there too; this lazy ``ADD COLUMN IF NOT EXISTS`` is the
    same belt-and-braces pattern ``user_provider_credential`` already uses for
    ``billingAuditJson``, so a deploy that has not re-run Prisma still gets a
    working watchdog. Documentary mirror:
    ``apps/api/migrations/0026_agent_run_heartbeat.sql``.

    ``timestamp`` (not ``timestamptz``) deliberately matches the existing
    ``startedAt``/``completedAt`` columns so every comparison in this module is
    against columns written the same way.
    """
    global _heartbeat_column_ready
    if _heartbeat_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'ALTER TABLE "AgentRun" '
                'ADD COLUMN IF NOT EXISTS "heartbeatAt" timestamp'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AgentRun_status_heartbeatAt_idx" '
                'ON "AgentRun" ("status", "heartbeatAt")'
            )
        conn.commit()
    _heartbeat_column_ready = True


_link_columns_ready = False
_policy_columns_ready = False
_quality_columns_ready = False


def ensure_agent_run_link_columns() -> None:
    """Additive, idempotent DDL for ``AgentRun.applicationId`` / ``AgentRun.jobId``
    (U-AX instrumentation item 1).

    An ``AgentRun`` row recorded WHICH agent ran and what it cost, but had no FK
    to the job or application it acted on — so "how did this agent's runs affect
    this application's outcome?" was unanswerable, and the per-agent
    orchestration view had nothing to correlate on. Both columns are plain
    nullable ``text`` (not enforced FKs): runs legitimately exist with no job
    (``scout``, ``storyExtractor``) and a deleted job must never make a
    historical audit row un-insertable or vanish.

    NULL on every pre-existing row is the honest value — those runs' targets
    were never recorded, so no backfill UPDATE is performed. Lazy DDL per
    ADR-TR-1, same pattern as :func:`ensure_heartbeat_column`.
    """
    global _link_columns_ready
    if _link_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "applicationId" text'
            )
            cur.execute('ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "jobId" text')
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AgentRun_jobId_idx" '
                'ON "AgentRun" ("jobId")'
            )
        conn.commit()
    _link_columns_ready = True


def ensure_agent_run_policy_columns() -> None:
    """Additive, idempotent DDL for ``AgentRun.policyTier`` / ``metricSnapshot``
    (U-AX build spec item 2b — per-run policy visibility).

    ``policyTier`` (text) is the rigor tier this run executed at, and
    ``metricSnapshot`` (jsonb) is the EXACT metric snapshot the policy consumed
    to pick it. Storing the snapshot — not just the tier — is what makes the
    run card's "policy inputs consumed" honest and reconstructable months
    later, when the underlying metrics have moved on.

    NULL on every pre-existing row is correct: those runs predate the policy
    loop and were not governed by a tier. No backfill UPDATE is performed;
    stamping them with today's tier would claim a decision that never happened.
    """
    global _policy_columns_ready
    if _policy_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "policyTier" text'
            )
            cur.execute(
                'ALTER TABLE "AgentRun" '
                'ADD COLUMN IF NOT EXISTS "metricSnapshot" jsonb'
            )
        conn.commit()
    _policy_columns_ready = True


def ensure_agent_run_quality_columns() -> None:
    """Additive, idempotent DDL for the U2c quality-gate instrumentation.

    ``qualityAttempts`` (jsonb) is the per-attempt trail of ONE run — how many
    attempts it made, each attempt's own real score and gate verdict, how many
    of those were the gate's bounded extra attempts, and why it stopped.
    ``qualityGateState`` (text) is the run's terminal gate state — ``passed``,
    ``below_floor``, or NULL for a run the gate never judged.

    Why a column and not just ``AgentRun.output``: the Supervisor's directive
    loop (ADR-AGI-2) selects runs BY this state ("show me every run that
    terminated below the floor, and what it tried"), which a nested key inside
    a free-form output blob cannot serve without scanning every row.

    NULL on every pre-existing row is correct and is what the "no gate, no
    claim" test pins: those runs predate the gate, and stamping them with a
    state would assert a judgement that was never made. No backfill.
    """
    global _quality_columns_ready
    if _quality_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'ALTER TABLE "AgentRun" '
                'ADD COLUMN IF NOT EXISTS "qualityAttempts" jsonb'
            )
            cur.execute(
                'ALTER TABLE "AgentRun" '
                'ADD COLUMN IF NOT EXISTS "qualityGateState" text'
            )
        conn.commit()
    _quality_columns_ready = True


#: Terminal gate states stamped on ``AgentRun.qualityGateState``.
GATE_STATE_PASSED = "passed"
GATE_STATE_BELOW_FLOOR = "below_floor"


def quality_instrumentation(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """The per-attempt trail + terminal state for ONE run's output, or ``None``.

    PURE: reads only what the agent already produced. It never re-scores, never
    re-judges and never fills a gap with a placeholder — a run whose output
    carries no gate verdict yields ``None``, and the columns stay NULL.

    Both artifact families are read from the shape their agent already returns:
    the tailoring agent's ``iterations`` + ``tailoringSummary``, and the
    cover-letter agent's ``quality.passes`` + ``quality.qualityGate``.
    """
    out = output or {}
    summary = out.get("tailoringSummary")
    quality = out.get("quality")
    attempts_raw: list[Any] = []
    # ``belowQualityFloor`` is the marker that the gate actually JUDGED this
    # run — it is written by the same builder that writes the verdict, and only
    # by it. Its ABSENCE (a discovery run, a legacy output shape) is what keeps
    # the columns NULL instead of inventing a state.
    if isinstance(summary, dict) and "belowQualityFloor" in summary:
        source, gate_summary = out.get("iterations"), summary
    elif isinstance(quality, dict) and "belowQualityFloor" in quality:
        source, gate_summary = quality.get("passes"), quality
    else:
        return None
    if isinstance(source, list):
        attempts_raw = source

    per_attempt: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts_raw, start=1):
        if not isinstance(attempt, dict):
            continue
        gate = attempt.get("qualityGate")
        gate = gate if isinstance(gate, dict) else {}
        per_attempt.append(
            {
                "iteration": attempt.get("iteration", index),
                "stage": attempt.get("stage"),
                "score": attempt.get("score", attempt.get("overall")),
                "gatePassed": gate.get("passed"),
                "failingLabels": gate.get("failingLabels") or [],
            }
        )

    below = bool(gate_summary.get("belowQualityFloor"))
    return {
        "state": GATE_STATE_BELOW_FLOOR if below else GATE_STATE_PASSED,
        "payload": {
            "attempts": len(per_attempt),
            "perAttempt": per_attempt,
            "stopReason": gate_summary.get("stopReason"),
            "gateAttemptsUsed": gate_summary.get("gateAttemptsUsed", 0),
            "belowQualityFloor": below,
            "failingDimensions": gate_summary.get("failingDimensions") or [],
        },
    }


def run_link_fields(input_: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """``(job_id, application_id)`` for a run, read off its own params.

    The params dict IS the run's declared target — every job-scoped agent is
    dispatched with ``job_id`` (``routers/agents.py::_require_job_id``) and the
    submission agent with ``application_id``. Deriving the columns here rather
    than at each of the two ``start()`` call sites means a new dispatch path
    cannot forget to populate them. Both spellings are accepted because the
    async worker round-trips params through JSON where either may appear.
    """
    params = input_ or {}
    job_id = params.get("job_id") or params.get("jobId")
    application_id = params.get("application_id") or params.get("applicationId")
    return (
        str(job_id) if job_id else None,
        str(application_id) if application_id else None,
    )


def run_policy_fields(
    input_: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """``(policy_tier, metric_snapshot)`` for a run, read off its own params.

    ``params["qualityPolicy"]`` is merged in by the single enforcement seam in
    ``routers/agents.py`` (``_with_quality_policy``) upstream of BOTH the sync
    and async dispatch paths, so whatever governed the run is exactly what is
    persisted here — never a second, independently recomputed verdict that
    could disagree with the one the agent actually obeyed.
    """
    policy = (input_ or {}).get("qualityPolicy")
    if not isinstance(policy, dict):
        return None, None
    tier = policy.get("tier")
    snapshot = {
        "tier": tier,
        "triggers": policy.get("triggers"),
        "knobs": policy.get("knobs"),
        "metrics": policy.get("metrics"),
        "thresholds": policy.get("thresholds"),
    }
    return (str(tier) if tier else None), snapshot


class AgentRunRepository:
    def start(
        self, user_id: str, agent_name: str, input_: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Open a ``running`` audit row.

        U-AX: the row additionally carries the run's target (``jobId`` /
        ``applicationId``) and the rigor policy that governed it
        (``policyTier`` / ``metricSnapshot``), both derived from ``input_`` —
        see :func:`run_link_fields` / :func:`run_policy_fields`. All four are
        nullable, so a run with no job and no resolved policy stores NULLs
        rather than placeholders.
        """
        ensure_agent_run_link_columns()
        ensure_agent_run_policy_columns()
        job_id, application_id = run_link_fields(input_)
        policy_tier, metric_snapshot = run_policy_fields(input_)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "AgentRun"
                        ("id", "userId", "agentName", "status", "input", "startedAt",
                         "jobId", "applicationId", "policyTier", "metricSnapshot")
                    VALUES (%s, %s, %s, 'running'::"AgentRunStatus", %s, NOW(),
                            %s, %s, %s, %s)
                    RETURNING {_COLUMNS}
                    ''',
                    (
                        new_id(), user_id, agent_name, json.dumps(input_ or {}),
                        job_id, application_id, policy_tier,
                        json.dumps(metric_snapshot) if metric_snapshot else None,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def last_policy_run_by_agent(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Latest run per agent name INCLUDING its policy/link columns.

        Separate from :meth:`last_run_by_agent` (whose ``_COLUMNS`` projection
        is a contract for existing dashboard readers) so the U-AX policy and
        orchestration surfaces can read the new columns without widening — and
        therefore risking — that shared projection.
        """
        ensure_agent_run_link_columns()
        ensure_agent_run_policy_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT DISTINCT ON ("agentName")
                        "id", "agentName", "status", "output", "error", "costUsd",
                        "startedAt", "completedAt", "createdAt",
                        "jobId", "applicationId", "policyTier", "metricSnapshot"
                    FROM "AgentRun" WHERE "userId" = %s
                    ORDER BY "agentName", "createdAt" DESC
                    ''',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return {row["agentName"]: row for row in rows}

    def policy_tier_history(
        self, user_id: str, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        """``(runs_that_recorded_a_tier, runs_that_did_not)`` — oldest first.

        U-AX build spec item 2(c) ("trend of policy tier over time vs the
        metrics it responds to"). Reads ONLY the already-instrumented columns:
        a run whose ``policyTier`` is NULL predates the policy loop (or failed
        to resolve one) and is EXCLUDED from the series rather than
        back-stamped with today's verdict — but it is counted and returned, so
        the surface can say how much history is genuinely un-instrumented
        instead of implying the series is complete.
        """
        ensure_agent_run_policy_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT "id", "agentName", "createdAt", "policyTier",
                           "metricSnapshot"
                    FROM "AgentRun"
                    WHERE "userId" = %s AND "policyTier" IS NOT NULL
                    ORDER BY "createdAt" ASC, "id" ASC
                    LIMIT %s
                    ''',
                    (user_id, limit),
                )
                rows = rows_to_dicts(cur)
                cur.execute(
                    'SELECT COUNT(*) FROM "AgentRun"'
                    ' WHERE "userId" = %s AND "policyTier" IS NULL',
                    (user_id,),
                )
                without = int((cur.fetchone() or [0])[0] or 0)
        return rows, without

    def finish(
        self,
        run_id: str,
        status: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "AgentRun"
                    SET "status" = %s::"AgentRunStatus", "output" = %s,
                        "error" = %s, "costUsd" = %s, "completedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_COLUMNS}
                    ''',
                    (status, json.dumps(output or {}), error, cost_usd, run_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def record_quality_instrumentation(
        self, run_id: str, output: dict[str, Any] | None
    ) -> bool:
        """Stamp this run's quality-gate trail + terminal state. Additive.

        Returns True iff something was written. A run whose output carries no
        gate verdict writes NOTHING — the columns stay NULL rather than
        recording a state nobody measured.
        """
        instrumentation = quality_instrumentation(output)
        if instrumentation is None:
            return False
        ensure_agent_run_quality_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" SET "qualityAttempts" = %s::jsonb, '
                    '"qualityGateState" = %s WHERE "id" = %s',
                    (
                        json.dumps(instrumentation["payload"]),
                        instrumentation["state"],
                        run_id,
                    ),
                )
                written = cur.rowcount > 0
            conn.commit()
        return written

    def heartbeat(self, run_id: str) -> bool:
        """Stamp liveness for a RUNNING run. Returns False once it is terminal.

        The ``status = 'running'`` predicate is what makes the heartbeat loop
        self-terminating and makes a stamp on an already-reconciled run
        impossible — a heartbeat can never resurrect a finished row.
        """
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" SET "heartbeatAt" = NOW() '
                    'WHERE "id" = %s AND "status" = \'running\'::"AgentRunStatus"',
                    (run_id,),
                )
                stamped = cur.rowcount > 0
            conn.commit()
        return stamped

    def count_abandoned(
        self, heartbeat_stale_seconds: float, max_run_seconds: float
    ) -> int:
        """How many ``running`` rows currently have nothing alive behind them."""
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT COUNT(*) FROM "AgentRun" WHERE {_ABANDONED_PREDICATE}',
                    (heartbeat_stale_seconds, max_run_seconds),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0]) if row else 0

    def list_abandoned(
        self,
        heartbeat_stale_seconds: float,
        max_run_seconds: float,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Abandoned ``running`` rows plus the numbers the honest error cites."""
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT "id", "userId", "agentName", "startedAt", "createdAt",
                           "heartbeatAt",
                           EXTRACT(EPOCH FROM (
                               NOW() - COALESCE("startedAt", "createdAt")
                           )) AS "ageSeconds",
                           CASE WHEN "heartbeatAt" IS NULL THEN NULL ELSE
                               EXTRACT(EPOCH FROM (NOW() - "heartbeatAt"))
                           END AS "heartbeatAgeSeconds"
                    FROM "AgentRun"
                    WHERE {_ABANDONED_PREDICATE}
                    ORDER BY COALESCE("startedAt", "createdAt") ASC
                    LIMIT %s
                    ''',
                    (heartbeat_stale_seconds, max_run_seconds, limit),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows

    def fail_abandoned(self, run_id: str, error: str) -> bool:
        """Atomically fail ONE abandoned run. First-terminal-wins.

        The ``status = 'running'`` guard means a reconciler racing a worker that
        is finishing the very same run loses cleanly: whoever writes the
        terminal state first wins and the other observes ``False``. The row is
        never deleted and is never marked ``completed`` — an abandoned run
        produced no output, and saying otherwise would be a fabrication.
        """
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" '
                    'SET "status" = \'failed\'::"AgentRunStatus", "error" = %s, '
                    '    "completedAt" = NOW() '
                    'WHERE "id" = %s AND "status" = \'running\'::"AgentRunStatus"',
                    (error, run_id),
                )
                won = cur.rowcount > 0
            conn.commit()
        return won

    def set_billing_audit(
        self, run_id: str, audit: dict[str, Any]
    ) -> None:
        """Persist the billing-provenance audit for a run (GAP-D3).

        Writes the additive ``billingAuditJson`` column (created by the lazy DDL
        in ``user_provider_credential._ensure_user_agent_tables``). Best-effort:
        a missing column must never fail an otherwise-successful run, so the
        caller guards this.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" SET "billingAuditJson" = %s WHERE "id" = %s',
                    (json.dumps(audit), run_id),
                )
            conn.commit()

    def list_recent(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "AgentRun" WHERE "userId" = %s '
                    'ORDER BY "createdAt" DESC LIMIT %s',
                    (user_id, limit),
                )
                return rows_to_dicts(cur)

    def get_by_id(self, run_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "AgentRun" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (run_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def last_run_by_agent(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Latest run per agent name for the dashboard's agent grid."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT DISTINCT ON ("agentName") {_COLUMNS}
                    FROM "AgentRun" WHERE "userId" = %s
                    ORDER BY "agentName", "createdAt" DESC
                    ''',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return {row["agentName"]: row for row in rows}

    def recent_runs_by_agent(
        self, user_id: str, window: int = 3
    ) -> dict[str, list[dict[str, Any]]]:
        """The most-recent ``window`` runs per agent name, newest-first.

        Backs the windowed, transient-tolerant agent status on the Agents
        screen (ML-agents-err-001): the catalog must tell a one-off transient
        upstream blip apart from chronic breakage, which needs the last N runs
        per agent — not just the single latest that ``last_run_by_agent``
        returns. Additive; ``last_run_by_agent`` and its callers are unchanged.
        Same column set as the other reads, scoped to the caller's own runs.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT {_COLUMNS} FROM (
                        SELECT {_COLUMNS},
                               ROW_NUMBER() OVER (
                                   PARTITION BY "agentName"
                                   ORDER BY "createdAt" DESC
                               ) AS _rn
                        FROM "AgentRun" WHERE "userId" = %s
                    ) ranked
                    WHERE _rn <= %s
                    ORDER BY "agentName", "createdAt" DESC
                    ''',
                    (user_id, window),
                )
                rows = rows_to_dicts(cur)
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["agentName"], []).append(row)
        return result
