# Networking adversarial review — independent findings

**Session:** NW-ADV · 2026-08-18  
**Base:** `origin/main` @ `4e46d140`  
**PR #19:** `feat/networking-crm-honesty` (CONFLICTING) — absorb sound parts, fence unsafe send

## Verdict

Production Networking is **not customer-honest** and is a **viewer, not a CRM**. Contacts import and persist. Stats lie. Pipeline cannot be moved on `main`. Outreach cannot be acted on.

## Keep from PR #19 (`a0746d74`)

- `networking_insights.build_crm_summary` — `responseRate: null` when no terminal outreach
- `followUpsDueToday` from real `scheduledAt` (Australia/Melbourne)
- Contact upsert that does not reset stage on re-import
- Subject from first line of `message` when present
- `POST /networking/refresh-from-inbox`, `GET /analytics/networking`
- UI: PageHeader, not-measured tile, freshness footnote, contact edit + stage select
- Tests in `test_networking_insights.py`

## Kill / fence

- `_run_network_nurture` live `gmail.send` — prod has `AETHER_SALES_AGENT_DRY_RUN=false`; would market Aether to recruiter/referral contacts. Fence: never send; log skip/dry_run only.
- Do not absorb branding commit `5b4c646f` or guardian commits from `merge/pr19-resolved`.

## Fix before ship (beyond absorb)

- Replace bare `except Exception` swallows that hide missing OutreachTask as empty CRM
- `network_snapshot_for_prompt` must not report `contacts: 0` on error
- Stage labels New/Warm/… in UI select (not raw enum)
- Gmail SENT/self exclusion; stop global SalesLead from CRM imports
- Unique index on contact email; wire remaining CRM actions

## Out of scope

- LinkedIn scraping · flipping dry-run env · product-wide API paywall (ADV-ENT-002) · kanban DnD
