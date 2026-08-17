"""AUD-MON-1 — GET /billing/plans transmits ONLY facts the backend enforces.

Ledger finding (round 1): "Pricing claims per-plan 'feature access' tiers that
NO code enforces. FIX: either enforce feature-gating or correct the copy to
match reality."

The /pricing PAGE was corrected first (client-side filter, MV-pricing-002 /
CLI-D3), but the API itself kept TRANSMITTING the unenforced claims: a per-plan
``modelTier`` label ('light'/'standard'/'advanced'/'premium') and presentation
bullets like "Advanced model tier", "Cover letters + story bank", "Priority
email agent", "Everything in Starter". Hiding them in one client is not the
same as not asserting them — any other consumer of the public endpoint (and the
raw JSON itself) still reads a feature ladder that nothing implements.

Architect ruling D4: a plan enforces EXACTLY two things —
  * the monthly agent-run quota  (Plan.runsPerMonth       -> UsageQuota.runsAllowed)
  * the monthly AI spend cap     (Plan.spendCapUsdMonthly -> UsageQuota.spendCapUsd)
Real per-plan feature/model gating is DEFERRED (not implemented). These tests
pin the payload shape to exactly that truth.
"""
from __future__ import annotations

import json
import re

from app.db import new_id
from app.repositories.billing import (
    RATIFIED_PLANS,
    UsageQuotaRepository,
    ensure_user_billing,
)

#: The two enforced facts — the ONLY things a plan bullet may state.
_ENFORCED_FACT_RE = re.compile(r"agent runs\s*/\s*month|monthly ai spend cap", re.I)

#: Vocabulary of the old, unenforced feature ladder.
_UNENFORCED_CLAIM_RE = re.compile(
    r"model tier|model access|story bank|email agent|everything in "
    r"(starter|pro)|community support|ats scoring|priority|feature access",
    re.I,
)

#: The Plan.modelTier label values (billing.py CHECK constraint).
_TIER_LABELS = ("light", "standard", "advanced", "premium")

_RATIFIED_BY_ID = {row[0]: row for row in RATIFIED_PLANS}


def test_plans_payload_never_asserts_an_unenforced_model_tier(client):
    body = client.get("/billing/plans").json()
    plans = {p["id"]: p for p in body["plans"]}
    assert set(plans) == {"free", "starter", "pro", "power"}
    for plan_id, plan in plans.items():
        assert "modelTier" not in plan, (
            f"{plan_id}: the payload still transmits a modelTier label; no code "
            "routes a subscriber's plan to a different model (ruling D4)."
        )
        flat = json.dumps(plan).lower()
        for label in _TIER_LABELS:
            assert f'"{label}"' not in flat, (
                f"{plan_id}: payload still carries the unenforced tier label "
                f"{label!r}."
            )


def test_plans_payload_features_state_only_enforced_facts(client):
    body = client.get("/billing/plans").json()
    for plan in body["plans"]:
        for bullet in plan["features"]:
            assert not _UNENFORCED_CLAIM_RE.search(bullet), (
                f"{plan['id']}: feature bullet {bullet!r} claims a plan-gated "
                "capability the backend does not enforce."
            )
            assert _ENFORCED_FACT_RE.search(bullet), (
                f"{plan['id']}: feature bullet {bullet!r} is not one of the two "
                "enforced facts (run quota / spend cap)."
            )


def test_plans_payload_exposes_the_enforced_spend_cap(client):
    body = client.get("/billing/plans").json()
    for plan in body["plans"]:
        ratified = _RATIFIED_BY_ID[plan["id"]]
        expected_runs, expected_cap = int(ratified[4]), float(ratified[6])
        assert plan["runsPerMonth"] == expected_runs
        assert "spendCapUsdMonthly" in plan, (
            f"{plan['id']}: the payload hides the spend cap — one of the two "
            "facts a plan actually enforces."
        )
        assert float(plan["spendCapUsdMonthly"]) == expected_cap
        # Both enforced numbers are also stated in the honest bullets.
        bullets = " | ".join(plan["features"])
        assert str(expected_runs) in bullets
        assert f"{expected_cap:.2f}" in bullets


def test_advertised_free_numbers_are_the_numbers_actually_provisioned(client):
    """The advertised facts are the ENFORCED ones, not parallel copy.

    A freshly provisioned account's UsageQuota (what the reserve path in
    ``UsageQuotaRepository.reserve`` actually checks) must equal what
    /billing/plans advertised for the Free tier.
    """
    body = client.get("/billing/plans").json()
    free = next(p for p in body["plans"] if p["id"] == "free")

    user_id = f"aud-mon-1-{new_id()}"
    ensure_user_billing(user_id)
    quota = UsageQuotaRepository().get_by_user(user_id)
    assert quota is not None

    assert int(quota["runsAllowed"]) == free["runsPerMonth"]
    assert float(quota["spendCapUsd"]) == float(free["spendCapUsdMonthly"])
