#!/usr/bin/env python3
"""ML-W4B independent screen-alive proof — interviewPrep -> Interview Center.

WHY THIS EXISTS. Wave-4B (25ccabe + aaadc79) claims the Interview Center's
predicted-questions panel is now fed by a real agent run: before the wave,
``GET /workspaces/interviews/prep`` (apps/api/app/routers/workspaces.py:48-100)
read the most recent ``AgentRun`` whose ``agentName ILIKE '%interview%'`` and
rendered ``output.predictedQuestions``, and NOTHING had ever written such a row,
so the panel was permanently empty. PROD-VERIFY-5A / QA #5a could NOT verify the
claim on production ("no interview to render" — the probe account had no
application at the ``interview`` stage), and the authoring agent (repeatedly
killed by API overloads) never delivered the end-to-end proof.

WHAT THIS PROVES, out of band from the pytest suite it is verifying:
  1. the panel is EMPTY for a user with an interview-stage application and
     stories but no interviewPrep run (so step 3 cannot be a false positive);
  2. ``POST /agents/interviewPrep/run`` with an EMPTY body resolves the job from
     the caller's own most recent interview-stage Application — the exact path
     the Agents-screen Run button takes (``runAgent(AGENT_ROUTE[backend] ??
     backend)`` -> the generic per-name route, no RUN_PARAMS entry);
  3. the SAME questions the run returned are then served by
     ``GET /workspaces/interviews/prep``, i.e. the screen is genuinely alive;
  4. the durable AgentRun row that feeds it really does match the screen's
     ``agentName ILIKE '%interview%'`` predicate;
  5. the story-grounding guard holds on a SECOND run whose model output cites a
     fabricated story handle: the reference and its answer sketch are stripped,
     reported in ``guardActions``, and nothing invented is served to the screen.

HONEST DISCLOSURES (both recorded in the artifact):
  * The LLM call is served from the COMMITTED replay fixture
    (apps/api/tests/fixtures/llm/interview_prep/default.json) via
    ``AETHER_LLM_MODE=replay``. No live model is called — OpenRouter credits are
    exhausted (402) and there is no direct Anthropic key, so a live call would
    fail for reasons unrelated to this wiring. Every DETERMINISTIC post-check in
    the agent, the persistence, and the screen read are fully real.
  * ``AETHER_REQUIRE_PAID_SUBSCRIPTION=false``: the paywall entitlement gate is
    not what is under test, and the proof user has no subscription.

SAFETY. Runs ONLY against a DSN whose ``schema=`` is literally ``aether_test``
(same refusal as scripts/run-tests.sh — see
docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md). It TRUNCATES NOTHING and
touches no pre-existing row: it registers its own fresh user and inserts only
that user's rows, so it is safe to run while other suites share the schema.

Usage:  python3 uat/scripts/models-live-w4b-verify/screen_alive_proof.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    REPO_ROOT / "uat" / "reports" / "evidence" / "models-live"
    / "W4B-SCREEN-ALIVE-PROOF.json"
)

# The corpus the committed replay fixture is grounded in. The agent's guards are
# REAL, so the seeded job + stories must genuinely contain the entities the
# fixture's text uses — otherwise the guard would (correctly) strip everything.
JOB_TITLE = "Senior Platform Engineer"
JOB_COMPANY = "Atlassian"
JOB_LOCATION = "Melbourne, Australia"
JOB_DESCRIPTION = (
    "We are hiring a Senior Platform Engineer to scale our Kubernetes platform "
    "and lead incident response for a payments service. You will own the deploy "
    "pipeline and the on-call rotation, and work with Terraform across our "
    "estate."
)
JOB_REQUIREMENTS = [
    "Kubernetes at scale", "Incident response leadership", "Python", "Terraform",
]
STORY_ONE = {
    "title": "Cut deploy time on the payments platform",
    "situation": (
        "The payments platform at Canvatech took 30 minutes to deploy and "
        "blocked releases."
    ),
    "task": "I owned reducing deploy time without extra headcount.",
    "action": (
        "I migrated the services to Kubernetes and Docker and rebuilt the pipeline."
    ),
    "result": (
        "Deploy time dropped from 30 minutes to 5 minutes and releases went daily."
    ),
    "metrics": {"deployMinutesBefore": 30, "deployMinutesAfter": 5},
    "tags": ["Kubernetes", "Docker"],
}
STORY_TWO = {
    "title": "Led incident response for a cache outage",
    "situation": "A Redis cache outage degraded checkout for two hours at Canvatech.",
    "task": "I coordinated the incident response as the on-call lead.",
    "action": "I ran the incident bridge, restored the cache and wrote the postmortem.",
    "result": "Checkout recovered in 40 minutes and repeat incidents fell to zero.",
    "metrics": {"recoveryMinutes": 40},
    "tags": ["Incident response"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_test_dsn() -> str:
    """DATABASE_URL_TEST from the env or the repo-root .env, WITHOUT sourcing the
    whole file (a production DATABASE_URL there must never leak in here)."""
    dsn = os.environ.get("DATABASE_URL_TEST", "")
    if not dsn:
        env_file = REPO_ROOT / ".env"
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                if line.startswith("DATABASE_URL_TEST="):
                    dsn = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not dsn:
        sys.exit("REFUSING TO RUN: DATABASE_URL_TEST is not set.")
    if "schema=aether_test" not in dsn:
        sys.exit(
            "REFUSING TO RUN: resolved DSN does not carry '?schema=aether_test'. "
            "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md."
        )
    return dsn


def main() -> int:
    dsn = _resolve_test_dsn()
    os.environ["DATABASE_URL"] = dsn
    os.environ["DATABASE_URL_TEST"] = dsn
    # Serve the committed replay fixture instead of a live model (disclosed).
    os.environ["AETHER_LLM_MODE"] = "replay"
    # The paywall entitlement gate is not under test.
    os.environ["AETHER_REQUIRE_PAID_SUBSCRIPTION"] = "false"
    # Keep the run on the synchronous path so the proof observes the run's own
    # response body rather than an enqueue envelope.
    os.environ["AETHER_ASYNC_GENERATION"] = "false"
    # An EPHEMERAL, process-local signing secret: tokens are minted and verified
    # inside this one process, so no real secret is read or written anywhere.
    os.environ["NEXTAUTH_SECRET"] = uuid.uuid4().hex
    # Never touch the real persisted model-price cache from a verification run.
    os.environ.setdefault(
        "AETHER_MODEL_PRICE_CACHE_FILE",
        f"/tmp/aether-w4b-proof-model-price-cache-{os.getpid()}.json",
    )
    # The §14.7 admin-rotation lifespan would UPSERT a phantom owner user.
    os.environ.pop("AETHER_ADMIN_EMAIL", None)
    os.environ.pop("AETHER_ADMIN_PASSWORD_HASH", None)
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

    from fastapi.testclient import TestClient

    from app.db import get_connection
    from app.main import create_app

    ev: dict[str, object] = {
        "run": "ML-W4B-SCREEN-ALIVE-PROOF",
        "role": "fixer-hard (independent verification of wave-4B 25ccabe+aaadc79)",
        "target": "aether_test schema via the real ASGI app (app.main.create_app)",
        "startedAt": _now(),
        "llmMode": "replay — committed fixture "
                   "apps/api/tests/fixtures/llm/interview_prep/default.json "
                   "(no live model: OpenRouter 402, no direct Anthropic key)",
        "paywallGate": "AETHER_REQUIRE_PAID_SUBSCRIPTION=false (not under test)",
        "mutations": "inserts only rows owned by the freshly registered proof "
                     "user; truncates nothing",
        "steps": [],
    }
    steps: list[dict[str, object]] = ev["steps"]  # type: ignore[assignment]

    with TestClient(create_app()) as client:
        # -- a fresh, real user -------------------------------------------------
        email = f"w4b-proof-{uuid.uuid4().hex[:10]}@example.com"
        creds = {"email": email, "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=creds).status_code == 201
        token = client.post("/auth/login", json=creds).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        user_id = client.get("/auth/me", headers=headers).json()["id"]
        ev["proofUser"] = {"id": user_id, "email": email}

        # -- seed a real Job + interview-stage Application + Story Bank --------
        job_id, resume_id, app_id = (uuid.uuid4().hex for _ in range(3))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "Job" ("id","userId","title","company","location",'
                    '"description","requirements","source","sourceUrl","status",'
                    '"fitScore","createdAt","updatedAt") VALUES '
                    "(%s,%s,%s,%s,%s,%s,%s,'seek',%s,'discovered'::\"JobStatus\","
                    "88.0,NOW(),NOW())",
                    (
                        job_id, user_id, JOB_TITLE, JOB_COMPANY, JOB_LOCATION,
                        JOB_DESCRIPTION, json.dumps(JOB_REQUIREMENTS),
                        f"https://example.com/job/{job_id}",
                    ),
                )
                cur.execute(
                    'INSERT INTO "Resume" ("id","userId","version","sections",'
                    '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
                    (resume_id, user_id, json.dumps({"summary": "proof"}),
                     f"hash-{resume_id}"),
                )
                cur.execute(
                    'INSERT INTO "Application" ("id","userId","jobId","resumeId",'
                    '"status","createdAt","updatedAt") VALUES '
                    "(%s,%s,%s,%s,'interview'::\"ApplicationStatus\",NOW(),NOW())",
                    (app_id, user_id, job_id, resume_id),
                )
            conn.commit()
        # StoryRepository.list_by_user is newest-first, so the story the fixture
        # cites as S1 must be inserted LAST.
        story_ids = []
        for story in (STORY_TWO, STORY_ONE):
            res = client.post("/stories", json=story, headers=headers)
            assert res.status_code == 201, res.text
            story_ids.append(res.json()["id"])
        steps.append({
            "step": "1-seed",
            "jobId": job_id, "applicationId": app_id,
            "applicationStatus": "interview",
            "storyIds": list(reversed(story_ids)),
            "note": "S1 = newest story = " + STORY_ONE["title"],
        })

        # -- the panel must be EMPTY first (no false positive) -----------------
        before = client.get("/workspaces/interviews/prep", headers=headers)
        assert before.status_code == 200, before.text
        before_body = before.json()
        steps.append({
            "step": "2-screen-before-run",
            "http": before.status_code,
            "sessionRole": (before_body.get("session") or {}).get("role"),
            "questions": before_body["questions"],
            "verdict": "PASS — panel empty before any interviewPrep run"
                       if before_body["questions"] == []
                       else "FAIL — panel already populated",
        })
        assert before_body["questions"] == [], before_body["questions"]
        assert (before_body.get("session") or {}).get("role") == JOB_TITLE

        # -- run the agent through the SAME route the Run button uses ----------
        run = client.post("/agents/interviewPrep/run", json={}, headers=headers)
        assert run.status_code == 200, run.text
        out = run.json()
        steps.append({
            "step": "3-agent-run",
            "route": "POST /agents/interviewPrep/run (generic per-name route, "
                     "EMPTY body — the Agents-screen Run button's request)",
            "http": run.status_code,
            "runId": out.get("run_id"),
            "jobSelection": out.get("jobSelection"),
            "jobIdResolved": out.get("jobId"),
            "resolvedFromSeededApplication": out.get("jobId") == job_id,
            "storiesAvailable": out.get("storiesAvailable"),
            "storiesConsidered": out.get("storiesConsidered"),
            "questionCount": len(out.get("predictedQuestions") or []),
            "questionsGrounded": out.get("questionsGrounded"),
            "storyGaps": out.get("storyGaps"),
            "droppedQuestions": out.get("droppedQuestions"),
            "model": out.get("model"),
            "tokensIn": out.get("tokensIn"),
            "tokensOut": out.get("tokensOut"),
            "costUsd": out.get("costUsd"),
            "message": out.get("message"),
        })
        assert out["jobSelection"] == "activeInterview", out["jobSelection"]
        assert out["jobId"] == job_id
        assert out["predictedQuestions"], "the agent returned no questions"

        # -- the screen is now alive, with the RUN's OWN rows -------------------
        after = client.get("/workspaces/interviews/prep", headers=headers)
        assert after.status_code == 200, after.text
        after_body = after.json()
        same = after_body["questions"] == out["predictedQuestions"]
        steps.append({
            "step": "4-screen-after-run",
            "http": after.status_code,
            "sessionRole": (after_body.get("session") or {}).get("role"),
            "sessionCompany": (after_body.get("session") or {}).get("company"),
            "questionCount": len(after_body["questions"]),
            "identicalToRunOutput": same,
            "questions": after_body["questions"],
            "verdict": "PASS — the panel serves exactly the rows this run produced"
                       if same and after_body["questions"] else "FAIL",
        })
        assert same and after_body["questions"]
        for q in after_body["questions"]:
            assert q["question"].strip()
            # Every attached story must be one of THIS user's real rows.
            if q.get("suggestedStoryId"):
                assert q["suggestedStoryId"] in story_ids, q["suggestedStoryId"]

        # -- the durable row the screen joins on --------------------------------
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id","agentName","status" FROM "AgentRun" '
                    'WHERE "userId" = %s AND "agentName" ILIKE %s '
                    'ORDER BY "startedAt" DESC',
                    (user_id, "%interview%"),
                )
                rows = cur.fetchall()
        steps.append({
            "step": "5-agentrun-row-matches-the-screen-predicate",
            "predicate": "agentName ILIKE '%interview%' (workspaces.py:71-80)",
            "rows": [{"id": r[0], "agentName": r[1], "status": r[2]} for r in rows],
            "verdict": "PASS — a real row now satisfies the join that nothing "
                       "used to write" if rows else "FAIL — no row",
        })
        assert rows and rows[0][1] == "interviewPrep"

        # -- the story-grounding guard, in anger, end to end -------------------
        # Drive the SAME route with a model output citing a story handle that does
        # not exist. The reference and its sketch must be stripped and reported.
        from app.routers import agents as agents_router

        fabricated = {
            "questions": [{
                "question": (
                    "Tell me about a time you reduced deploy time on a platform "
                    "you owned."
                ),
                "category": "behavioural",
                "whyAsked": (
                    "The posting asks for Kubernetes at scale, so the interviewer "
                    "will probe how you have delivered platform change."
                ),
                "suggestedStoryId": "S99",
                "answerSketch": {
                    "situation": STORY_ONE["situation"],
                    "task": STORY_ONE["task"],
                    "action": STORY_ONE["action"],
                    "result": STORY_ONE["result"],
                    "reflection": "I would instrument the pipeline earlier.",
                },
            }]
        }

        class _FabricatingLLM:
            def complete_json(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
                return fabricated

        real_callable = agents_router._agent_callable

        def _patched(uid, name, params):  # noqa: ANN001
            if name in ("interviewPrep", "interview-prep"):
                from app.agents.interview_prep_agent import InterviewPrepAgent

                agent = InterviewPrepAgent(llm=_FabricatingLLM())
                return "interviewPrep", (lambda: agent.run(uid, job_id=None))
            return real_callable(uid, name, params)

        agents_router._agent_callable = _patched
        try:
            guard_run = client.post(
                "/agents/interviewPrep/run", json={}, headers=headers
            )
        finally:
            agents_router._agent_callable = real_callable
        assert guard_run.status_code == 200, guard_run.text
        g = guard_run.json()["predictedQuestions"][0]
        guard_ok = (
            g["suggestedStoryId"] is None
            and g["suggestedStoryTitle"] is None
            and g["answerSketch"] is None
            and any("story" in a.lower() for a in g["guardActions"])
            and bool(g["preparationNote"])
        )
        panel = client.get(
            "/workspaces/interviews/prep", headers=headers
        ).json()["questions"]
        steps.append({
            "step": "6-story-grounding-guard-in-anger",
            "injectedStoryHandle": "S99 (does not exist; the user has S1 and S2)",
            "suggestedStoryId": g["suggestedStoryId"],
            "suggestedStoryTitle": g["suggestedStoryTitle"],
            "answerSketch": g["answerSketch"],
            "guardActions": g["guardActions"],
            "preparationNote": g["preparationNote"],
            "screenServesTheStrippedItem": panel == guard_run.json()[
                "predictedQuestions"
            ],
            "verdict": "PASS — fabricated story reference and its sketch stripped, "
                       "removal reported, nothing invented reaches the screen"
                       if guard_ok else "FAIL — a fabricated story survived",
        })
        assert guard_ok, g

    # -- does any SHIPPED screen actually consume this endpoint? ---------------
    # 25ccabe's message claims it "revive[s] the Interview Center panel". The
    # ENDPOINT is now genuinely fed (steps 2-6 prove that). Whether a user can
    # SEE it is a separate question, answered here by search rather than by
    # assertion, because it decides whether the wave-4B claim is complete.
    web_src = REPO_ROOT / "apps" / "web" / "src"
    callers = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in web_src.rglob("*.ts*")
        if "workspaces/interviews/prep" in p.read_text(errors="ignore")
        or "interviews/prep" in p.read_text(errors="ignore")
    )
    interview_page = web_src / "app" / "dashboard" / "interviews" / "page.tsx"
    ev["frontendConsumerAudit"] = {
        "question": "Does any shipped frontend file request "
                    "GET /workspaces/interviews/prep?",
        "searchRoot": "apps/web/src/**/*.ts,*.tsx",
        "callers": callers,
        "interviewCenterPageExists": interview_page.is_file(),
        "interviewCenterPageRequestsIt": (
            interview_page.is_file()
            and "interviews/prep" in interview_page.read_text(errors="ignore")
        ),
        "finding": (
            "ML-W4B-OBS-1 (MEDIUM, scope/claim accuracy — NOT fixed here, "
            "reported for orchestrator adjudication): no shipped frontend file "
            "requests GET /workspaces/interviews/prep, so the endpoint this wave "
            "brought to life has no UI consumer and no user-visible panel is "
            "revived. The Interview Center page (apps/web/src/app/dashboard/"
            "interviews/page.tsx) fetches GET /interviews and renders a free-text "
            "prep-notes field instead. This is a PRE-EXISTING, separately-recorded "
            "gap — docs/delivery/archive/MANUAL-VERIFICATION-GAPS.json records the "
            "same observation ('0 requests to /api/workspaces/interviews/prep on "
            "load, confirmed twice') — so wave-4B did not cause it. Two readings: "
            "(a) 25ccabe delivered exactly the backend half its build-plan row "
            "asked for ('writes the AgentRun rows /interviews/prep already "
            "consumes', AGENTS-IMPLEMENTATION-MATRIX-2026-07-29.md:24) and the "
            "commit message overstates it as reviving a panel; (b) the wave is "
            "incomplete until the screen is wired. Wiring the panel is net-new "
            "frontend work (session/brief/questions/liveAssist/debrief rendering) "
            "well outside a verification+fix task, so it is filed, not attempted."
        )
            if not callers else
        "PASS — the endpoint has a frontend consumer.",
    }

    ev["finishedAt"] = _now()
    ev["verdict"] = "PASS"
    ev["summary"] = (
        "GET /workspaces/interviews/prep is genuinely fed by the interviewPrep "
        "agent: empty before the run, serving exactly the run's own rows after it, "
        "backed by a durable AgentRun row that satisfies the endpoint's own ILIKE "
        "predicate; and the story-grounding guard strips a fabricated story "
        "reference end to end rather than serving it. Scope caveat in "
        "frontendConsumerAudit: no shipped screen requests this endpoint, so the "
        "BACKEND half of the wave-4B claim verifies and the 'revived panel' half "
        "does not."
    )
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(ev, indent=1, default=str) + "\n")
    print(f"PASS — artifact written: {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
