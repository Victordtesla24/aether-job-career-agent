"""MV-resume-studio — honest tailor approval + no silent billed no-op.

Covers the two HIGH/MEDIUM Resume-Studio findings from the MANUAL-VERIFICATION
run (Cluster E):

- MV-resume-studio-001 (HIGH): the tailor run returned ``approvalRequired: true``
  but NEVER created an ApprovalRequest — the gate was decorative. A tailored
  version now opens a REAL pending approval (mirroring the cover-letter flow),
  stays ``pending`` until a human signs off, and the approval decision flips the
  version's ``approvalStatus``.
- MV-resume-studio-003 (MEDIUM): when the fabrication/entailment guards reject
  EVERY proposed rewrite, the old code still created + BILLED a 0-diff "Tailored"
  version indistinguishable from a real change. It now creates NO version, opens
  NO approval, and refunds the run (honest no-op, never billed).

All tests run against the SYNC path (``AETHER_ASYNC_GENERATION=false``, the suite
default); the async worker shares the same service + refund plumbing.
"""
from __future__ import annotations

import pytest

from app.repositories.billing import UsageQuotaRepository
from app.security import decode_access_token


@pytest.fixture()
def user_id(auth_headers) -> str:
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


def _run_tailor(client, auth_headers, job) -> dict:
    resp = client.post(
        "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTailorApprovalIsReal:
    """MV-resume-studio-001: ``approvalRequired: true`` must be backed by a real
    ApprovalRequest, not a decorative flag."""

    def test_tailor_run_opens_a_pending_approval(self, client, auth_headers):
        job = _seed_job(client, auth_headers)
        body = _run_tailor(client, auth_headers, job)

        assert body["changes"] > 0, "test fixture must exercise the changes>0 path"
        # The flag is honest: it is accompanied by a real approval id/status.
        assert body["approvalRequired"] is True
        assert body["approval_id"], "no approval id returned — flag is decorative"
        assert body["approval_status"] == "pending"

        # The approval genuinely exists in the queue, scoped to this tailored
        # version — the exact record the tester found MISSING (8/8 rows were
        # application_submit / cover_letter, never tailor).
        approvals = client.get("/approvals?status=all", headers=auth_headers).json()
        match = [a for a in approvals if a["id"] == body["approval_id"]]
        assert len(match) == 1, "tailor run created no ApprovalRequest row"
        payload = match[0]["payload"]
        assert payload.get("kind") == "resume_tailor"
        assert payload.get("resume_id") == body["resume_id"]
        assert match[0]["status"] == "pending"

    def test_tailored_version_is_pending_until_approved(self, client, auth_headers):
        job = _seed_job(client, auth_headers)
        body = _run_tailor(client, auth_headers, job)

        version = client.get(
            f"/resumes/{body['resume_id']}", headers=auth_headers
        ).json()
        assert version["approvalStatus"] == "pending"

        # Approving the gate flips the version to approved (the gate has teeth).
        resolved = client.post(
            f"/approvals/{body['approval_id']}/approve", headers=auth_headers
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "approved"

        version = client.get(
            f"/resumes/{body['resume_id']}", headers=auth_headers
        ).json()
        assert version["approvalStatus"] == "approved"

    def test_rejecting_tailor_marks_version_rejected(self, client, auth_headers):
        job = _seed_job(client, auth_headers)
        body = _run_tailor(client, auth_headers, job)

        resolved = client.post(
            f"/approvals/{body['approval_id']}/reject", headers=auth_headers
        )
        assert resolved.status_code == 200
        version = client.get(
            f"/resumes/{body['resume_id']}", headers=auth_headers
        ).json()
        assert version["approvalStatus"] == "rejected"

    def test_base_resume_stays_approved(self, client, auth_headers):
        """Backward compatibility: the immutable base (and every pre-existing
        version) is ``approved`` by default so it remains authoritative."""
        job = _seed_job(client, auth_headers)
        body = _run_tailor(client, auth_headers, job)
        version = client.get(
            f"/resumes/{body['resume_id']}", headers=auth_headers
        ).json()
        base = client.get(
            f"/resumes/{version['parentId']}", headers=auth_headers
        ).json()
        assert base["parentId"] is None
        assert base["approvalStatus"] == "approved"

    def test_tailor_and_cover_letter_approvals_do_not_collide(
        self, client, auth_headers
    ):
        """Both artifacts share the ``application_submit`` enum type + the same
        job_id; the kind-scoped idempotency must keep them as SEPARATE pending
        cards (a regression would overwrite one with the other)."""
        job = _seed_job(client, auth_headers)
        tailor = _run_tailor(client, auth_headers, job)
        letter = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert letter.status_code == 200, letter.text

        approvals = client.get("/approvals?status=all", headers=auth_headers).json()
        kinds = [
            (a["payload"] or {}).get("kind")
            for a in approvals
            if a["status"] == "pending"
        ]
        assert "resume_tailor" in kinds
        assert "cover_letter" in kinds
        # The tailor approval survived the cover-letter run (no overwrite).
        still_there = [a for a in approvals if a["id"] == tailor["approval_id"]]
        assert len(still_there) == 1
        assert (still_there[0]["payload"] or {}).get("kind") == "resume_tailor"


class TestNoSilentBilledNoOp:
    """MV-resume-studio-003: a run that applies ZERO net edits must not create a
    version, must not open an approval, and must not be billed."""

    @staticmethod
    def _force_noop(monkeypatch) -> None:
        from app.services.resume_tailor import ResumeTailorService, TailorResult

        def _fake_tailor(self, resume_text, job_description, originals=None,
                         evidence_extra=""):
            bullets = []
            for i, b in enumerate(originals or []):
                if isinstance(b, dict):
                    bullets.append(
                        {"text": b.get("text", ""),
                         "evidenceRef": b.get("evidenceRef") or f"bullet-{i}"}
                    )
                else:
                    bullets.append({"text": b, "evidenceRef": f"bullet-{i}"})
            # Every proposed rewrite was rejected → 0 net changes, bullets ==
            # originals (byte-identical to the parent).
            return TailorResult(
                bullets=bullets,
                changes=0,
                rejected=["Rewrote a bullet the evidence could not verify"],
                originals=[dict(b) for b in bullets],
            )

        monkeypatch.setattr(ResumeTailorService, "tailor", _fake_tailor)

    def test_noop_returns_honest_result_not_a_version(
        self, client, auth_headers, monkeypatch
    ):
        job = _seed_job(client, auth_headers)
        self._force_noop(monkeypatch)

        resp = client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["noChangesApplied"] is True
        assert body["resume_id"] is None
        assert body["changes"] == 0
        # The flag must NOT falsely claim a gate when nothing was produced.
        assert body["approvalRequired"] is False
        assert "not charged" in body["message"].lower()

    def test_noop_creates_no_child_version(self, client, auth_headers, monkeypatch):
        job = _seed_job(client, auth_headers)
        self._force_noop(monkeypatch)
        client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        resumes = client.get("/resumes", headers=auth_headers).json()
        # Only the immutable base exists — no billed no-op "Tailored" version.
        assert all(r["parentId"] is None for r in resumes), (
            "a no-op run created a child version"
        )
        assert not any(
            (r.get("label") or "").startswith("Tailored") for r in resumes
        )

    def test_noop_opens_no_approval(self, client, auth_headers, monkeypatch):
        job = _seed_job(client, auth_headers)
        self._force_noop(monkeypatch)
        client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        approvals = client.get("/approvals?status=all", headers=auth_headers).json()
        assert not any(
            (a["payload"] or {}).get("kind") == "resume_tailor" for a in approvals
        )

    def test_noop_run_is_refunded_not_billed(
        self, client, auth_headers, user_id, monkeypatch
    ):
        job = _seed_job(client, auth_headers)
        self._force_noop(monkeypatch)
        client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        quota = UsageQuotaRepository().get_by_user(user_id)
        # The metered run reserved one slot then refunded it on the no-op path —
        # net zero consumption (the tester's "billed no-op" is gone).
        assert quota is not None
        assert int(quota["runsUsed"]) == 0

    def test_noop_agent_run_audit_row_is_honest_not_failed(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """MV-adv-A-002 (AgentRun audit-row half): ``GET /agents/runs`` is a
        plain-``CurrentUser`` (NOT admin) endpoint rendered verbatim in the
        /dashboard/agents "Recent runs" table (status + error columns), so a
        legitimate full-rejection no-op must not be recorded as
        ``status='failed'`` with a leaked ``'NoChangesApplied: ...'``
        exception-class error string — that would show the run's OWNER a red
        "failed" row with raw internal exception text. ``_execute_reserved_run``
        must record an honest COMPLETED no-op instead (mirrors the HTTP
        response body), matching the async worker's BackgroundJob treatment."""
        job = _seed_job(client, auth_headers)
        self._force_noop(monkeypatch)
        resp = client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

        from app.repositories.agent_run import AgentRunRepository

        runs = AgentRunRepository().list_recent(user_id, limit=5)
        tailor_runs = [r for r in runs if r["agentName"] == "tailor"]
        assert tailor_runs, "no AgentRun row recorded for the tailor no-op"
        run = tailor_runs[0]
        assert run["status"] != "failed", run
        assert run["status"] == "completed"
        error_text = (run.get("error") or "").lower()
        assert "nochangesapplied" not in error_text
        output = run.get("output") or {}
        if isinstance(output, str):
            import json as _json

            output = _json.loads(output)
        assert output.get("noChangesApplied") is True

    def test_pipeline_tolerates_a_noop_tailor(self, client, auth_headers, monkeypatch):
        """A no-op tailor inside the full pipeline must NOT fail the whole run —
        the cover-letter step draws on the base résumé regardless."""
        self._force_noop(monkeypatch)
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        by_agent = {s["agent"]: s["output"] for s in body["steps"]}
        if "tailor" in by_agent:
            # The pipeline reached the tailor step (a top job existed): the tailor
            # step is an honest no-op AND the pipeline still produced the cover
            # letter + its approval rather than crashing.
            assert by_agent["tailor"].get("noChangesApplied") is True
            assert "coverLetter" in by_agent
            assert body["status"] == "awaiting_approval"
            assert body["approval_id"]
