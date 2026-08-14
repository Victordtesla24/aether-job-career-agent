# ORCH §8 Operator Decision Ledger — 2026-08-14 (running)

Per `orchestrator-execution-prompt.md` §8: each row is a decision ONLY the operator can make.
Format: one-line ask · exact operator action · what it unblocks. Nothing here blocks the items
outside its own row.

| # | Ask | Exact operator action | Unblocks |
|---|---|---|---|
| 1 | **PyMuPDF licensing (AGPL)** — decision doc ready: `ADR-PYMUPDF-LICENSE.md` (recommend Option A: Artifex commercial license for launch; only `resume_pdf.py` is genuinely load-bearing, 2 of 3 use-sites swappable) | Read the ADR; if Option A: request a quote at artifex.com/licensing (SaaS/server use) | Licensing sign-off of the resume engine (functional completion is NOT blocked) |
| 2 | **Stripe Dashboard branding upload** (~2 min) | Assets were NOT found in the repo (recon S8.branding: MISSING — likely only in the market-perf session's evidence dir). Session 9c6a2ba6's draft email holds the staged steps; upload logo/colors in Stripe Dashboard → Settings → Branding | Final Stripe polish (Checkout code path NOT blocked) |
| 3 | **App-password rotation** — my bounded VM census (aether-gn-evidence, aether-setup, Uploads, aether-backups + repo docs/uat) found NO live leak file; the original leak report location is unrecovered, so rotation stays a precaution, not an emergency | Rotate the Google app password at myaccount.google.com → Security → App passwords; update the env var (name only: the SMTP/app-password key in `.env`) | Closes the §8.3 security item |
| 4 | **Verified sending domain** (~5-min DNS) — confirmed still `onboarding@resend.dev` via the Resend API branch of `email_sender.py` | In Resend: add + verify your domain (2 DNS records), then update `AETHER_EMAIL_FROM` in `.env` | Production email deliverability polish (email agent logic NOT blocked) |
| 5 | **Rehearsal card step** (~2 min + refund) — checklist staged: `STRIPE-REHEARSAL-CHECKLIST.md` (grounded in the live billing routes; Stripe account is livemode-only, so this is the ONLY honest proof of the subscribe path) | Execute the checklist: real signup → Checkout on Starter (A$19) → first tailored resume → refund → keep the invoice PDF for GST wording adjudication | §9.1 paid-tier walkthrough + §9.2 dress rehearsal — the two final gates code cannot self-prove |
| 6 | **Owner login password** (NEW this run — incident `ORCH-INCIDENT-OWNER-LOGIN-2026-08-14.md`) — §14.7 boot rotation re-asserts the `.env` admin hash on every restart; `AetherDemo1` dies at each deploy until `.env` agrees | Decide the owner password; set `AETHER_ADMIN_PASSWORD_HASH` (bcrypt) + sync `AETHER_CRON_PASSWORD`/`LOGIN_PASSWORD` in `.env`; restart via a claimed window (session 9c6a2ba6 supplied the recipe and is holding its next landing for you) | Stable owner login across deploys; unblocks 9c6a2ba6's MAIN-REDS landing |
| 7 | **GlitchTip/Sentry DSN (optional)** — interim alerting ships THIS run without it (systemd OnFailure → email per `OPS-ALERTING.md`); a hosted GlitchTip DSN would add in-process error capture | If wanted: create a GlitchTip/Sentry project, provide the DSN env var | Upgrades Wave-D alerting from unit-failure emails to in-process error tracking |

## Resolved this run (no operator action left)

- **Owner-login incident RCA** — root-caused (no intruder), both sessions aligned, operator informed via 9c6a2ba6; only row 6 remains.
- **Beauty verdict (A4)** — recorded: console-clean both viewports, desktop PASS; mobile CONCERN owned by 9c6a2ba6/S-UI-B4.
- **9 backend reds on main** — owned by session 9c6a2ba6; fix slice staged, landing behind row 6.
