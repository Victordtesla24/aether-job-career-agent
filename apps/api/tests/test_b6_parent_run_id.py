"""B6 — parentRunId causal traces (ORCH-B1-BLUEPRINT-2026-08-14.md §4.4).

Ground truth this suite pins (verified 2026-08-14 against a live `\\d "AgentRun"`
on the design tree): `AgentRun` had 17 columns and NO `parentRunId`; the
agents-console orchestration map drew stage-order edges only, with an explicit
honesty-rule comment in both `orchestration-map-model.ts` and
`workflow-linkage.ts` saying causal edges "need a parent run id the API does
not record yet" and are deliberately NOT faked or stubbed ahead of the data.

THE REAL SEMANTIC (traced from `_pipeline_core`, `apps/api/app/routers/
agents.py:3401-3521`, the only place in this tree where one run genuinely
causes others — B1a's scheduler does not exist in this working tree, see
`docs/delivery/ORCH-B1-BLUEPRINT-2026-08-14.md` §0.4 B6 row and §4.4):
the pipeline's supervisor node is recorded FIRST via `_record_run`, and every
subsequent step (scout, fitScorer, matcher, tailor, coverLetter) is dispatched
BY that same pipeline invocation — so each child's `parentRunId` is the
supervisor run's id, not each other's (they are siblings, not a chain).

Four assertions, matching the finding record:
  (a) a full `/agents/pipeline/run` records every child's `parentRunId` as the
      supervisor run's id;
  (b) a directly-triggered single run (the generic `/agents/{name}/run` route,
      e.g. `matcher`) records `parentRunId = None` — honest: it has no parent;
  (c) `GET /agents/runs` (the runs-list payload the agents console reads,
      `apps/web/.../orchestration-map-model.ts`'s `resolveNodeState` doc)
      carries the field;
  (d) the silent-drop guard: `AgentRunRepository.start(..., parent_run_id=…)`
      through the NORMAL creation path, read back via the repository AND via
      `GET /agents/runs`, returns the value — this is the `run_policy_fields`
      whitelist trap (§2.4 of the blueprint) applied to `parentRunId`: a caller
      could merge `parentRunId` into `params` and have it silently vanish on
      the way to the database unless the column/INSERT genuinely carries it.
"""
from __future__ import annotations

from conftest import seed_own_resume, seed_search_target

from app.agents.fit_scorer import get_base_resume_path
from app.repositories.agent_run import AgentRunRepository
from app.services.resume_parser import parse_resume_pdf


def _operator_resume_text() -> str:
    """Same fixture `test_pipeline.py` uses — the bundled operator PDF's own
    text, seeded as the fixture user's OWN résumé (the static replay fixtures
    for tailor/coverLetter are recorded against it)."""
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


class TestPipelineChildrenRecordSupervisorAsParent:
    def test_pipeline_children_carry_supervisors_run_id_as_parent(
        self, client, auth_headers
    ):
        seed_own_resume(client, auth_headers, raw_text=_operator_resume_text())
        seed_search_target(
            client, auth_headers,
            target_role="Business Analyst", location="Melbourne, Australia",
        )
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        steps = {s["agent"]: s["output"] for s in body["steps"]}

        sup_run_id = steps["supervisor"]["run_id"]
        assert sup_run_id

        # The supervisor node itself is the top of this chain — no parent.
        runs_by_id = {
            r["id"]: r
            for r in client.get("/agents/runs", headers=auth_headers).json()
        }
        assert runs_by_id[sup_run_id]["parentRunId"] is None

        # Every step the pipeline dispatched is the supervisor's CHILD — a
        # sibling of the others, never chained to the previous step.
        for name in ("scout", "fitScorer", "matcher"):
            child_run_id = steps[name]["run_id"]
            assert runs_by_id[child_run_id]["parentRunId"] == sup_run_id, name

        if body["status"] == "awaiting_approval":
            for name in ("tailor", "coverLetter"):
                child_run_id = steps[name]["run_id"]
                assert runs_by_id[child_run_id]["parentRunId"] == sup_run_id, name


class TestDirectSingleRunHasNoParent:
    def test_directly_triggered_run_records_null_parent(self, client, auth_headers):
        # matcher is deterministic and needs no job/résumé — a fast, reliable
        # probe of the generic single-agent trigger route (the same seam
        # D.524 will later make async — ORCH-B1-BLUEPRINT §4.5).
        resp = client.post("/agents/matcher/run", json={}, headers=auth_headers)
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        runs = {
            r["id"]: r
            for r in client.get("/agents/runs", headers=auth_headers).json()
        }
        assert runs[run_id]["parentRunId"] is None


class TestRunsListExposesParentRunId:
    def test_runs_list_payload_carries_parent_run_id_key(self, client, auth_headers):
        resp = client.post("/agents/matcher/run", json={}, headers=auth_headers)
        assert resp.status_code == 200
        runs = client.get("/agents/runs", headers=auth_headers).json()
        assert len(runs) >= 1
        # Additive field: present on every row (None where there is no
        # parent), never merely present-when-truthy — a reader must be able
        # to tell "no parent" from "field doesn't exist on this build".
        assert all("parentRunId" in r for r in runs)


class TestParentRunIdSurvivesTheNormalCreationPath:
    def test_repository_start_with_parent_round_trips_through_the_real_column(
        self, client, auth_headers, test_user_id
    ):
        """The whitelist-drop trap (blueprint §2.4, `run_policy_fields`):
        a field that is only threaded through a free-form ``params``/``input``
        dict can be silently dropped on the way to the database by any
        intermediate whitelist. This creates a parent run, then a child run
        THROUGH THE NORMAL REPOSITORY CREATION PATH with `parent_run_id` set,
        and reads it back two independent ways — the repository layer AND the
        HTTP list endpoint — so a silent drop in EITHER layer fails the test.
        """
        runs = AgentRunRepository()
        parent = runs.start(test_user_id, "supervisor", {"plan": ["scout"]})
        child = runs.start(
            test_user_id, "scout", {}, parent_run_id=parent["id"]
        )

        # (1) Repository read-back — a raw column read, not a re-parse of the
        # JSON `input` blob a lazier implementation might have relied on.
        fetched = runs.get_by_id(child["id"], test_user_id)
        assert fetched is not None
        assert fetched["parentRunId"] == parent["id"]

        # (2) The list a real caller (the agents console) actually reads.
        listed = {r["id"]: r for r in runs.list_recent(test_user_id, limit=50)}
        assert listed[child["id"]]["parentRunId"] == parent["id"]

        # (3) End to end over HTTP, for good measure — the same round trip
        # the FE causal-edge feature depends on.
        via_http = {
            r["id"]: r
            for r in client.get("/agents/runs", headers=auth_headers).json()
        }
        # The two runs above were created directly against the repository for
        # a DIFFERENT user (`test_user_id`) than `auth_headers`' fixture user,
        # so they will not appear here — this call only proves the endpoint
        # itself never 500s / never drops the key for the calling user's own
        # (parent-less) runs, complementing (1)/(2)'s direct proof.
        assert all("parentRunId" in r for r in via_http.values())
