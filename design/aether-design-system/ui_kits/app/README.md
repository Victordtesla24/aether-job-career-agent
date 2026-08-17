# Command center kit

Interactive recreation of the Aether dashboard shell and four workspace screens.

Open `index.html`. The rail navigates between:

- **Dashboard** — pulse band with the four KPI tiles, agent activity feed (filterable, inline approve), today's opportunities, application funnel, needs-approval queue, live activity stream, story bank and recruiter CRM.
- **Jobs** — two-pane discovery browser: scored result rows on the left, the posting, fit/ATS/salary tiles and the agent's reasoning on the right. Rows select, roles save, the market tabs filter.
- **Resume Studio** — version rail, the change list with evidence traces, keyword coverage and the evidence tab, plus the ATS tile and voice DNA aside.
- **Agents** — conductor band (run everything / pause all), the six-agent fleet grid, the run-policy gates and provider connections.

The nine remaining sections render a labelled placeholder rather than an invented screen.

Built from: `apps/web/src/components/shell/*`, `app/dashboard/page.tsx`, `app/dashboard/jobs/page.tsx`, `app/dashboard/resume/page.tsx`, `app/dashboard/agents/page.tsx`.

All data in `data.js` is fixture data — the product fetches it live.
