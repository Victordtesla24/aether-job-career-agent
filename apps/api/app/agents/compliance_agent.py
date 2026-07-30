"""Compliance Agent — surfaces the guard verdicts the generation agents already
recorded, as a per-artifact compliance report (wave-4A, ADR-AG-1).

HONEST SCOPE. Aether has exactly ONE truthfulness authority: the
fabrication/entailment guards that run INSIDE the tailoring and cover-letter
agents (``app.services.fabrication_guard``, ``resume_tailor.unsupported_*``,
the §10.2 structural checks). This agent does NOT re-verify artifacts with a
second-opinion LLM — no such verifier exists, and inventing one would produce a
"compliance" verdict nothing in the product actually enforces. What it does is
read the verdicts those guards ALREADY persisted on the caller's own
``tailor``/``coverLetter`` :class:`AgentRun` rows and present them per artifact.

Consequences of that scope, all deliberate:

* Deterministic and unmetered — no LLM call, so no spend and no plan-quota
  reservation (the backend is absent from ``_LLM_TIER_BY_BACKEND``).
* Read-only — it writes nothing but its own audit row.
* A run that never reached a verdict (``failed``/``running``/``queued``, or a
  completed row whose output carries no verdict field at all) is reported as an
  honest EXCLUSION, never scored as "clean". Counting an unfinished run as
  compliant would be a fabricated pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.repositories.agent_run import AgentRunRepository

#: Backend agent name -> the artifact its guard verdict is about. These are the
#: ONLY two agents that run a fabrication/entailment guard, so they are the only
#: ones that can have a compliance verdict at all.
_ARTIFACT_BY_AGENT: dict[str, str] = {
    "tailor": "resume",
    "coverLetter": "coverLetter",
}

#: Output keys that prove a guard verdict was actually recorded on the row. A
#: completed run whose output has NONE of them (e.g. an empty ``{}`` written by
#: a legacy/partial path) yields no verdict and is excluded, not passed.
_VERDICT_KEYS: dict[str, tuple[str, ...]] = {
    "tailor": ("rejected", "changes", "noChangesApplied", "resume_id"),
    "coverLetter": (
        "flagged", "cover_letter_id", "coverLetterUnavailable",
        "cover_letter_unavailable",
    ),
}

#: How many of the caller's most recent runs are scanned. Bounded so the report
#: can never turn into an unbounded table scan; ``truncated`` tells the caller
#: honestly when the window was full.
_SCAN_LIMIT = 200


@dataclass
class ArtifactVerdict:
    """One artifact's recorded guard verdict."""

    runId: str
    agentName: str
    artifact: str
    jobId: str | None
    verdict: str  # clean | flagged | withheld
    rejected: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    changesApplied: int | None = None
    detail: str = ""
    ranAt: str | None = None


@dataclass
class ComplianceReport:
    checked: int = 0
    clean: int = 0
    flagged: int = 0
    withheld: int = 0
    skippedNoVerdict: int = 0
    scanned: int = 0
    truncated: bool = False
    artifacts: list[ArtifactVerdict] = field(default_factory=list)
    message: str = ""


def _as_dict(value: Any) -> dict[str, Any]:
    """AgentRun.output is jsonb (psycopg2 -> dict) but older rows / other code
    paths can hand back a JSON string; normalise without ever guessing."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if value in (None, "", {}):
        return []
    return [str(value)]


class ComplianceAgent:
    """Builds a per-artifact compliance report from recorded guard verdicts."""

    def __init__(self, runs: AgentRunRepository | None = None) -> None:
        self._runs = runs or AgentRunRepository()

    def run(self, user_id: str) -> ComplianceReport:
        rows = self._runs.list_recent(user_id, limit=_SCAN_LIMIT)
        report = ComplianceReport(scanned=len(rows), truncated=len(rows) >= _SCAN_LIMIT)
        for row in rows:
            agent = row.get("agentName")
            artifact = _ARTIFACT_BY_AGENT.get(agent or "")
            if artifact is None:
                continue  # no guard runs in this agent — nothing to report
            output = _as_dict(row.get("output"))
            if row.get("status") != "completed" or not any(
                k in output for k in _VERDICT_KEYS[agent]
            ):
                report.skippedNoVerdict += 1
                continue
            verdict = (
                self._tailor_verdict(row, output)
                if agent == "tailor"
                else self._cover_verdict(row, output)
            )
            report.artifacts.append(verdict)
            report.checked += 1
            if verdict.verdict == "clean":
                report.clean += 1
            elif verdict.verdict == "flagged":
                report.flagged += 1
            else:
                report.withheld += 1
        report.message = self._message(report)
        return report

    # -- per-agent verdict derivation ---------------------------------------

    @staticmethod
    def _job_id(row: dict[str, Any]) -> str | None:
        job_id = _as_dict(row.get("input")).get("job_id")
        return str(job_id) if job_id else None

    @staticmethod
    def _ran_at(row: dict[str, Any]) -> str | None:
        stamp = row.get("completedAt") or row.get("createdAt")
        return stamp.isoformat() if hasattr(stamp, "isoformat") else None

    def _tailor_verdict(
        self, row: dict[str, Any], output: dict[str, Any]
    ) -> ArtifactVerdict:
        rejected = _strings(output.get("rejected"))
        try:
            changes = int(output.get("changes") or 0)
        except (TypeError, ValueError):
            changes = 0
        # Every proposed edit rejected (the guard's honest no-op) => the
        # artifact was WITHHELD; some rejected but others applied => flagged.
        if output.get("noChangesApplied") is True or (rejected and changes == 0):
            verdict = "withheld"
        elif rejected:
            verdict = "flagged"
        else:
            verdict = "clean"
        return ArtifactVerdict(
            runId=row["id"],
            agentName="tailor",
            artifact="resume",
            jobId=self._job_id(row),
            verdict=verdict,
            rejected=rejected,
            changesApplied=changes,
            detail=str(output.get("message") or ""),
            ranAt=self._ran_at(row),
        )

    def _cover_verdict(
        self, row: dict[str, Any], output: dict[str, Any]
    ) -> ArtifactVerdict:
        flagged = _strings(output.get("flagged"))
        withheld = bool(
            output.get("coverLetterUnavailable") or output.get("cover_letter_unavailable")
        )
        # ``reason`` is the guard's own entity/issue list already rendered into
        # English by the exception constructors (never verbatim LLM output).
        detail = str(output.get("reason") or output.get("message") or "")
        return ArtifactVerdict(
            runId=row["id"],
            agentName="coverLetter",
            artifact="coverLetter",
            jobId=self._job_id(row),
            verdict="withheld" if withheld else ("flagged" if flagged else "clean"),
            flagged=flagged,
            detail=detail,
            ranAt=self._ran_at(row),
        )

    # -- honest messaging ---------------------------------------------------

    @staticmethod
    def _message(report: ComplianceReport) -> str:
        if report.checked == 0 and report.skippedNoVerdict == 0:
            return (
                "No tailoring or cover-letter runs to audit yet — this report only "
                "surfaces the guard verdicts those runs record, it does not "
                "re-check artifacts itself."
            )
        if report.checked == 0:
            return (
                f"No guard verdict has been recorded yet: "
                f"{report.skippedNoVerdict} tailoring/cover-letter run(s) never "
                "reached a verdict, so there is nothing to audit."
            )
        parts = [
            f"{report.checked} artifact(s) audited: {report.clean} clean, "
            f"{report.flagged} flagged, {report.withheld} withheld."
        ]
        if report.skippedNoVerdict:
            parts.append(
                f"{report.skippedNoVerdict} run(s) excluded — no guard verdict "
                "was recorded for them."
            )
        if report.truncated:
            parts.append(
                f"Only the most recent {_SCAN_LIMIT} runs were scanned."
            )
        return " ".join(parts)
