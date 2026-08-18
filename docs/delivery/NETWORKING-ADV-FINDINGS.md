# Networking adversarial review — independent findings

**Session:** NW-ADV · 2026-08-18  
**Status:** VERIFIED-CLOSED on Hostinger prod `https://aether.srv1356245.hstgr.cloud`  
**Note:** Abacus URL `5cb5f0620.abacusai.cloud` is decommissioned — do not use it for prod checks.

## Verdict (pre-fix)

Production Networking was **not customer-honest** and was a **viewer, not a CRM**. Contacts imported; stats lied; pipeline could not be moved; outreach could not be acted on; CRM imports could inject global SalesLeads; Sales nurture could send Aether marketing to recruiter contacts.

## Requirements → disposition

| Requirement | Disposition | Evidence |
|---|---|---|
| `responseRate` null / UI “not measured” (never fake green 0%) | DONE | `networking_insights.build_crm_summary`; live tile shows **not measured** |
| Real `followUpsDueToday` | DONE | Melbourne-local pending `scheduledAt` |
| No synthetic `"{type} — {company}"` subject when message exists | DONE | first line of message / kind only |
| No warmth stars = stage | DONE | stars removed |
| No silent `except` empty CRM | DONE | `_ensure_outreach_tables` + structured path |
| Fence `_run_network_nurture` live send | DONE | always skip/dry_run; sent-count unchanged after land |
| Gmail exclude SENT + skip self | DONE | query + mailbox skip |
| Stop SalesLead from CRM imports | DONE | Contact-only upsert |
| Unique email index + upsert helper | DONE | `Contact_userId_email_lower_uidx` |
| PageHeader + purpose copy | DONE | live PageHeader + “What this page does” |
| Human stage labels New/Warm/… | DONE | STAGE_LABELS in select + detail |
| a11y: aria-live, dialog+Escape, retry | DONE | live |
| CRM actions: PATCH stage, queue/remove outreach, draft→Approvals | DONE | live contact panel |
| Empty account shows CRM shell (not help-only page) | DONE | `84f9d04f` — stats+pipeline+queue always render |
| Jobs `?company=` deep-link | DONE | Jobs → Networking filter |
| e2e `/networking` → `/dashboard/networking` | DONE | baseline route fixed |
| refresh-from-inbox + GET `/analytics/networking` | DONE | API + Refresh button |
| Close PR #19 / delete feature branches | DONE | PR CLOSED |

## What Networking is (product meaning)

Your **recruiter & referral CRM** for *this job search*: import people, stage them, queue follow-ups, draft first-touch via Recruiter Outreach into Approvals (never auto-send). It is **not** Aether’s sales list.

## Cross-app use

- **Jobs** → “View company in CRM” (`?company=`)
- **Recruiter Outreach agent** → drafts from `Contact` rows → Approvals
- **Analytics** → `GET /analytics/networking` (counts + employer names, no emails) for orchestrator/admin insight
- **Email inbox refresh** → promotes career-classified threads into contacts

## Commits (landed)

`ec5137e6` honesty API + fence · `5e20067d` import correctness · `16d400f2` UI/CRM actions · `3f6acfc3` purpose copy · `84f9d04f` empty CRM shell · `b46cbf61` close-out
