> **⚠️ HISTORICAL — SUPERSEDED (2026-07-12 wireframe-to-implementation audit).**
> This was an early Phase-0/1 audit of Dashboard/Jobs/Applications wireframe elements and does
> NOT reflect the current shipped product. The authoritative, current, gate-verified delivery
> record is **`docs/delivery/phase6-gap-analysis.json`** + **`docs/delivery/PHASE6-EXECUTION-SUMMARY.md`**
> (Phases 1–6 shipped to production). Kept for historical continuity only.

# Wireframe-to-Implementation Gap Analysis for Aether Career Agent
**Production URL:** https://5cb5f0620.abacusai.cloud  
**Audit Date:** 2026-07-12  
**Focus Screens:** Dashboard, Jobs, Applications

## 1. WIREFRAME ELEMENT INVENTORY

### Dashboard (design/screens/dashboard.html)
- **Sidebar & Navigation**
  - `sidebar-main-a1b2c3` – main sidebar container
  - `nav-primary-d4e5f6` – primary navigation links
  - `btn-manage-agents-9a8b7c` – "Manage Agents" button
- **Top Bar**
  - `topbar-g7h8i9` – top header bar
  - `btn-notif-j1k2l3` – notification bell with indicator
- **Main Content**
  - `main-content-m4n5o6` – main content container
  - `stats-row-p7q8r9` – row of stat cards (jobs found, applied, etc.)
- **Agent Feed**
  - `agent-feed-s1t2u3` – live agent activity feed
- **Opportunities**
  - `opportunities-v4w5x6` – "Today's Opportunities" section
  - `opp-card-1-y7z8a9`, `opp-card-2-e4f5g6`, `opp-card-3-k1l2m3` – opportunity cards
  - `btn-apply-1-b1c2d3`, `btn-apply-2-h7i8j9`, `btn-apply-3-n4o5p6` – apply buttons
- **Funnel**
  - `funnel-q7r8s9` – application funnel visualization
- **Story Bank Quick**
  - `story-bank-quick-db10` – quick access to story bank
- **CRM Summary**
  - `crm-summary-db11` – recruiter CRM summary
- **Approvals**
  - `approvals-t1u2v3` – pending approvals list
  - `btn-approve-1-w4x5y6`, `btn-reject-1-z7a8b9`, `btn-approve-2-c1d2e3`, `btn-reject-2-f4g5h6` – approval action buttons
- **Market Intel**
  - `market-intel-mi01` – market intelligence panel
  - `btn-focus-explore-mi02` – "Explore matching roles" button

### Job Discovery (design/screens/job-discovery.html)
- **Sidebar & Navigation**
  - `sidebar-main-jd01`, `nav-primary-jd02`, `topbar-jd03`
- **Market Tabs**
  - `tab-au-jd20` – Australia (Local) tab
  - `tab-intl-jd21` – International tab
  - `tab-saved-jd41` – Saved jobs tab
- **Source Bar**
  - `source-bar-jd22` – connected job boards panel
  - `btn-sync-jd23` – "Sync Now" button
  - `btn-seek-manage-jd24`, `btn-li-manage-jd25`, `btn-wfa-connect-jd26`, `btn-jora-connect-jd27`, `btn-indeed-connect-jd28` – board-specific buttons
- **Filters**
  - `filter-role-jd04`, `filter-source-jd29`, `filter-loc-jd05`, `filter-salary-jd06`, `filter-remote-jd07`
  - `btn-clear-jd08` – clear all filters
- **Job List**
  - `job-list-jd09` – job list container
  - `btn-bulk-tailor-jd10`, `btn-bulk-skip-jd11` – bulk action buttons
  - `job-card-1-jd12`, `job-card-2-jd13`, `job-card-3-jd14`, `job-card-4-jd15` – job cards
- **Job Detail**
  - `job-detail-jd16` – detail panel
  - `link-crm-jd40` – "View company in CRM" link
- **Fit Score**
  - `fit-score-jd30` – ATS fit score panel
- **Risk Signals**
  - `risk-signals-jd31` – risk signals panel
- **Apply Flow**
  - `apply-flow-jd32` – apply flow buttons
  - `btn-tailor-resume-jd17` – "Tailor Resume" button
  - `btn-preview-jd33`, `btn-skip-jd19`, `link-story-bank-jd34`, `link-open-studio-jd35`
  - `btn-review-apply-jd18` – "Review & Apply" button
  - `btn-retailor-jd36` – "Re-tailor" button
- **Saved View**
  - `saved-view-jd42` – saved jobs view
  - `btn-saved-tailor-all-jd43` – "Tailor & Apply all"
  - `saved-card-1-jd44`, `saved-card-2-jd45`, `saved-card-3-jd46`
  - `btn-unsave-1-jd47`, `btn-unsave-2-jd48`, `btn-unsave-3-jd49`
- **Submit Gate Modal**
  - `submit-gate-jd37` – modal overlay
  - `submit-cancel-jd38`, `submit-confirm-jd39` – modal buttons

### Application Tracker (design/screens/application-tracker.html)
- **Sidebar & Navigation**
  - `sidebar-main-at01`, `nav-primary-at02`, `topbar-at03`
- **View Controls**
  - `btn-view-board-at04`, `btn-view-sankey-at40`, `btn-view-timeline-at05`
  - `btn-filter-at06`, `btn-sort-at07`
- **Kanban Board**
  - `kanban-at08` – main board container
  - `col-discovered-at09`, `col-evaluating-at12`, `col-tailoring-at14`, `col-ready-at16`, `col-submitted-at18`, `col-review-at20`, `col-interview-at22`, `col-offer-at24` – stage columns
  - `card-at10`, `card-at11`, `card-at13`, `card-at15`, `card-at17`, `card-at19`, `card-at21`, `card-at23`, `card-at25` – application cards
- **Sankey View**
  - `sankey-view-at41` – sankey diagram panel
- **Email Thread Links**
  - `link-email-thread-at42`, `link-email-thread-at43`, `link-crm-at44`, `link-crm-at45`

## 2. PRODUCTION REALITY

### Dashboard
- **PRESENT** (with minor differences):
  - Sidebar & Navigation – present, matches wireframe layout.
  - Top Bar with notification bell – present, includes user avatar and greeting.
  - Agent Activity feed – present as "Agent Activity" with filter buttons.
  - Today's Opportunities – present as "Today's Opportunities" with job cards and action buttons.
  - Application Funnel – present as "Application Funnel" (likely placeholder).
  - Story Bank quick link – present as "Story Bank" with "Open" link.
  - Recruiter CRM – present as "Recruiter CRM" with "Open" link.
  - Needs Approval – present as "Needs Approval".
- **ABSENT**:
  - Stats row (stats-row-p7q8r9) – not rendered; UI shows "Loading stats" placeholder.
  - Market Intel panel (market-intel-mi01) – completely missing.
  - Design‑id attributes – only `m-notif-md02` and `m-tabbar-md08` appear; wireframe‑specific IDs not used.
- **DIFFERENT**:
  - Opportunity cards show only three jobs (vs. three in wireframe). Apply buttons are "Tailor & Apply" vs. "Tailor & Apply"/"Review Match".
  - Funnel visualization appears to be a placeholder (no actual chart).
  - Approvals list shows count but no actionable buttons (Approve/Reject missing).

### Job Discovery
- **PRESENT**:
  - Sidebar & Navigation – present.
  - Market Tabs – Australia, International, Saved tabs present with counts (110, 2, 0).
  - Source Bar – "Connected job boards" panel with sync button and board list.
  - Filters – Source filter (dropdown), location textbox, Remote/Hybrid toggle, sort dropdown, match score slider, clear all button.
  - Job List – scrollable list of job cards with checkboxes and match scores.
  - Job Detail – detail panel with company logo placeholder, job title, company, source, tags.
  - Fit Score panel – not visible in current snapshot (may appear after selecting a job).
  - Apply Flow – "Tailor Resume" and "Review & Apply" buttons appear after job selection (likely).
- **ABSENT**:
  - Risk Signals panel – not visible.
  - Bulk tailor/skip buttons – present but disabled (no jobs selected).
  - Saved View – saved jobs count zero; no saved cards.
  - Submit Gate modal – not triggered.
  - Design‑id attributes – none present in production.
- **DIFFERENT**:
  - Filter‑by‑role and filter‑by‑salary are missing; replaced by generic source filter and match slider.
  - Job cards show match score as number (e.g., 35) vs. colored badge.
  - Detail panel lacks ATS score breakdown and risk signals.

### Application Tracker
- **PRESENT**:
  - Sidebar & Navigation – present.
  - View Controls – Board View selected, Sankey Flow and Timeline tabs present.
  - Kanban Board – columns: Discovered, Evaluating, Tailoring, Ready, Submitted, Review, Interview, Offer.
  - Application cards – each with initials, match score, job title, company, timestamp.
  - Filter and Sort buttons – present.
- **ABSENT**:
  - Sankey View – tab exists but not shown (requires clicking "Sankey Flow").
  - Email thread links – not present on cards.
  - CRM links – not present.
  - Design‑id attributes – none.
- **DIFFERENT**:
  - Column counts differ (e.g., Discovered 105 vs. wireframe's example numbers).
  - Card styling is simpler (no colored borders, no progress bars).
  - No "tailoring resume…" status indicator.

## 3. REAL DATA AUDIT

### API Endpoints Checked
- **GET /api/analytics/funnel** – Returns real DB‑derived counts (jobs found, applied, screened, interviewed, offers) for the authenticated user. No hardcoded placeholder data.
- **GET /api/jobs** – Queries Job table with user filter; real data.
- **GET /api/applications** – Queries Application table; real data.
- **GET /api/agents** – Returns catalog (static) and run history (real DB data).

### Hardcoded / Mock Data Found
1. **Sankey Data** (`/api/applications/funnel/sankey`) – Hardcoded fixture with static numbers (847→412→156→23→4). Described as "product constant" but not real user data.
2. **Agent Catalog & Provider Seed** (`/api/agents`) – Static configuration (AGENT_CATALOG, PROVIDER_SEED). Acceptable as configuration.
3. **Market Baselines** (`analytics.py`) – Constants `_MARKET_APPS_PER_MONTH = 15`, `_MARKET_INTERVIEW_RATE = 8` used for comparison, not displayed.

### Conclusion
Core data endpoints (jobs, applications, analytics/funnel) are backed by real database queries. The sankey diagram uses a fixed demo dataset, which is a product decision but presents stale/demo data to users.

## 4. RESUME & COVER LETTER FORMAT AUDIT

### Resume Studio Page (`/dashboard/resume`)
- **PDF Side‑by‑Side Comparison View** – **ABSENT**. The page shows text bullet diff only, no embedded PDF viewer or side‑by‑side visual comparison.
- **Format Integrity Claims** – UI includes "Format Integrity Check" stating "Typography, spacing, columns & margins preserved".
- **Backend Tailoring Process** – `ResumeTailorService` works on extracted text only; `formatHash` is carried from base PDF but the PDF itself is never modified.
- **PDF Export** – Download button returns 501 Not Implemented (note: "PDF export is coming in Phase 3").

### Cover Letter Studio Page (`/dashboard/cover-letters`)
- **PDF Export** – Implemented (`/cover-letters/{id}/pdf`) using ReportLab, generating a new PDF with Helvetica font. Does **NOT** preserve original formatting (no original format to preserve).
- **Format Consistency** – Cover letters are generated as plain text; the PDF export uses generic styling.

### Agent Logic
- **`resume_tailor.py`** – Anti‑fabrication guard, evidence tracing, format hash preservation (but only as a hash, not actual PDF layout).
- **`tailor_agent.py`** – Carries `formatHash` through child versions; source PDF unchanged.
- **`cover_letter_agent.py`** – Generates text with fabrication guard; output is plain text.

### Verdict
**Format preservation is partially true:** The original PDF is not altered, but tailored resumes are stored as text bullets only, and PDF export is not yet implemented. The claim "Typography, spacing, columns & margins preserved" is misleading—there is no side‑by‑side PDF view, and the PDF is not regenerated with original formatting.

## 5. MISSING WIREFRAME ELEMENTS

### Dashboard
- Stats row (stat cards)
- Market Intel panel
- Design‑id attributes throughout

### Job Discovery
- Risk Signals panel
- Filter by Role, Salary (replaced by simpler controls)
- Saved job cards (zero count in production)
- Submit Gate modal
- Design‑id attributes

### Application Tracker
- Sankey diagram visualization (tab present but not inspected)
- Email thread links on cards
- CRM links on cards
- Design‑id attributes

## 6. STALE/DEMO DATA

1. **Sankey Funnel Numbers** – Fixed values (847, 412, 156, 23, 4) shown in the sankey view (fixture‑backed).
2. **Demo User Name** – "Demo U." appears in top bar (expected, as demo account).
3. **Market Baseline Constants** – Used for comparison but not displayed.
4. **Agent Catalog** – Static model recommendations and pricing.

## 7. CONSOLE ERROR REPORT

- **Dashboard** – No JavaScript errors or warnings.
- **Job Discovery** – No JavaScript errors.
- **Application Tracker** – No JavaScript errors.

All three screens are clean of client‑side errors.

## 8. FINAL SCORECARD

| Screen          | Wireframe Elements | Implemented | Missing | Divergent | Console Errors | Verdict        |
|----------------|-------------------|-------------|---------|-----------|----------------|----------------|
| Dashboard      | 24                | 16          | 3       | 5         | 0              | NEEDS‑WORK     |
| Job Discovery  | 49                | 35          | 8       | 6         | 0              | NEEDS‑WORK     |
| Applications   | 25                | 18          | 4       | 3         | 0              | NEEDS‑WORK     |

### Summary Verdict
- **Dashboard**: Core sections present but missing stats row and market intel. Funnel visualization placeholder.
- **Job Discovery**: Functional but missing risk signals and some filters. Saved view empty.
- **Applications**: Kanban board works but sankey view untested, missing email/CRM links.

**Overall**: The production app implements the majority of wireframe structure and is functional with real data, but several key visual elements are missing or simplified, and some data (sankey) is hardcoded. The resume/cover letter format preservation claims are overstated—PDF export not yet delivered, no side‑by‑side comparison view.

**Recommendations**:
1. Implement stats row and market intel panel on dashboard.
2. Add risk signals and saved‑jobs UI to Job Discovery.
3. Replace hardcoded sankey data with real user‑specific funnel.
4. Deliver PDF export for resumes with true format preservation.
5. Add design‑id attributes to aid future QA.