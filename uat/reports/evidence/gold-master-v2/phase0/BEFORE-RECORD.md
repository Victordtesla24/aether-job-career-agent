# BEFORE-RECORD: Production State Baseline

**Captured:** 2026-07-30T23:03:27.742Z
**Base URL:** https://5cb5f0620.abacusai.cloud
**Total Routes:** 27

| Route | Screenshot | Status | Console Errors | Network Errors | Description |
|-------|------------|--------|----------------|-----------------|---------|
| `/login` | [login.png](before/login.png) | 200 | 0 | 1 | A |
| `/signup` | [signup.png](before/signup.png) | 200 | 0 | 0 | A |
| `/forgot-password` | [forgot-password.png](before/forgot-password.png) | 200 | 0 | 2 | A |
| `/pricing` | [pricing.png](before/pricing.png) | 200 | 0 | 2 | A |
| `/terms` | [terms.png](before/terms.png) | 200 | 0 | 0 | Aether |
| `/privacy-policy` | [privacy-policy.png](before/privacy-policy.png) | 200 | 0 | 0 | Aether |
| `/dashboard` | [dashboard.png](before/dashboard.png) | 200 | 0 | 0 | Aether |
| `/dashboard/agents` | [dashboard-agents.png](before/dashboard-agents.png) | 200 | 0 | 0 | Aether |
| `/dashboard/jobs` | [dashboard-jobs.png](before/dashboard-jobs.png) | 200 | 0 | 0 | Aether |
| `/dashboard/applications` | [dashboard-applications.png](before/dashboard-applications.png) | 200 | 0 | 0 | Aether |
| `/dashboard/approvals` | [dashboard-approvals.png](before/dashboard-approvals.png) | 200 | 0 | 0 | Aether |
| `/dashboard/cover-letters` | [dashboard-cover-letters.png](before/dashboard-cover-letters.png) | 200 | 0 | 0 | Aether |
| `/dashboard/resume` | [dashboard-resume.png](before/dashboard-resume.png) | 200 | 0 | 0 | Aether |
| `/dashboard/stories` | [dashboard-stories.png](before/dashboard-stories.png) | 200 | 0 | 0 | Aether |
| `/dashboard/email` | [dashboard-email.png](before/dashboard-email.png) | 200 | 0 | 0 | Aether |
| `/dashboard/interviews` | [dashboard-interviews.png](before/dashboard-interviews.png) | 200 | 0 | 0 | Aether |
| `/dashboard/offers` | [dashboard-offers.png](before/dashboard-offers.png) | 200 | 0 | 0 | Aether |
| `/dashboard/networking` | [dashboard-networking.png](before/dashboard-networking.png) | 200 | 0 | 0 | Aether |
| `/dashboard/analytics` | [dashboard-analytics.png](before/dashboard-analytics.png) | 200 | 0 | 0 | Aether |
| `/dashboard/settings` | [dashboard-settings.png](before/dashboard-settings.png) | 200 | 0 | 0 | Aether |
| `/admin` | [admin.png](before/admin.png) | 200 | 0 | 0 | Aether Admin |
| `/admin/health` | [admin-health.png](before/admin-health.png) | 200 | 0 | 0 | Aether Admin |
| `/admin/settings` | [admin-settings.png](before/admin-settings.png) | 200 | 0 | 0 | Aether Admin |
| `/admin/users` | [admin-users.png](before/admin-users.png) | 200 | 0 | 3 | Aether Admin |
| `/admin/users/1` | [admin-users-id.png](before/admin-users-id.png) | 200 | 1 | 0 | Aether Admin |
| `/admin/spend` | [admin-spend.png](before/admin-spend.png) | 200 | 0 | 0 | Aether Admin |
| `/admin/audit-log` | [admin-audit-log.png](before/admin-audit-log.png) | 200 | 0 | 0 | Aether Admin |


## Detailed Results

### /login
- **Screenshot:** `before/login.png`
- **HTTP Status:** 200
- **Failed Network Requests:**
  - `https://5cb5f0620.abacusai.cloud/forgot-password?_rsc=1obve`: net::ERR_ABORTED

### /signup
- **Screenshot:** `before/signup.png`
- **HTTP Status:** 200

### /forgot-password
- **Screenshot:** `before/forgot-password.png`
- **HTTP Status:** 200
- **Failed Network Requests:**
  - `https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=1at5c`: net::ERR_ABORTED
  - `https://5cb5f0620.abacusai.cloud/terms?_rsc=1at5c`: net::ERR_ABORTED

### /pricing
- **Screenshot:** `before/pricing.png`
- **HTTP Status:** 200
- **Failed Network Requests:**
  - `https://5cb5f0620.abacusai.cloud/terms?_rsc=6i8d7`: net::ERR_ABORTED
  - `https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=6i8d7`: net::ERR_ABORTED

### /terms
- **Screenshot:** `before/terms.png`
- **HTTP Status:** 200

### /privacy-policy
- **Screenshot:** `before/privacy-policy.png`
- **HTTP Status:** 200

### /dashboard
- **Screenshot:** `before/dashboard.png`
- **HTTP Status:** 200

### /dashboard/agents
- **Screenshot:** `before/dashboard-agents.png`
- **HTTP Status:** 200

### /dashboard/jobs
- **Screenshot:** `before/dashboard-jobs.png`
- **HTTP Status:** 200

### /dashboard/applications
- **Screenshot:** `before/dashboard-applications.png`
- **HTTP Status:** 200

### /dashboard/approvals
- **Screenshot:** `before/dashboard-approvals.png`
- **HTTP Status:** 200

### /dashboard/cover-letters
- **Screenshot:** `before/dashboard-cover-letters.png`
- **HTTP Status:** 200

### /dashboard/resume
- **Screenshot:** `before/dashboard-resume.png`
- **HTTP Status:** 200

### /dashboard/stories
- **Screenshot:** `before/dashboard-stories.png`
- **HTTP Status:** 200

### /dashboard/email
- **Screenshot:** `before/dashboard-email.png`
- **HTTP Status:** 200

### /dashboard/interviews
- **Screenshot:** `before/dashboard-interviews.png`
- **HTTP Status:** 200

### /dashboard/offers
- **Screenshot:** `before/dashboard-offers.png`
- **HTTP Status:** 200

### /dashboard/networking
- **Screenshot:** `before/dashboard-networking.png`
- **HTTP Status:** 200

### /dashboard/analytics
- **Screenshot:** `before/dashboard-analytics.png`
- **HTTP Status:** 200

### /dashboard/settings
- **Screenshot:** `before/dashboard-settings.png`
- **HTTP Status:** 200

### /admin
- **Screenshot:** `before/admin.png`
- **HTTP Status:** 200

### /admin/health
- **Screenshot:** `before/admin-health.png`
- **HTTP Status:** 200

### /admin/settings
- **Screenshot:** `before/admin-settings.png`
- **HTTP Status:** 200

### /admin/users
- **Screenshot:** `before/admin-users.png`
- **HTTP Status:** 200
- **Failed Network Requests:**
  - `https://5cb5f0620.abacusai.cloud/admin/users/cccd35dcf1f2a57e715bf821b?_rsc=12ojy`: net::ERR_ABORTED
  - `https://5cb5f0620.abacusai.cloud/admin/users/c6c8d0163d973a8048e7e33b8?_rsc=12ojy`: net::ERR_ABORTED
  - `https://5cb5f0620.abacusai.cloud/admin/users/c08c4e7416692b70e268170fd?_rsc=12ojy`: net::ERR_ABORTED

### /admin/users/1
- **Screenshot:** `before/admin-users-id.png`
- **HTTP Status:** 200
- **Console Messages:**
  - [ERROR] Failed to load resource: the server responded with a status of 404 ()

### /admin/spend
- **Screenshot:** `before/admin-spend.png`
- **HTTP Status:** 200

### /admin/audit-log
- **Screenshot:** `before/admin-audit-log.png`
- **HTTP Status:** 200

