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
        "skippedSeedDefaults": 0,
        "applied": bool(apply),
        "changes": [],
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "userId", "agentKey", "model" FROM "AgentConfig" '
                'WHERE "model" IS NOT NULL AND "model" <> \'\''
            )
            rows = rows_to_dicts(cur)

    for row in rows:
        current = (row.get("model") or "").strip()
        if not is_claude_model(current):
            continue  # a genuine OpenRouter / non-Claude pick — untouched
        report["scanned"] += 1
        if current == seeded.get(str(row.get("agentKey")), ""):
            # The app's own seeded default, inert at run time — not a pin.
            report["skippedSeedDefaults"] += 1
            continue
        bare = normalize_model_id(current)
        if bare in servable:
            if bare == current:
                continue  # already in the routing spelling — nothing to do
            action, new_value = "normalized", bare
        else:
            action, new_value = "cleared", None
        change = {
            "userId": row["userId"],
            "agentKey": row["agentKey"],
            "from": current,
            "to": new_value,
            "action": action,
        }
        report["changes"].append(change)
        report[action] += 1
        logger.warning(
            "MODEL-SUB-QUOTA pin repair (%s): user=%s agent=%s model %r -> %r",
            "applied" if apply else "dry-run",
            row["userId"], row["agentKey"], current, new_value,
        )
        if not apply:
            continue
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentConfig" SET "model" = %s, "updatedAt" = NOW() '
                    'WHERE "userId" = %s AND "agentKey" = %s',
                    (new_value, row["userId"], row["agentKey"]),
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
                    "newModel": new_value,
                    "action": action,
                    "reason": (
                        "MODEL-SUB-QUOTA: Claude models are served by the "
                        "operator's Anthropic subscription; "
                        + (
                            "the anthropic/ namespace was stripped to the bare id "
                            "(same model, direct provider)."
                            if action == "normalized"
                            else "this id is not in the app's Anthropic catalog, so "
                            "the pin was cleared to the tier default rather than "
                            "silently swapped for a different model."
                        )
                    ),
                    "source": "app.services.model_pin_repair",
                },
            )
        except Exception as exc:  # noqa: BLE001 — the repair is the point, not the log
            logger.warning("pin-repair audit row failed for %s: %s", change, exc)

    return report
