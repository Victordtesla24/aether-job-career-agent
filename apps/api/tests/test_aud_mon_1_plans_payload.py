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
from pathlib import Path

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

#: A plan name on the same line as an unenforced-claim phrase is a per-plan
#: feature-ladder assertion (the exact shape the adversarial review found in
#: docs/growth — round 2, AUD-MON-1-R2 §4): e.g. "Starter ... email agent".
#: Generic product prose that never names a plan on that line (e.g. "your
#: story bank" describing what the product does for every user) is not a
#: claim that the feature is plan-gated, so it is not flagged.
_PLAN_NAME_RE = re.compile(r"\b(free|starter|pro|power)\b", re.I)

#: docs/growth/*.md is the versioned, committed snapshot of copy the external
#: growth engine (Perplexity Computer cron 6592806d) sends/posts to real
#: prospects — see docs/growth/README.md. It must obey the same ruling-D4
#: honesty bar as the API payload above.
_GROWTH_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "growth"


def test_growth_docs_never_assert_a_plan_gated_feature_ladder():
    """AUD-MON-1-R2 (adversarial review, RUN-20260818T0223Z §4): the growth
    engine's versioned marketing copy (docs/growth/*.md) must not assert a
    per-plan feature unlock — e.g. "Starter unlocks ... cover letters, your
    story bank, and an email agent" or "Pro ... priority email agent" — that
    no code enforces. Ruling D4: a plan differs by EXACTLY the monthly run
    quota and the monthly AI spend cap; every plan uses the same models and
    the same features.
    """
    assert _GROWTH_DOCS_DIR.is_dir(), f"missing {_GROWTH_DOCS_DIR}"
    violations: list[str] = []
    for doc in sorted(_GROWTH_DOCS_DIR.glob("*.md")):
        for lineno, line in enumerate(
            doc.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _PLAN_NAME_RE.search(line) and _UNENFORCED_CLAIM_RE.search(line):
                violations.append(f"{doc.name}:{lineno}: {line.strip()!r}")
    assert not violations, (
        "docs/growth/*.md still asserts a plan-gated feature the backend "
        "does not enforce (ruling D4): " + " | ".join(violations)
    )


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
