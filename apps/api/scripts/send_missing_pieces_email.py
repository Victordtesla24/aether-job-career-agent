#!/usr/bin/env python3
"""One-off: create a Gmail DRAFT of the owner's missing-pieces report.

Reuses the app's own GmailService credential-refresh/persist path (no ad-hoc
OAuth code here). Creates a DRAFT (never sends) addressed to the owner's own
primary connected Gmail account. Prints ONLY non-secret identifiers (draft id,
message id, thread id) — never a token value.

Usage (from apps/api):
    python3 scripts/send_missing_pieces_email.py [--dry-run]

The script reads DATABASE_URL / GOOGLE_OAUTH_* from the repo-root .env (same
convention as scripts/dedup_cleanup.py).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

# --- Path setup: run from repo root or apps/api/ ---
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

# Load .env so DATABASE_URL / GOOGLE_OAUTH_* are available.
try:
    from dotenv import load_dotenv

    _env_path = _REPO_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — expect env already populated

OWNER_USER_ID = "c6c8d0163d973a8048e7e33b8"
OWNER_EMAIL = "sarkar.vikram@gmail.com"

SUBJECT = "Aether — Missing Pieces & Open Decisions (orchestrator report, 14 Aug 2026)"

BODY = """BLOCKING ONBOARDING (in active repair):
1. Resume renderer completeness — reflow path could emit resumes missing contact/education/skills while fidelity verified only tracked edits. Renderer rebuilt (parser + pagination + whole-document verification); final parse fixes (surname recovery, merged section banners) in flight.
2. Submission truth — submission agent claimed sub-30-second "submissions" without transmitting; forensics census + proof-or-no-claim fix + per-card Submit control in flight.
3. Subscribe path unproven — zero completed Stripe Checkouts ever on the live account; the dress rehearsal (your 2-minute real card step) is the only honest proof.
4. Flagship UI landing — new shell + Dashboard + Analytics built and in review; coordinated single deploy pending; beauty verdict pending.

CORE PRODUCT INCOMPLETENESS (queued, sequenced):
5. Threshold enforcement (U2c) — 80%-all-dimensions + cover-letter thresholds computed and displayed but not yet enforced as output gates.
6. Self-serve evidence corpus — no in-app writer; future subscribers would run baseline-only. Your own 377-item corpus import still pending (queued behind the critical fix).
7. Story extractor intelligence — no corrective loop, ignores rigor policy, zero learning; first through the agentic kernel (U-AGI P2).
8. Evidence-chain defects — story relevance ranking never actually runs; cover letters can reject claims the resume just made (fix building now).
9. Email agent unscheduled — works (7 modes, writes real job cards) but nothing crons it.
10. LinkedIn source — not built; will be upload-based (compliant), never scraping.
11. Supervisor orchestrates nothing today (one-line stub; board_sweep is the real hidden orchestrator) — replaced by the U-AGI kernel + Directed-Improvement architecture (ADR-AGI-2).
12. Missing parentRunId — blocks honest causal traces for the n8n interconnection map (additive column queued).

UI COMPLETION (spec'd, batched B2→B3→B4, beauty bar binding):
Jobs (12,000px unvirtualized), Applications/Approvals, Resume Studio "aha moment" (before/after currently near-empty), Cover Letter Studio, Story Bank ("Section not found" today), Interviews/Networking/Email/Offers (thin), marketing/login surfaces (console error, redirect quirk), final deletion of superseded UI.

SCALE & OPERATIONS:
- Session tokens in localStorage (XSS exposure) — post-launch hardening.
- No operator alerting yet (GlitchTip queued).
- No queue-depth visibility for subscribers when workers are busy.
- Generic agent-run route still carries the 524-timeout exposure class.
- Monitoring residuals MON-002/003/006/008; LLM budget-timeout frequency tuning; single-deployer discipline for landings.

AWAITING YOUR DECISIONS:
- PyMuPDF licensing (AGPL in the resume engine core): buy Artifex commercial license (recommended for launch) vs Track-2 migration; brief legal advice suggested.
- Stripe Dashboard branding upload (2 minutes; assets staged in the project's evidence folder with step-by-step instructions).
- App password rotation (a verification agent leaked it into a VM-local report).
- Verified sending domain to replace onboarding@resend.dev (5-minute DNS, whenever convenient).
- Rehearsal card step when I call for it.

FINAL GATES BEFORE GO:
- Paid-tier experience end-to-end walkthrough (never done — audits covered free tier only).
- Dress rehearsal: real signup → real Checkout → onboarding → first value → refund, with real-invoice GST adjudication.
- U6 closing gate: full suites + cumulative cross-model reviews + independent audits across everything landed.

Foundation already live and verified: honesty machinery (measured fidelity, fabrication guard, honest benchmarks), billing/tax config certified, automated backups with proven restore, auto-deploy pipeline, password reset with real delivery, multi-user discovery with API budget guards, the rebuilt Agents console with the 22-agent orchestration maps.

— Aether launch orchestrator (Claude), full report in the project ledger.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build everything (incl. a live credential refresh check) but do "
        "not call drafts.create.",
    )
    args = parser.parse_args()

    from app.services.gmail_service import (
        GmailService,
        GmailError,
        GmailNotConnectedError,
        GmailAuthError,
    )

    svc = GmailService(OWNER_USER_ID)

    try:
        creds = svc._credentials()  # reuses the app's own refresh-and-persist path
    except GmailNotConnectedError as exc:
        print(json.dumps({"ok": False, "stage": "credentials", "error": "not_connected", "detail": str(exc)}))
        return 2
    except GmailAuthError as exc:
        print(json.dumps({"ok": False, "stage": "credentials", "error": "auth_expired", "detail": str(exc)}))
        return 2
    except GmailError as exc:
        print(json.dumps({"ok": False, "stage": "credentials", "error": "gmail_error", "detail": str(exc)}))
        return 2

    granted_scopes = list(getattr(creds, "scopes", None) or [])
    print(json.dumps({"stage": "credentials", "resolved_account_id": svc._resolved_account_id, "granted_scopes": granted_scopes}))

    if args.dry_run:
        print(json.dumps({"ok": True, "stage": "dry_run", "would_create_draft_to": OWNER_EMAIL}))
        return 0

    raw = svc._raw_message(to=OWNER_EMAIL, subject=SUBJECT, body=BODY)

    try:
        from googleapiclient.discovery import build

        client = build("gmail", "v1", credentials=creds, cache_discovery=False)
        draft = (
            client.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — classify and report, never raise a bare trace with token data
        print(json.dumps({"ok": False, "stage": "drafts.create", "error": type(exc).__name__, "detail": str(exc)}))
        return 3

    draft_id = draft.get("id")
    message = draft.get("message") or {}
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "drafts.create",
                "draft_id": draft_id,
                "message_id": message.get("id"),
                "thread_id": message.get("threadId"),
                "to": OWNER_EMAIL,
                "subject": SUBJECT,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
