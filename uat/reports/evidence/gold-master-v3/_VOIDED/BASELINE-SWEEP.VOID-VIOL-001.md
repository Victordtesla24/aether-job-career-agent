# BASELINE-SWEEP.md
Generated: 2026-07-31T17:09:20.591Z (UTC)

## Summary
- Routes swept: 28
- Total console errors: 0
- Total failed requests: 30
- Production URL: https://5cb5f0620.abacusai.cloud

## Route Summary Table

| Route | HTTP Status | Console Errors | Failed Requests | Data State | Screenshot | Notes |
|-------|-------------|---|---|---|---|---|
| `/login` | 200 | 0 | 3 | live | [login.png](login.png) | OK |
| `/` | 200 | 0 | 3 | live | [root.png](root.png) | OK |
| `/dashboard` | 200 | 0 | 2 | live | [dashboard.png](dashboard.png) | OK |
| `/dashboard/agents` | 200 | 0 | 2 | live | [dashboard-agents.png](dashboard-agents.png) | OK |
| `/dashboard/analytics` | 200 | 0 | 1 | live | [dashboard-analytics.png](dashboard-analytics.png) | OK |
| `/dashboard/applications` | 200 | 0 | 0 | live | [dashboard-applications.png](dashboard-applications.png) | OK |
| `/dashboard/approvals` | 200 | 0 | 1 | live | [dashboard-approvals.png](dashboard-approvals.png) | OK |
| `/dashboard/cover-letters` | 200 | 0 | 2 | live | [dashboard-cover-letters.png](dashboard-cover-letters.png) | OK |
| `/dashboard/email` | 200 | 0 | 3 | live | [dashboard-email.png](dashboard-email.png) | OK |
| `/dashboard/interviews` | 200 | 0 | 1 | live | [dashboard-interviews.png](dashboard-interviews.png) | OK |
| `/dashboard/jobs` | 200 | 0 | 0 | live | [dashboard-jobs.png](dashboard-jobs.png) | OK |
| `/dashboard/networking` | 200 | 0 | 0 | live | [dashboard-networking.png](dashboard-networking.png) | OK |
| `/dashboard/offers` | 200 | 0 | 1 | live | [dashboard-offers.png](dashboard-offers.png) | OK |
| `/dashboard/resume` | 200 | 0 | 2 | live | [dashboard-resume.png](dashboard-resume.png) | OK |
| `/dashboard/settings` | 200 | 0 | 0 | live | [dashboard-settings.png](dashboard-settings.png) | OK |
| `/dashboard/stories` | 200 | 0 | 3 | live | [dashboard-stories.png](dashboard-stories.png) | OK |
| `/admin-login` | 200 | 0 | 0 | live | [admin-login.png](admin-login.png) | OK |
| `/admin` | 200 | 0 | 0 | live | [admin.png](admin.png) | OK |
| `/admin/audit-log` | 200 | 0 | 0 | live | [admin-audit-log.png](admin-audit-log.png) | OK |
| `/admin/health` | 200 | 0 | 3 | live | [admin-health.png](admin-health.png) | OK |
| `/admin/settings` | 200 | 0 | 1 | live | [admin-settings.png](admin-settings.png) | OK |
| `/admin/spend` | 200 | 0 | 0 | live | [admin-spend.png](admin-spend.png) | OK |
| `/admin/users` | 200 | 0 | 1 | live | [admin-users.png](admin-users.png) | OK |
| `/pricing` | 200 | 0 | 0 | live | [pricing.png](pricing.png) | OK |
| `/privacy-policy` | 200 | 0 | 0 | live | [privacy-policy.png](privacy-policy.png) | OK |
| `/signup` | 200 | 0 | 1 | live | [signup.png](signup.png) | OK |
| `/terms` | 200 | 0 | 0 | live | [terms.png](terms.png) | OK |
| `/forgot-password` | 200 | 0 | 0 | live | [forgot-password.png](forgot-password.png) | OK |

## Baseline Findings

### Route: `/login`
- Final URL: https://5cb5f0620.abacusai.cloud/login
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 3
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 3
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 2
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/agents`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fagents
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 2
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/analytics`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fanalytics
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/approvals`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fapprovals
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/cover-letters`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fcover-letters
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 2
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/email`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Femail
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 3
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/interviews`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Finterviews
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/offers`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Foffers
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/resume`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fresume
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 2
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/dashboard/stories`
- Final URL: https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard%2Fstories
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 3
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/admin/health`
- Final URL: https://5cb5f0620.abacusai.cloud/login
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 3
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1obve (net::ERR_ABORTED)
  - GET https://5cb5f0620.abacusai.cloud/terms?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/admin/settings`
- Final URL: https://5cb5f0620.abacusai.cloud/login
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/admin/users`
- Final URL: https://5cb5f0620.abacusai.cloud/login
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

### Route: `/signup`
- Final URL: https://5cb5f0620.abacusai.cloud/signup
- HTTP Status: 200
- Console Errors: 0

- Failed Requests: 1
  - GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=g1byd (net::ERR_ABORTED)

- Placeholder Flags: none
- Data State: live

