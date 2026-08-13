# Aether Growth Engine

Autonomous marketing/outreach system for driving Aether subscriptions, built and operated outside this repo (Perplexity Computer scheduled task, cron id `6592806d`, runs 6x/day) but versioned here for auditability.

## Live artifacts (source of truth, edited by the running engine)
- [CRM & Learning Log (Sheet)](https://docs.google.com/spreadsheets/d/1hiaoc7lDKW09IKbHwL9FlJAYU37k290ZjQUvB2v_52M/edit) — Prospects, Email_Log, LinkedIn_Content_Queue, Learnings, Metrics, Suppression_List
- [LinkedIn Content Calendar (Doc)](https://docs.google.com/document/d/1FgpWoxG_AAUodf8Nz21QsTiApj0eSz5jeSDXvCiyFSM/edit)
- [Messaging Playbook & Email Templates (Doc)](https://docs.google.com/document/d/1mc5tPZRN3kKGKTO2-S1W6CDYPoiDECH0yKapoW9j760/edit)

## Files in this directory
- `messaging-playbook.md` — ICP, positioning, pricing, compliance footer, 4 email templates (snapshot; live Doc is authoritative)
- `linkedin-content-calendar.md` — batch 1 draft posts (snapshot; live Doc is authoritative)
- `ADVERSARIAL-REVIEW-2026-08-10.md` — independent third-party review of the engine (compliance, idempotency, safety, revenue-funnel gaps) with a prioritized fix list. All FAIL items on compliance footer, suppression, and idempotency were fixed the same day (see Learnings tab in the Sheet, 2026-08-13 entries).

## Verified facts (2026-08-13, live browser test)
- `/pricing` renders real AUD prices ($19/$39/$69 monthly + correct annual) with working Subscribe CTAs — an earlier non-JS text-fetch based review incorrectly reported this as broken.
- Clicking Subscribe on a logged-in account redirects to a real, live-mode Stripe Checkout session (`checkout.stripe.com`, `cs_live_...`) — the payment path is functional end to end. No purchase was completed during testing.
- LinkedIn automation (auto-post/auto-connect/auto-DM) is intentionally NOT implemented — LinkedIn's Terms prohibit it and enforcement in 2026 escalates to permanent account bans. The engine only drafts LinkedIn content for manual posting.
- No cold-email list exists or is fabricated — the engine only emails real inbound signals or genuine pre-existing contacts, enforced via a tool allowlist, a recipient hard rule, a Suppression_List, and idempotency keys (Gmail_Message_Id/Handled) added after the adversarial review.
