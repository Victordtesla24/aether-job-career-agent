#!/usr/bin/env python3
"""MODEL-SUB-QUOTA — repair legacy ``AgentConfig.model`` Claude pins (ops one-shot).

Thin CLI over :func:`app.services.model_pin_repair.repair_claude_model_pins`,
which holds the whole rule set and is what the tests exercise. Read that
module's docstring for exactly what is changed and why.

In one line: a Claude pin stored in OpenRouter's ``anthropic/claude-…``
spelling is rewritten to the bare id the operator's Anthropic subscription
serves (SAME model), and a Claude pin naming a model the app's Anthropic
catalog does not carry is CLEARED to NULL so the tier default applies — never
silently swapped for a different model. Non-Claude picks are untouched.

It also corrects a row's ``provider`` COLUMN when that row serves a Claude model
(pinned, or via its tier default) but the column claims some other provider —
a stored assertion that a Claude run bills an account it never touches. The
model is not changed by that correction; ``provider`` is derived from it.

DRY RUN IS THE DEFAULT. Without ``--apply`` it performs SELECTs only and prints
exactly what it would change:

    cd apps/api && python3 ../../scripts/repair_claude_model_pins.py
    cd apps/api && python3 ../../scripts/repair_claude_model_pins.py --apply

IDEMPOTENT: a second ``--apply`` run finds nothing left in a legacy shape and
reports zero changes.

``DATABASE_URL`` comes from ``os.environ`` only — never a literal in source,
never defaulted. An unset ``DATABASE_URL`` is refused.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default: dry run, SELECTs only)",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set — refusing to run.", file=sys.stderr)
        return 2

    from app.services.model_pin_repair import repair_claude_model_pins

    report = repair_claude_model_pins(apply=args.apply)
    print(json.dumps(report, indent=2, default=str))
    pending = (
        report["normalized"] + report["cleared"] + report["providerCorrected"]
    )
    if not args.apply and pending:
        print(
            f"\nDRY RUN — {report['normalized']} would be normalized, "
            f"{report['cleared']} would be cleared, "
            f"{report['providerCorrected']} provider column(s) would be corrected. "
            "Re-run with --apply to write.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
