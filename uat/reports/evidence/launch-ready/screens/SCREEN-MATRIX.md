# W-E SCREEN MATRIX — wireframe ↔ route ↔ key endpoints

Built 2026-07-24 from `design/screens/` (17 wireframes, per `design/canvas.json`) and the
actual Next.js app router (`apps/web/src/app/**/page.tsx`). Production base:
https://5cb5f0620.abacusai.cloud (API via `/api/*` nginx rewrite).

| id | Wireframe | Prod route | Key endpoints | Notes |
|---|---|---|---|---|
| dashboard | dashboard.html | /dashboard | /auth/me, /workspaces/career-data, /agents/runs | Home overview |
| jobs | job-discovery.html | /dashboard/jobs | /jobs, /agents/scout/run, /agents/scout/sources/availability | Job Discovery |
| applications | application-tracker.html | /dashboard/applications | /applications | Tracker board (FEAT-B2 stage move) |
| resume | resume-studio.html | /dashboard/resume | /resumes, /agents/tailor/run | Resume Studio |
| cover-letters | cover-letter-studio.html | /dashboard/cover-letters | /cover-letters, /agents/cover-letter/run | Cover Letter Studio |
| email | email-center.html | /dashboard/email | /workspaces/emails/inbox, /emails/draft, /emails/accounts/connect | Email Center |
| interviews | interview-center.html | /dashboard/interviews | /interviews | Interview Center |
| networking | networking.html | /dashboard/networking | /networking/contacts, /workspaces/networking/summary | Networking |
| offers | offer-comparison.html | /dashboard/offers | /workspaces/offers | Offer Comparison |
| stories | story-bank.html | /dashboard/stories | /stories, /stories/stats, /agents/story-extractor/run | Story Bank |
| analytics | analytics.html | /dashboard/analytics | /analytics/market-pulse, /analytics/ats-distribution, /analytics/agent-roi | Analytics |
| agents | agents.html + agent-monitor.html | /dashboard/agents | /agents, /agents/runs, /agents/pipeline/run | agent-monitor wireframe = monitor panel of same screen |
| approvals | approval-modal.html | /dashboard/approvals | /approvals, /approvals/purge-expired | FEAT-B1 purge lives here |
| settings | settings.html | /dashboard/settings | /settings (workspaces), /billing/subscription, /billing/entitlement | Settings + billing |
| pricing | (no wireframe — §7.2 subscription flow) | /pricing | /pricing, /billing/checkout, /billing/portal | Public pricing page |

Responsive variants (audited as viewports of the mapped route, not separate rows):
- mobile-dashboard.html → /dashboard @ 360px
- mobile-approval.html → /dashboard/approvals @ 360px

Unmapped router paths (out of dashboard-screen scope, checked in hygiene pass only):
`/login`, `/signup`, `/forgot-password`, `/terms`, `/privacy-policy`,
`/admin/*` (7 admin routes — operator surface, not part of the 15-screen paid-app matrix),
`/dashboard/[...slug]` (graceful "Section not found" catch-all).

Coverage check: 17/17 wireframes mapped (15 primary + 2 mobile variants); 15 matrix rows.
