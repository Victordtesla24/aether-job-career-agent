"""GOLD-MASTER-V2 adversarial finding ADV-ENT-001 — ungated paid LLM call.

``uat/reports/evidence/gold-master-v2/adversarial/ENTITLEMENT-ENFORCEMENT-VERIFICATION.md``:
``POST /cover-letters/{id}/refine`` (apps/api/app/routers/cover_letters.py:653-750)
calls ``LLMClient().complete_json(..., model=get_model("REASONING"))`` directly,
with ZERO entitlement gate / quota reserve / spend cap / AgentRun audit row —
``grep -c "subscription\\|_record_run\\|_require_active\\|quota"
cover_letters.py`` = 0. Contrast: every ``/agents/*/run`` endpoint
(apps/api/app/routers/agents.py's ``_require_active_subscription`` ->
``_record_run``) gates BEFORE resource lookup — a bogus job_id still returns
402, never 404 (proven live, probes 16-18 in the evidence report, and already
pinned in this repo's own ``test_gap_p6_paywall.py``).

Exploitability boundary (from the report, §4): a FRESH Free account cannot
reach this LLM call at all — it owns no CoverLetter row, and the only
producer of one is the gated ``cover_letter_agent``. A LAPSED/CANCELLED
ex-subscriber CAN: nothing deletes their letters when their subscription
lapses, so ``/refine`` is a permanent, unmetered, unaudited handle on
REASONING-tier capacity for anyone who was EVER a paying customer. Every test
below reproduces that exact, reachable scenario — never an unreachable
"fresh Free user with a letter" strawman.

FAILING tests written BEFORE any fix (test-author brief §0.4 — never
implements the fix). Mirrors ``test_gap_p6_paywall.py``'s own ``_set_plan``
helper and the letter-seeding shortcut already established by
``test_ml_w26_refine_claim_guard.py`` (``CoverLetterRepository().create``
directly, bypassing the — irrelevant here — generation agent).

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_adv_ent_001_refine_entitlement_gate.py -v
"""
from __future__ import annotations

from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume

from app.db import get_connection
from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    ensure_user_billing,
)
from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.services.llm_client import LLMClient


def _set_plan(user_id: str, plan_id: str, status: str) -> None:
    """Force the user's Subscription row to (plan_id, status), keeping a
    matching UsageQuota ceiling. Copied verbatim from
    ``test_gap_p6_paywall.py``'s own helper so this file has no
    cross-test-module coupling."""
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (plan_id, status, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, user_id),
            )
        conn.commit()


def _seed_job(user_id: str, suffix: str) -> str:
    created = JobRepository().create(
        user_id,
        {
            "title": "Senior Backend Engineer",
            "company": "Acme Robotics",
            "location": "Remote",
            "remote": True,
            "description": "Python, PostgreSQL, distributed systems.",
            "requirements": [],
            "source": "test",
            "sourceUrl": f"https://example.test/adv-ent-001/{suffix}",
            "postedAt": None,
        },
    )
    return created["id"]


def _seed_letter(client, auth_headers, user_id: str, suffix: str) -> dict:
    """Seed the user their own résumé + a real Job + an initial letter row
    DIRECTLY (mirrors ``test_ml_w26_refine_claim_guard.py``'s own
    ``_seed_letter``) — the generation agent is irrelevant to what is under
    test here (the REFINE path's OWN, missing, entitlement gate).
    ``FIXTURE_LLM_RESUME_TEXT`` (not plain ``JORDAN_RESUME_TEXT``) is required
    so the STATIC ``cover_letter_refine`` replay fixture's vocabulary
    ($5M / 92%, per its docstring) is grounded and a clean 200 is reachable
    on the entitled-path tests below — a fabrication-guard 422 would mask the
    entitlement defect these tests exist to prove.
    """
    resume = seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
    job_id = _seed_job(user_id, suffix)
    return CoverLetterRepository().create(
        user_id, job_id, resume["id"], "Placeholder initial draft body."
    )


# ---------------------------------------------------------------------------
# 8) Unentitled (lapsed-subscriber) user -> honest 402, NO LLM call
# ---------------------------------------------------------------------------


class TestUngatedRefineIsBlockedForUnentitledUser:
    def test_lapsed_subscriber_refine_returns_402_not_200(
        self, client, auth_headers, test_user_id, monkeypatch
    ):
        """The honest CONTRACT: ``/refine`` must give a lapsed/cancelled
        subscriber the SAME 402 ``subscription_required`` refusal
        ``/agents/*/run`` gives (``_require_active_subscription``), not a
        real REASONING-tier LLM call.

        Setup mirrors the report's own exploitability boundary: the letter is
        created while the user WAS a paying subscriber (the only way a
        CoverLetter row can exist at all), then the subscription is
        cancelled BEFORE refine is called — "cancel your subscription, keep
        refining forever".
        """
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        _set_plan(test_user_id, "pro", "active")
        letter = _seed_letter(client, auth_headers, test_user_id, "lapsed-402")

        # Subscription lapses.
        _set_plan(test_user_id, "free", "canceled")
        assert (
            SubscriptionRepository().has_active_paid_subscription(test_user_id)
            is False
        )

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it more concise."},
            headers=auth_headers,
        )
        assert resp.status_code == 402, (
            "a lapsed subscriber's /refine call must be refused with the "
            f"SAME 402 subscription_required the agent endpoints give, got "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["detail"]["error"] == "subscription_required"
        assert body["detail"]["upgradeUrl"] == "/pricing"

    def test_lapsed_subscriber_refine_makes_no_llm_call(
        self, client, auth_headers, test_user_id, monkeypatch
    ):
        """Same scenario as above, isolating the second half of the claim: no
        REASONING-tier LLM call may be made at all — not merely that the
        eventual HTTP status is wrong. Spies on ``LLMClient.complete_json``
        (same monkeypatch idiom ``test_ml_w26_refine_claim_guard.py`` uses,
        delegating to the real implementation) so the call COUNT is the
        source of truth, independent of the HTTP status outcome.
        """
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        _set_plan(test_user_id, "pro", "active")
        letter = _seed_letter(client, auth_headers, test_user_id, "lapsed-nocall")
        _set_plan(test_user_id, "free", "canceled")

        calls: list[str] = []
        original = LLMClient.complete_json

        def _spy(self, prompt_name, system, user, **kwargs):
            calls.append(prompt_name)
            return original(self, prompt_name, system, user, **kwargs)

        monkeypatch.setattr(LLMClient, "complete_json", _spy)

        client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it more concise."},
            headers=auth_headers,
        )
        assert calls == [], (
            "an unentitled/lapsed user's /refine call reached the LLM "
            f"(complete_json called for {calls!r}) — the entitlement gate "
            "must run BEFORE any LLM call, exactly like _record_run does "
            "for every /agents/*/run endpoint"
        )


# ---------------------------------------------------------------------------
# 9) Entitled user's SUCCESSFUL refine must be metered AND audited
# ---------------------------------------------------------------------------


class TestEntitledRefineIsMeteredAndAudited:
    def test_entitled_refine_reserves_quota_and_creates_agent_run_audit_row(
        self, client, auth_headers, test_user_id, monkeypatch
    ):
        """An ENTITLED (paid, active) user's SUCCESSFUL refine must be
        metered and audited exactly like any other actionable agent call: it
        must reserve one run against UsageQuota AND create an AgentRun audit
        row. Today ``/refine`` calls ``_record_run`` for NEITHER, so both
        deltas below are 0 instead of the expected 1.
        """
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        _set_plan(test_user_id, "pro", "active")
        letter = _seed_letter(client, auth_headers, test_user_id, "entitled-audit")

        quota_before = UsageQuotaRepository().get_by_user(test_user_id)
        runs_before = len(AgentRunRepository().list_recent(test_user_id, limit=200))

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it more concise."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        quota_after = UsageQuotaRepository().get_by_user(test_user_id)
        runs_after = len(AgentRunRepository().list_recent(test_user_id, limit=200))

        assert int(quota_after["runsUsed"]) == int(quota_before["runsUsed"]) + 1, (
            "a successful /refine call must reserve exactly one run against "
            f"the plan quota (before={quota_before['runsUsed']!r}, "
            f"after={quota_after['runsUsed']!r})"
        )
        assert runs_after == runs_before + 1, (
            "a successful /refine call must create exactly one AgentRun "
            f"audit row (before={runs_before}, after={runs_after})"
        )

    def test_entitled_refine_respects_the_spend_cap(
        self, client, auth_headers, test_user_id, monkeypatch
    ):
        """When the user's monthly USD spend cap is already exhausted, an
        entitled user's ``/refine`` call must be blocked with the SAME 429
        ``spend_cap_exceeded`` response ``_record_run`` gives every other
        metered agent — never a 200 that silently spends past the cap.
        """
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        _set_plan(test_user_id, "pro", "active")
        letter = _seed_letter(client, auth_headers, test_user_id, "entitled-cap")

        quota = UsageQuotaRepository().get_by_user(test_user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "UsageQuota" SET "spendUsedUsd"=%s,"updatedAt"=now() '
                    'WHERE "userId"=%s',
                    (quota["spendCapUsd"], test_user_id),
                )
            conn.commit()

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it more concise."},
            headers=auth_headers,
        )
        assert resp.status_code == 429, (
            "an entitled user whose monthly spend cap is already exhausted "
            f"must be blocked (429 spend_cap_exceeded), got "
            f"{resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# 10) Gate-before-work: bogus id for an unentitled user -> 402, not 404
# ---------------------------------------------------------------------------


class TestGateRunsBeforeResourceLookup:
    def test_bogus_letter_id_for_unentitled_user_returns_402_not_404(
        self, client, auth_headers, test_user_id, monkeypatch
    ):
        """Mirrors the report's decisive differential (probe 29). On every
        GATED route a bogus id yields 402 because the gate runs first
        (``test_gap_p6_paywall.py``'s
        ``test_tailor_endpoint_returns_402_for_non_subscriber`` proves this
        for ``/agents/tailor/run``). On ``/refine`` today a bogus id yields
        404 — proof the handler reaches resource lookup with NO entitlement
        check at all. A fresh Free user (never a real letter owner) is used
        here — the gate must fire before any DB lookup, so it must not
        matter that the id does not exist.
        """
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
        assert (
            SubscriptionRepository().has_active_paid_subscription(test_user_id)
            is False
        )

        resp = client.post(
            "/cover-letters/nonexistent-adv-ent-001-id/refine",
            json={"instructions": "x"},
            headers=auth_headers,
        )
        assert resp.status_code == 402, (
            "gate-before-work: a bogus letter id for an unentitled user must "
            f"return the ENTITLEMENT refusal (402), not a resource-lookup "
            f"404 — got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["detail"]["error"] == "subscription_required"
