"""One-time, idempotent repair of legacy ``AgentConfig.model`` pins.

MODEL-SUB-QUOTA clause 4 (OWNER DIRECTIVE, 2026-08-17). Before this fix a
per-agent model pick was persisted verbatim, so rows written from the OpenRouter
catalog hold Claude models in OpenRouter's namespaced spelling
(``anthropic/claude-opus-5`` was live on the owner's ``coverLetter`` row). The
routing seam now normalizes those on the way in AND on the way out, so nothing
depends on this repair for correctness — but leaving the rows as written means
the UI keeps showing a spelling the app no longer stores, and a pin naming a
model the app cannot serve stays silently broken until its next run.

What it does to each ``AgentConfig`` row whose ``model`` is a Claude id:

* ``anthropic/claude-X`` where ``claude-X`` IS in the app's Anthropic catalog
  -> rewritten to ``claude-X``. SAME model, now stored in the spelling that
  routes to the operator's subscription.
* any Claude id (either spelling) whose bare form is NOT in that catalog
  -> the pin is CLEARED to NULL, so the agent falls back to its tier default
  (itself a subscription-served Claude model). It is NEVER swapped for a
  different, nearby Claude id — a silent model substitution is exactly what
  ADR-ML-3 forbids, so the honest move is to drop the un-servable pin and let
  the documented default apply.

It also repairs the row's ``provider`` COLUMN (MODEL-SUB-QUOTA round 3, found on
live production rows): a row whose effective model is a Claude id — its pin, or
the tier default when nothing is pinned — but whose stored ``provider`` says
something other than ``anthropic`` is claiming a Claude run bills an account it
never touches, and the Agents UI repeats that claim because it prefers the
stored value over its own derivation. ``provider`` is DERIVED from the model,
never chosen, so correcting it is not a substitution: the model is untouched.
Rows with no model pin are scanned for this reason alone.

One row shape is deliberately left alone: a value equal to that agent's OWN
seeded ``recommended`` model (the app wrote it; ``_user_model_override`` treats
it as "no choice made", so it never reaches a model). Clearing it would only
make the UI render the identical value again from the catalog, and would show
up as a change to the operator that changed nothing.

Every change is recorded: a WARNING log line and an immutable ``AdminAuditLog``
row (``action='agent_model_pin_repair'``) naming the row, the previous value and
what happened to it. Nothing else is touched — a genuine OpenRouter pick
(``deepseek/…``) is left exactly as the user chose it.

Re-running is a no-op: the pass only matches rows still in a legacy shape, so a
second run reports zero changes. Read-only by default (``apply=False``).
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import get_connection, rows_to_dicts
from app.repositories.admin import write_audit
from app.services.llm_client import (
    ModelCatalogError,
    is_claude_model,
    list_provider_models,
    normalize_model_id,
)

logger = logging.getLogger(__name__)

#: The audit action every change is filed under (greppable, stable).
AUDIT_ACTION = "agent_model_pin_repair"


def _seeded_recommendation_by_agent_key() -> dict[str, str]:
    """Each agent's OWN seeded ``recommended`` model, keyed by AgentConfig key.

    A stored value equal to this is the app's own seed, not a user choice:
    ``_user_model_override`` treats it as "no choice made" (the phantom seed),
    so it never reaches a model and clearing it would only make the UI render
    the identical value again from the catalog. Those rows are left alone.
    """
    from app.routers.agents import AGENT_CATALOG

    return {
        str(entry["key"]): str(entry.get("recommended") or "")
        for entry in AGENT_CATALOG
        if entry.get("key")
    }


def _servable_claude_ids() -> set[str]:
    """Bare Claude ids the app can actually route, from its Anthropic catalog."""
    try:
        catalog = list_provider_models("anthropic", None, allow_fetch=False)
    except ModelCatalogError:  # pragma: no cover — the static catalog never raises
        return set()
    return {str(row.get("id")) for row in catalog if row.get("id")}


def repair_claude_model_pins(*, apply: bool = False) -> dict[str, Any]:
    """Normalize / clear legacy Claude pins. Returns a report of what it found.

    ``apply=False`` (the default) inspects and reports without writing a single
    row — the dry run an operator reads before committing to the change.
    """
    servable = _servable_claude_ids()
    seeded = _seeded_recommendation_by_agent_key()
    report: dict[str, Any] = {
        "scanned": 0,
        "normalized": 0,
        "cleared": 0,
        "providerCorrected": 0,
        "skippedSeedDefaults": 0,
        "applied": bool(apply),
        "changes": [],
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            # EVERY row, including those with no model pin: a row running its
            # tier default (a Claude id) can still carry a stale `provider`
            # column claiming OpenRouter, which is the half round 2 missed.
            cur.execute('SELECT "userId", "agentKey", "model", "provider" FROM "AgentConfig"')
            rows = rows_to_dicts(cur)

    for row in rows:
        current = (row.get("model") or "").strip()
        agent_key = str(row.get("agentKey") or "")
        model_action: str | None = None
        new_value: str | None = None

        if is_claude_model(current):
            report["scanned"] += 1
            if current == seeded.get(agent_key, ""):
                # The app's own seeded default, inert at run time — not a pin.
                report["skippedSeedDefaults"] += 1
            else:
                bare = normalize_model_id(current)
                if bare in servable:
                    if bare != current:
                        model_action, new_value = "normalized", bare
                else:
                    model_action, new_value = "cleared", None

        # The model this row will actually run once the model repair above is
        # applied: the repaired pin, else the pin as stored, else — for an
        # unpinned or just-cleared row — the agent's tier default.
        effective = new_value if model_action else current
        if not effective:
            effective = seeded.get(agent_key, "")
        declared = str(row.get("provider") or "").strip()
        provider_action = (
            declared
            and is_claude_model(effective)
            and declared.lower() != "anthropic"
        )

        if not model_action and not provider_action:
            continue

        change: dict[str, Any] = {
            "userId": row["userId"],
            "agentKey": row["agentKey"],
            "action": model_action or "providerCorrected",
        }
        if model_action:
            change.update({"from": current, "to": new_value})
            report[model_action] += 1
            logger.warning(
                "MODEL-SUB-QUOTA pin repair (%s): user=%s agent=%s model %r -> %r",
                "applied" if apply else "dry-run",
                row["userId"], row["agentKey"], current, new_value,
            )
        if provider_action:
            change.update({"providerFrom": declared, "providerTo": "anthropic"})
            report["providerCorrected"] += 1
            logger.warning(
                "MODEL-SUB-QUOTA pin repair (%s): user=%s agent=%s serves Claude "
                "%r but declared provider %r -> 'anthropic'",
                "applied" if apply else "dry-run",
                row["userId"], row["agentKey"], effective, declared,
            )
        report["changes"].append(change)
        if not apply:
            continue
        sets = []
        params: list[Any] = []
        if model_action:
            sets.append('"model" = %s')
            params.append(new_value)
        if provider_action:
            sets.append('"provider" = %s')
            params.append("anthropic")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "AgentConfig" SET {", ".join(sets)}, "updatedAt" = NOW() '
                    'WHERE "userId" = %s AND "agentKey" = %s',
                    (*params, row["userId"], row["agentKey"]),
                )
            conn.commit()
        # The trace is written OUTSIDE the update transaction deliberately: an
        # audit-store hiccup must not roll back (or block) the repair itself,
        # and the log line above is a second, independent record.
        try:
            write_audit(
                row["userId"],
                AUDIT_ACTION,
                target_type="AgentConfig",
                target_id=f"{row['userId']}:{row['agentKey']}",
                detail={
                    "agentKey": row["agentKey"],
                    "previousModel": current,
                    "newModel": new_value if model_action else current,
                    "modelAction": model_action,
                    "previousProvider": declared if provider_action else None,
                    "newProvider": "anthropic" if provider_action else None,
                    "action": change["action"],
                    "reason": (
                        "MODEL-SUB-QUOTA: Claude models are served by the "
                        "operator's Anthropic subscription; "
                        + (
                            "the anthropic/ namespace was stripped to the bare id "
                            "(same model, direct provider). "
                            if model_action == "normalized"
                            else "this id is not in the app's Anthropic catalog, so "
                            "the pin was cleared to the tier default rather than "
                            "silently swapped for a different model. "
                            if model_action == "cleared"
                            else ""
                        )
                        + (
                            "the stored provider column claimed this Claude run "
                            f"billed '{declared}', which it never does — the column "
                            "is derived from the model, so it was corrected to "
                            "'anthropic'. The MODEL was not changed."
                            if provider_action
                            else ""
                        )
                    ),
                    "source": "app.services.model_pin_repair",
                },
            )
        except Exception as exc:  # noqa: BLE001 — the repair is the point, not the log
            logger.warning("pin-repair audit row failed for %s: %s", change, exc)

    return report
