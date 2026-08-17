repo: Victordtesla24/aether-job-career-agent
branch: main
path: apps/web

## Last sync
date: 2026-08-15T01:30:00Z

### Updated in this project
- Built the Aether design system on the AB Entertainment black-and-gold baseline.
- Tokens, 12 components and 18 foundation cards derived from the web app's own contracts.
- UI kits recreated for the command center (4 screens) and the public site (pricing + auth).

## Screen map
| Screen | Built from |
|---|---|
| ui_kits/app/Shell.jsx | apps/web/src/components/shell/Rail.tsx, shell/CommandBar.tsx, mobile-tab-bar.tsx, lib/navigation.ts, lib/navigation-groups.ts |
| ui_kits/app/DashboardScreen.jsx | apps/web/src/app/dashboard/page.tsx, components/dashboard/DashboardStats.tsx, components/telemetry/ActivityTicker.tsx |
| ui_kits/app/JobsScreen.jsx | apps/web/src/app/dashboard/jobs/page.tsx |
| ui_kits/app/ResumeScreen.jsx | apps/web/src/app/dashboard/resume/page.tsx, components/resume/ChangeList.tsx |
| ui_kits/app/AgentsScreen.jsx | apps/web/src/app/dashboard/agents/page.tsx, components/agents/* |
| ui_kits/public/PricingScreen.jsx | apps/web/src/app/pricing/page.tsx |
| ui_kits/public/AuthScreen.jsx | apps/web/src/app/login/page.tsx, components/PublicFooter.tsx |
| tokens/*.css | apps/web/tailwind.config.ts, apps/web/src/app/globals.css, design/DESIGN.md |
