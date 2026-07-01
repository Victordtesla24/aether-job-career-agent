# Aether AI Job Application Platform — Design Review & Adversarial Audit

**Reviewer:** Senior QA / Design Auditor  
**Date:** 1 July 2026  
**Scope:** All 16 high-fidelity HTML wireframe screens  
**Verdict:** Strong foundational design with **critical navigation inconsistencies, several data-flow gaps, and missing safety rails** that would undermine job application outcomes in production.

---

## CRITICAL CROSS-SCREEN ISSUE: Navigation Inconsistency

**Severity: BLOCKER — must fix before any development begins.**

The sidebar navigation is **not consistent across screens**. There are two distinct navigation schemas in use:

### Schema A (12-item nav — used by 10 screens):
Dashboard → Jobs → Resume Studio → Story Bank → Applications → Interview Center → Networking → Email Center → Agents → Analytics → Offers → Settings

**Used by:** dashboard, job-discovery, resume-studio, story-bank, application-tracker, interview-center, networking, email-center, offer-comparison

### Schema B (9-item nav — used by 4 screens):
Dashboard → Jobs → Applications → Resume Studio → Cover Letters → Email Center → Agents → Analytics → Settings

**Used by:** agents, agent-monitor, analytics, settings

### What's broken:
- Schema B **removes** Story Bank, Interview Center, Networking, and Offers — four core screens that exist and are fully designed
- Schema B **adds** "Cover Letters" which has **no corresponding screen** in the design
- Schema B **reorders** items (Applications before Resume Studio)
- The Aether logo itself differs: Schema A uses `from-[#FF6B35] to-[#F59E0B]` gradient, Schema B uses `from-[#FF6B35] to-[#4F46E5]` gradient
- The sidebar bottom widget differs: Schema A has "Agents Active" status, Schema B has user profile card (some screens), or agent count

**Impact:** A user navigating from Job Discovery to Agents would see 4 nav items disappear and a phantom "Cover Letters" item appear. This destroys spatial memory and trust in the platform.

**Recommendation:** Standardize on Schema A (12-item) across all 16 screens. Remove "Cover Letters" as a standalone nav item (it's a sub-feature of Resume Studio or Email Center). Standardize the logo gradient and sidebar bottom widget.

---

## Screen-by-Screen Review

---

### 1. Dashboard (`dashboard.html`)

**Strengths:**
- Excellent information density without cognitive overload. The 4-stat row gives immediate pulse. Agent activity feed with live indicator creates urgency and trust. Application funnel on the right provides strategic context. Market Intelligence section with demand heatmap, salary trends, and "Best Time to Apply" is genuinely differentiated and actionable. The "Where to Focus" AI recommendation card is the kind of proactive guidance that maximizes outcomes.

**Weaknesses / Issues:**
- The "Today's Opportunities" section shows 3 job cards but the first card (Canva) says "Senior ML Engineer" while the agent feed says the Discovery Agent found "Senior ML Engineer at Canva" — but the job-discovery screen shows the top match as "Senior Technical Program Manager" at Canva. **Data inconsistency across screens.** Which role is it?
- The opportunity cards show salary in USD format ($180k) but the Market Intelligence section shows "AU $180–220K" — the currency context is missing from the opportunity cards. For an Australian user, this ambiguity could lead to misaligned salary expectations.
- "AI Confidence 91%" is vague — confidence in what? Match quality? Agent accuracy? This needs a tooltip or subtitle.
- The "Recruiter CRM" summary says "2 follow-ups due today" but there's no visual urgency (no red/amber indicator). Follow-ups are time-critical.
- No date/time context on the dashboard beyond the greeting. The user can't tell when data was last refreshed.

**Missing Elements:**
- No "Rejected/Ghosted" count — the user only sees positive metrics. Showing rejection data helps calibrate expectations and identify patterns.
- No upcoming interview countdown. The Interview Center shows "Tomorrow 10:00 AEST" but the dashboard doesn't surface this. **This is the highest-priority action a job seeker has.**
- No link to the Sankey flow view from the funnel widget.
- No notification panel design — the bell icon has a dot but no dropdown wireframe.

**Adversarial Findings:**
- If all agents are paused or erroring, the dashboard still shows "Agents Active" with a green dot. There's no degraded state shown.
- The "Tailor & Apply" button on opportunity cards implies one-click application. If the approval gate is on (as shown in settings), this button's label is misleading — it should say "Tailor & Review" or similar.

**Recommendations:**
1. Add an "Upcoming Interview" banner at the top of the dashboard when an interview is within 48 hours — this is the single highest-value action.
2. Standardize currency display: always prefix with AU$ or US$ on every salary figure.
3. Add a "Last refreshed" timestamp to the stats row.
4. Surface rejection/ghosting rate alongside interview rate for honest calibration.

---

### 2. Job Discovery (`job-discovery.html`)

**Strengths:**
- The Australia/International tab split with source integration bar is excellent for the AU market. Showing Seek, LinkedIn AU, Workforce Australia, Jora, and Indeed with connection status is practical and differentiated. The "Playwright session" label for Seek is honest about the scraping mechanism. The 10-Dimensional Fit Score with radar chart is sophisticated and builds trust. Risk Signals section (high applicant volume, role reposted, no salary listed, low recruiter response) is genuinely valuable intelligence that most platforms hide. Bulk "Tailor & Apply (4)" action is efficient. Source badges on each job card (Seek, LinkedIn, Workforce AU, Jora) provide provenance.

**Weaknesses / Issues:**
- The detail panel shows "No salary listed" as a risk signal, but the job card and detail header both show "$180k–$220k". **Contradictory data.**
- The "Voice-Authentic" badge and "AI detection 2%" appear on the detail panel but this is a job listing view, not a resume/cover letter view. This badge belongs on Resume Studio or Email Center output, not on a job listing.
- The match slider shows "Match ≥ 80%" but the filter bar doesn't show what the current active filters are (e.g., which roles, which locations). The "Remote · Hybrid" filter appears active (purple) but there's no way to see what "Role" or "Location" are set to.
- Job card #4 (NAB) shows source as "Jora" but Jora is shown as "Not connected" in the source bar. **How was this job discovered from a disconnected source?**

**Missing Elements:**
- No "Save for later" or "Bookmark" action on job cards — only "Tailor & Apply", "Review Match", and "Skip". What if the user wants to come back to it?
- No "Why not?" explanation for jobs below the threshold that were filtered out.
- No pagination or "Load more" for the job list (only 4 cards shown, but 98 matches claimed).
- No "Company research" link from the detail panel — the Company Research Agent exists but isn't surfaced here.
- No "Similar roles" or "People also applied to" section.

**Adversarial Findings:**
- The "Tailor & Apply" button on the detail panel is a high-stakes action. If clicked accidentally, there's no confirmation step shown in this wireframe. The approval modal exists but the flow from this button to that modal isn't clear.
- The bulk "Tailor & Apply (4)" button could trigger 4 simultaneous applications. If the user hasn't reviewed all 4, this is dangerous. The checkbox "Select all" is checked but the user may not have scrolled through all selected items.

**Recommendations:**
1. Fix the salary/risk signal contradiction.
2. Remove the "Voice-Authentic" badge from the job listing view.
3. Add a "Save" action to each job card.
4. Add a "Company Intel" expandable section in the detail panel that surfaces Company Research Agent output.
5. Show a confirmation step for bulk actions: "You're about to tailor & apply to 4 roles. Review each?"

---

### 3. Resume Studio (`resume-studio.html`)

**Strengths:**
- The side-by-side original/tailored view is the gold standard for resume tailoring UIs. Highlighted changes (orange for keyword insertions, green for additions) make diffs instantly scannable. The Evidence Trace section is exceptional — showing the chain from portfolio → GitHub → resume line builds trust and prevents hallucination. Voice DNA controls (tone, formality sliders) with AI Detection score (2% Safe) directly address the #1 fear of AI-assisted applications. Format Integrity Check with "0 format changes · layout locked" is a strong trust signal. Version history (v1, v2, v3) enables rollback.

**Weaknesses / Issues:**
- The original resume shows "Page 1 of 3" but only page 1 is rendered. There's no indication of what's on pages 2-3 or whether the tailoring affected those pages.
- The target dropdown shows "Senior TPM · ANZ Bank" but the dashboard shows the top opportunity as Canva. The user needs to understand which job this tailoring is for and how to switch targets.
- The ATS score (96) appears in 3 different places on this screen (top bar, tailored pane header, and integrity strip). This is redundant and wastes space.
- The "Request Changes" button has no indication of what kind of changes can be requested or how the feedback loop works.

**Missing Elements:**
- No "Compare with job description" view — the user can see the tailored resume but can't see the JD it was tailored against side-by-side.
- No cover letter preview or generation trigger from this screen. The cover letter is a companion artifact to the resume.
- No word count or page count warning if tailoring pushes content beyond page limits.
- No "Download original" button — only "Export PDF" for the tailored version.

**Adversarial Findings:**
- The Evidence Trace shows "GitHub commit history" as a source, but if the user's GitHub has private repos, the agent may not have access. There's no indication of which repos were scanned or whether access was granted.
- The "Approve Tailoring" button is the final gate before the resume is used. But there's no preview of where it will be used (which application? which job board?).

**Recommendations:**
1. Add a "View Job Description" toggle that shows the target JD alongside the tailored resume.
2. Show a page count indicator and warn if tailoring exceeds the original page count.
3. Consolidate ATS score display to one prominent location.
4. Add a "What happens next?" tooltip on the Approve button explaining the downstream flow.

---

### 4. Story Bank (`story-bank.html`)

**Strengths:**
- STAR+R format with quantified impact scores is excellent. The Interview Question Mapper on the right directly connects stories to likely questions — this is the bridge between preparation and performance. Coverage Gaps section proactively identifies missing narratives (conflict resolution, failure/lessons learned, stakeholder influence). "Draft missing stories" button is a smart AI-assisted gap-filler. Voice match percentage per story ensures consistency.

**Weaknesses / Issues:**
- The sidebar in this screen uses Schema A (correct) but the logo gradient uses `from-[#FF6B35] to-[#4F46E5]` instead of `from-[#FF6B35] to-[#F59E0B]`. Minor inconsistency but noticeable.
- The bottom user profile card shows "Senior TPM" but the settings screen shows target role as "Senior ML / Software Engineer". **Identity confusion.**
- Only 3 stories are shown but the stats say "24 Total Stories". No pagination, search, or scroll indicator.
- The "Insert" button on each story card has no context — insert where? Into which resume? Which cover letter?

**Missing Elements:**
- No way to edit a story inline. The ellipsis menu (⋯) suggests a dropdown but no dropdown is designed.
- No "Archive" or "Retire" action for outdated stories.
- No search/filter by keyword within stories.
- No "Suggested stories from your resume" — the system should auto-extract STAR stories from the uploaded resume.
- The "R" in STAR+R (Reflection) is mentioned in the header but not shown in any story card. Each card only shows S, T, A, R.

**Adversarial Findings:**
- The Coverage Gaps section shows "Conflict resolution — No story" and "Failure / lessons learned — No story". These are the two most common behavioral interview questions. If the user doesn't address these gaps, interview performance will suffer significantly. The "Draft missing stories" button is good but it's buried — this should be a prominent alert.

**Recommendations:**
1. Add the "R" (Reflection) column to story cards to complete the STAR+R framework.
2. Make Coverage Gaps a top-of-page alert banner, not a sidebar widget.
3. Add "Insert into…" context menu showing available resumes/cover letters/interview prep.
4. Add auto-extraction of stories from the uploaded resume.

---

### 5. Application Tracker (`application-tracker.html`)

**Strengths:**
- Kanban board with 8 columns (Discovered → Evaluating → Tailoring → Ready to Apply → Submitted → In Review → Interview → Offer) covers the full lifecycle. The Sankey Flow visualization below is exceptional — showing drop-off at each stage with specific numbers ("Evaluated → Applied: −35 lost") is actionable intelligence. Board/Sankey/Timeline view toggle provides flexibility. Each card shows match score, company, and status.

**Weaknesses / Issues:**
- The Kanban board shows 8 columns but the header says "9 stages". **Count mismatch.** (The Sankey shows 6 stages, adding further confusion.)
- The Sankey numbers don't match the Kanban numbers: Sankey shows 100 Discovered, 80 Evaluated, 45 Applied — but the dashboard funnel shows 142 Discovered, 98 Evaluated, 37 Applied. **Three different datasets for the same funnel.**
- Column widths are fixed at 260px each, making 8 columns = 2080px. This exceeds the 1192px available content width (1440 - 248 sidebar). The horizontal scroll is acknowledged but the UX of scrolling a Kanban board is poor — the user can only see ~4.5 columns at once.
- The "Offer" column card shows "decide by Jul 8" but there's no countdown timer or urgency indicator. Offer deadlines are the most time-critical element in a job search.

**Missing Elements:**
- No "Withdrawn" or "Rejected" column. Where do rejected applications go? They just disappear from the board?
- No drag-and-drop affordance on cards (no grab cursor, no drag handle).
- No card detail view — clicking a card should open a detail panel or modal.
- No "Archive" or "Hide" for old/irrelevant applications.
- The Timeline view is mentioned but not designed.
- No bulk actions on the Kanban (e.g., "withdraw all" for a company that ghosted).

**Adversarial Findings:**
- The biggest drop-off is "Evaluated → Applied (−35 lost)" per the Sankey. The insight text says "consider raising the match threshold" — but this is backwards. Raising the threshold would reduce the number evaluated, not improve the conversion from evaluated to applied. The AI recommendation is potentially harmful.
- If the user has 37 active applications (per dashboard), the Kanban should show 37 cards distributed across columns. But the visible cards only total ~15. Where are the other 22?

**Recommendations:**
1. **Fix the funnel data inconsistency** across dashboard, tracker, and analytics. Use one source of truth.
2. Add "Rejected" and "Withdrawn" columns (or a collapsed archive section).
3. Add offer deadline countdown with color-coded urgency (red < 3 days).
4. Fix the Sankey recommendation — it should suggest improving application quality, not raising the threshold.
5. Design the Timeline view.

---

### 6. Interview Center (`interview-center.html`)

**Strengths:**
- Company & Role Brief with interviewer background (Dir. of Eng · ex-Atlassian) is excellent preparation material. Predicted Questions with likelihood ratings and mapped stories create a direct prep-to-performance pipeline. Live Assist preview showing filler words, speaking pace, and talk/listen ratio is innovative. Last Debrief section with performance score and specific feedback creates a learning loop.

**Weaknesses / Issues:**
- The screen is titled "Senior TPM – Canva" but the header says "Round 2 · Hiring Manager · Tomorrow 10:00 AEST". The dashboard doesn't surface this upcoming interview. **Critical disconnect.**
- Only 3 predicted questions are shown but the header says "12 generated". No way to see the other 9.
- The Live Assist tab and Debrief tab are shown but not designed. These are arguably the most valuable features of the Interview Center.
- The "Agent prep 90% ready" indicator has no breakdown of what's missing in the remaining 10%.

**Missing Elements:**
- No mock interview launcher. The Interview Prep Agent exists but there's no "Start Mock Interview" button.
- No calendar integration showing the interview in context with other commitments.
- No "Questions to ask the interviewer" section — this is standard interview prep.
- No recording/transcript capability for post-interview analysis.
- No multi-round tracking — the screen shows Round 2 but there's no history of Round 1 performance or how it informed Round 2 prep.
- No "Reschedule" or "Cancel" action.

**Adversarial Findings:**
- The Live Assist feature shows real-time coaching cues like "Add the 92% metric now." If this is meant to be used during a live interview, it raises ethical concerns about AI-assisted interviewing. The design doesn't address whether this is for practice or live use.
- The debrief shows "Stripe · Round 1" with score 8.4, but there's no Stripe interview visible in the Application Tracker's Interview column (which shows only "Staff Engineer · Stripe · round 2 · Jul 3"). The debrief data doesn't connect to the tracker.

**Recommendations:**
1. Add a "Start Mock Interview" CTA prominently.
2. Design the Live Assist and Debrief tabs — these are the highest-value features.
3. Add "Questions to ask them" section.
4. Clarify the ethical boundary of Live Assist (practice only vs. live interview).
5. Surface upcoming interviews on the dashboard.

---

### 7. Networking / CRM (`networking.html`)

**Strengths:**
- 5-stage pipeline (New → Warm → Active → Scheduled → Placed) mirrors a sales CRM, which is appropriate for job search networking. Outreach Queue with AI-drafted messages and scheduled sends is practical. Communication Log provides conversation history. Stats (48 contacts, 12 active threads, 5 referrals, 41% response rate) give strategic overview.

**Weaknesses / Issues:**
- Only 1 contact card per pipeline stage is shown. With 48 total contacts, the user can't see the full pipeline.
- No search or filter for contacts.
- The "Placed" stage label is confusing — does it mean the contact placed the user in a role, or the contact was placed in the pipeline? "Converted" or "Referral Secured" would be clearer.
- No indication of which contacts are linked to which job applications.

**Missing Elements:**
- No contact detail view — clicking a contact should show full history, linked applications, and relationship timeline.
- No LinkedIn integration indicator per contact (can the agent auto-connect or message?).
- No "Stale contact" warning for contacts that haven't been engaged in X days.
- No referral tracking — the stat says "5 Referrals Secured" but there's no way to see which referrals led to which applications.
- No "Import contacts" from LinkedIn or email.

**Adversarial Findings:**
- The Outreach Queue shows "Sends tomorrow 9:00 AEST" for an intro message. If the user hasn't reviewed the draft, an AI-generated message goes out under their name. The approval gate for outreach messages isn't visible.

**Recommendations:**
1. Add contact detail view with full relationship timeline.
2. Link contacts to specific job applications.
3. Add "Stale contact" alerts for contacts not engaged in 7+ days.
4. Show approval gate status for outgoing messages.

---

### 8. Email Center (`email-center.html`)

**Strengths:**
- This is the most feature-complete screen in the platform. Multi-account support (two Gmail accounts), smart inbox with AI classification, interview conversion scoring per email, AI-generated replies with tone controls, Voice DNA authenticity check, automated follow-up engine with configurable parameters, recruiter profile cards, and email stats — all in one view. The spam detection ("TechRecruit AU" scored 21 with "Auto-detected spam") is practical. The follow-up engine settings (wait period, max follow-ups, top N applications, tone lock) give the user fine-grained control.

**Weaknesses / Issues:**
- The screen is extremely dense. Three columns plus a fixed bottom status bar creates information overload. On a 1440px screen with 248px sidebar, each column gets ~316px — very tight for email content.
- The "Interview Conversion Score" (82/100) on the AI Intelligence panel is a different metric from the "Interview Rate" (24%) on the dashboard. The relationship between these metrics is unclear.
- The email list shows account indicators (SV = sarkar.vikram, MV = melbvicduque) but these are tiny 6x6 circles that are hard to distinguish.
- The "Trash Automated/Spam" button is destructive and has no confirmation. If the AI misclassifies a legitimate recruiter email as spam, it's gone.

**Missing Elements:**
- No "Undo" for trash/spam actions.
- No email search within the inbox.
- No "Snooze" action for emails the user wants to deal with later.
- No template library for common responses.
- No "Unsubscribe" action for mass outreach emails.
- The "Compose" button exists but no compose view is designed.

**Adversarial Findings:**
- The auto-reply mode is set to "Draft for Review" but the status bar shows "Auto-reply mode: Draft for Review" — if this is accidentally toggled to "Auto-send", the AI sends emails on the user's behalf without review. This is the highest-risk automation in the entire platform. The toggle is a small button in a fixed footer bar that could be accidentally clicked.
- Email item #2 shows "Auto-replied" for David Okoro at Canva. If the auto-reply was inappropriate or contained errors, the damage is done. There's no "recall" or "undo send" capability shown.

**Recommendations:**
1. Add confirmation dialog for "Trash Automated/Spam" with a list of what will be trashed.
2. Make the auto-reply mode toggle require a confirmation step, not a single click.
3. Add email search.
4. Add "Undo" for all destructive actions with a 10-second grace period.
5. Design the compose view.

---

### 9. Agents (`agents.html`)

**Strengths:**
- 20 agents with individual model assignments, status indicators, and hover tooltips explaining best model choices is excellent transparency. 6 AI provider connections (Anthropic, OpenRouter, OpenAI, Google Gemini, AWS Bedrock, Groq) with connection status, credit/token remaining, and model selection dropdowns. The error state on Sentiment Analysis Agent ("Groq rate limit exceeded — reassign a model") is realistic. API spend tracking ($48.72/month) and token usage (3.42M) provide cost visibility.

**Weaknesses / Issues:**
- **Navigation uses Schema B** — missing Story Bank, Interview Center, Networking, Offers. Also adds "Cover Letters" which doesn't exist as a screen.
- The nav order is different: Applications comes before Resume Studio, which is inconsistent with all other screens.
- 20 agent cards in a 4-column grid creates a very long page. No grouping, categorization, or collapsible sections.
- The "Run All" button would start all 20 agents simultaneously. There's no indication of cost impact or what "Run All" means in practice.
- The Follow-up Agent is "Paused" but there's no indication of why or how to resume it.
- The Sentiment Analysis Agent shows "Error" but the only action is the toggle switch. There's no "Fix" or "Reassign model" button.

**Missing Elements:**
- No agent dependency visualization (which agents depend on which).
- No cost-per-agent breakdown.
- No agent logs or history per agent.
- No "Create custom agent" capability.
- No agent grouping (e.g., "Discovery agents", "Application agents", "Communication agents").

**Adversarial Findings:**
- The header says "20 agents" but the sidebar widget says "18 / 20 Active" with "1 paused · 1 needs attention". The visible cards show 18 active + 1 paused + 1 error = 20. This is consistent, but the sidebar widget is only visible on this screen — other screens show different sidebar widgets.
- Google Gemini shows "Token expiring in 3 days" — if this expires and agents depend on Gemini, they'll fail silently. There's no alert escalation or fallback model configuration.

**Recommendations:**
1. **Fix navigation to Schema A** (12 items).
2. Group agents by function (Discovery, Tailoring, Communication, Intelligence, Infrastructure).
3. Add cost-per-agent in the card.
4. Add "Reassign model" action on error-state agents.
5. Add provider expiry alerts that surface on the dashboard.

---

### 10. Agent Monitor (`agent-monitor.html`)

**Strengths:**
- Workflow graph with animated data flow lines between nodes (Discovery → Evaluator → Tailoring → Submission, with Learning and Memory nodes) provides real-time visibility. Task queue with progress bars. Performance metrics (1,284 tasks done, 3.2s avg, 98.4% success). Error log with severity levels (ERR, WRN, OK).

**Weaknesses / Issues:**
- **Navigation uses Schema B** — same issues as Agents screen.
- The workflow graph only shows 6 nodes but there are 20 agents. Where are the other 14?
- The "Manual Override" button has no indication of what it does or what the consequences are.
- The error log shows only 3 entries. No pagination, filtering, or search.
- The "Pause All" button is a global kill switch with no confirmation.

**Missing Elements:**
- No agent-to-agent communication log.
- No resource utilization (CPU, memory, API rate limits).
- No historical performance trends.
- No alert configuration (when should the user be notified?).

**Recommendations:**
1. Fix navigation.
2. Show all 20 agents in the workflow graph or provide a way to filter/zoom.
3. Add confirmation for "Pause All" and "Manual Override".
4. Add historical performance charts.

---

### 11. Analytics (`analytics.html`)

**Strengths:**
- Application funnel bar chart, interview conversion line chart, source distribution donut, skills demand bars, ATS score distribution histogram, and activity heatmap provide comprehensive analytics. The "Real-Time Market Pulse" section with Job Probability Score (68%), Employer Hiring Activity feed, and Recruiter Activity trends is genuinely differentiated. The probability score breakdown (application volume, market demand, profile match, interview conversion) is actionable.

**Weaknesses / Issues:**
- **Navigation uses Schema B** — missing 4 screens.
- The funnel shows 142/98/37/9/3 — same as dashboard. But the Application Tracker Sankey shows 100/80/45/30/12/3. **Still inconsistent.**
- The "Applications by Source" donut shows LinkedIn 49%, Seek 30%, Indeed 21% — but Indeed AU is shown as "Not connected" on the Job Discovery screen. **How are 21% of applications coming from a disconnected source?**
- The activity heatmap uses `document.write` with `Math.random()` — this means the heatmap shows different data every time the page loads. This is a wireframe artifact but should be noted.
- Interview conversion shows "+3.2%" but the dashboard shows "+3.2% vs avg" — these might be different metrics presented with the same number.

**Missing Elements:**
- No time-to-hire metric (average days from application to offer).
- No rejection reason analysis (why are applications being rejected?).
- No A/B testing data (which resume version performed better?).
- No ROI calculation (cost of AI agents vs. value of interviews/offers generated).
- No export format options (the Export button exists but no format selection).

**Adversarial Findings:**
- The "Interview conversion" metric shows 14% in the probability score breakdown but 24% on the dashboard. These are likely different calculations but the user sees contradictory numbers.

**Recommendations:**
1. Fix navigation.
2. Reconcile all funnel numbers across dashboard, tracker, and analytics.
3. Add time-to-hire and rejection analysis.
4. Add ROI calculation showing agent cost vs. interview value.

---

### 12. Offer Comparison (`offer-comparison.html`)

**Strengths:**
- Side-by-side offer cards with total comp breakdown (base, bonus, equity, location). Priority Weights with adjustable sliders (compensation 30%, growth 25%, culture 20%, work-life 15%, location 10%). Negotiation Coach with specific counter-offer suggestion ($195k base) and leverage analysis (2 competing offers). "Draft counter email" button connects to the Email Center.

**Weaknesses / Issues:**
- Only 3 offers shown but the dashboard says "3 offers, 2 pending decision". There's no indication of which offers are pending vs. decided.
- The "Fit score" on offer cards (91, 84, 79) doesn't explain what dimensions contribute to the score. The Job Discovery screen has a 10-dimensional breakdown but the Offer screen doesn't.
- No offer deadline/expiry shown. The Application Tracker shows "decide by Jul 8" for Vercel but the Offer Comparison shows Canva, Atlassian, and ANZ — different companies entirely. **Data inconsistency.**
- The Priority Weights sliders appear static — there's no indication they're interactive or that changing them would re-rank the offers.

**Missing Elements:**
- No "Decline offer" action.
- No "Accept offer" action with confirmation flow.
- No tax/take-home calculation (critical for comparing AU offers with different structures).
- No benefits comparison (leave, health, remote policy, learning budget).
- No "What if" scenario modeling (e.g., "What if Canva increases base by $10k?").
- No offer letter upload/attachment.
- No timeline view showing offer deadlines.

**Adversarial Findings:**
- The Negotiation Coach says "Canva base is $10k below market P75" — but this claim isn't sourced. If the market data is wrong, the user could make an aggressive counter-offer based on bad intelligence and lose the offer.
- The "2 competing offers" leverage claim assumes the user will disclose competing offers. This is a negotiation strategy choice, not a fact. The AI should present this as an option, not a recommendation.

**Recommendations:**
1. Add offer deadline countdown with urgency indicators.
2. Add "Accept" and "Decline" actions with confirmation flows.
3. Add benefits comparison table.
4. Add take-home pay calculator.
5. Source the market data claim with a link or methodology note.
6. Reconcile offer companies between tracker and comparison screen.

---

### 13. Settings (`settings.html`)

**Strengths:**
- Clean sub-navigation (Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance). Agent Configuration with auto-apply toggle (off), approval gate for cover letters (on), and match score threshold (80%) gives the user control over automation boundaries. Resume management shows the active base resume with upload capability.

**Weaknesses / Issues:**
- **Navigation uses Schema B** — missing 4 screens.
- The Profile section shows target role as "Senior ML / Software Engineer" but the entire platform is designed around "Senior TPM / Delivery Manager". **Critical identity mismatch.** The AI agents would be optimizing for the wrong role.
- The email field shows "vikram@email.com" but the Email Center shows "sarkar.vikram@gmail.com" and "melbvicduque@gmail.com". Which is the primary email?
- The location shows "Sydney, Australia" but the resume shows "Melbourne, VIC, Australia". **Location mismatch.**
- Only the "Profile" sub-page is designed. The other 6 sub-pages (Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance) are not wireframed.
- The Integrations section shows Seek as "not linked" but the Job Discovery screen shows Seek as "Connected · via Browser". **Inconsistency.**

**Missing Elements:**
- No data export/deletion (GDPR/privacy compliance).
- No account deletion flow.
- No two-factor authentication settings.
- No API key management (the Agents screen handles this but Settings should reference it).
- No notification preferences (email, push, in-app).
- No "Danger zone" for destructive actions.
- No salary target/range configuration (referenced by the approval modal but not configurable here).

**Adversarial Findings:**
- The auto-apply toggle is OFF, which is safe. But if a user accidentally turns it ON, there's no confirmation dialog, no "are you sure?", and no way to set a daily limit. The agent could submit dozens of applications without review.
- The match score threshold is 80% but there's no explanation of what happens to jobs below 80% — are they hidden? Archived? Still visible but not acted upon?

**Recommendations:**
1. **Fix the target role to match the platform's actual optimization target.**
2. Fix location to match resume.
3. Fix email to match Email Center accounts.
4. Fix Seek integration status to match Job Discovery.
5. Add confirmation dialog for auto-apply toggle.
6. Add daily application limit setting.
7. Add salary target range configuration.
8. Design the remaining 6 sub-pages.

---

### 14. Approval Modal (`approval-modal.html`)

**Strengths:**
- Clear "Why approval is needed" explanation. AI reasoning with checkmarks and warnings. Cover letter preview. "Trust this agent for similar decisions" checkbox enables progressive automation. Three-action footer (Reject, Edit & Approve, Approve) covers all decision paths.

**Weaknesses / Issues:**
- The modal shows "Senior ML Engineer · Canva" but the Job Discovery screen's top match for Canva is "Senior Technical Program Manager". **Role name inconsistency again.**
- The "Trust this agent" checkbox has no scope definition — "similar decisions" is vague. Does it mean same company? Same role type? Same confidence level?
- The cover letter preview is truncated (line-clamp-3) with no "Read full" option. The user is asked to approve something they can't fully read.
- No "Request changes" option — only Reject, Edit & Approve, or Approve. What if the user wants the agent to regenerate with different parameters?

**Missing Elements:**
- No history of previous approvals/rejections for context.
- No "Snooze" or "Decide later" option.
- No indication of urgency (is this time-sensitive?).
- No link to the full job listing for context.

**Recommendations:**
1. Add "Read full cover letter" expansion.
2. Define the scope of "Trust this agent" more precisely.
3. Add "Regenerate" as a fourth action.
4. Add a link to the job listing.

---

### 15. Mobile Dashboard (`mobile-dashboard.html`)

**Strengths:**
- Clean 2x2 stat grid mirrors the desktop dashboard. Approval banner with "Review Now" CTA prioritizes the most important mobile action. Agent activity feed is appropriately condensed. Bottom tab bar (Home, Jobs, Apps, Agents, Profile) covers the 5 most critical mobile actions.

**Weaknesses / Issues:**
- The bottom tab bar has 5 items but the desktop has 12 nav items. The mobile nav omits Resume Studio, Story Bank, Interview Center, Networking, Email Center, Analytics, Offers, and Settings. Some of these (Interview Center, Email Center) are high-urgency actions that a user would need on mobile.
- No pull-to-refresh indicator.
- No "Upcoming interview" alert — this is the #1 mobile use case.

**Missing Elements:**
- No quick-approve swipe gesture on approval items.
- No push notification indicator beyond the bell icon.
- No "Interview in X hours" countdown banner.
- No email notification badge on the tab bar.

**Recommendations:**
1. Add Interview Center to the mobile tab bar (replace "Profile" with a hamburger menu that includes Profile, Settings, etc.).
2. Add interview countdown banner when an interview is within 24 hours.
3. Add notification badges on tab bar items.

---

### 16. Mobile Approval (`mobile-approval.html`)

**Strengths:**
- Full-screen approval flow with clear action hierarchy (Approve & Submit as primary, Edit and Reject as secondary). AI reasoning is fully visible. "Trust this agent" checkbox is present. Sticky footer ensures actions are always accessible.

**Weaknesses / Issues:**
- "1 of 2 pending" indicator but no swipe-to-next gesture or "Next" button to move to the second approval.
- The cover letter preview from the desktop modal is missing entirely on mobile. The user is approving without seeing what will be sent.
- No haptic feedback indication for the approve action (design consideration for implementation).

**Missing Elements:**
- No cover letter preview.
- No "View job listing" link.
- No swipe navigation between pending approvals.

**Recommendations:**
1. Add cover letter preview (collapsible).
2. Add swipe or "Next" navigation between pending approvals.
3. Add "View job" link.

---

## Cross-Screen Data Flow Issues

### Funnel Numbers (3 different datasets):
| Source | Discovered | Evaluated | Applied | Interview | Offer |
|--------|-----------|-----------|---------|-----------|-------|
| Dashboard Funnel | 142 | 98 | 37 | 9 | 3 |
| Tracker Sankey | 100 | 80 | 45 | 12 | 3 |
| Analytics Funnel | 142 | 98 | 37 | 9 | 3 |

The Sankey uses completely different numbers. This must be reconciled.

### Role Name Inconsistencies:
- Dashboard opportunity card: "Senior ML Engineer" at Canva
- Job Discovery top match: "Senior Technical Program Manager" at Canva
- Approval Modal: "Senior ML Engineer" at Canva
- Interview Center: "Senior TPM – Canva"

### Profile Data Inconsistencies:
| Field | Settings | Resume | Email Center | Dashboard |
|-------|----------|--------|-------------|-----------|
| Target Role | Senior ML / Software Engineer | Senior TPM / AI Solutions Architect | — | — |
| Email | vikram@email.com | sarkar.vikram@gmail.com | sarkar.vikram@gmail.com + melbvicduque@gmail.com | — |
| Location | Sydney, Australia | Melbourne, VIC, Australia | — | — |
| GitHub | github.com/vikramd | github.com/Victordtesla24 | — | — |

### Integration Status Inconsistencies:
| Service | Job Discovery | Settings |
|---------|--------------|----------|
| Seek | Connected · via Browser | Not linked |
| Indeed AU | Not connected | — (not shown) |

### Source Data Inconsistency:
- Analytics shows 21% of applications from Indeed, but Indeed is "Not connected" on Job Discovery
- Job card #4 (NAB) sourced from Jora, but Jora is "Not connected"

---

## User Journey Gaps

1. **Onboarding flow is completely missing.** How does a new user set up their profile, upload their resume, connect job boards, and configure agents? There's no first-run experience.

2. **Resume upload → Story Bank extraction flow is missing.** The Story Bank should auto-populate from the uploaded resume, but there's no indication of this connection.

3. **Job Discovery → Application Tracker handoff is unclear.** When the user clicks "Tailor & Apply", what happens? Does it go to Resume Studio first? Directly to the tracker? Through the approval modal?

4. **Interview scheduling flow is missing.** The Interview Center shows an upcoming interview but there's no flow for how it got scheduled — was it through the Email Center? The Scheduling Agent? Manual entry?

5. **Offer acceptance → job search wind-down flow is missing.** When the user accepts an offer, what happens to active applications? Are they automatically withdrawn? Are agents paused?

6. **Error recovery flows are missing.** What happens when an agent fails? When an API key expires? When a job board connection drops? The error states are shown but recovery paths aren't designed.

---

## Top 10 Actionable Recommendations (Priority Order)

1. **Standardize navigation across all 16 screens** to the 12-item Schema A. This is a blocker.

2. **Reconcile all data inconsistencies** (funnel numbers, role names, profile data, integration status, source data). Create a single data model document.

3. **Add upcoming interview countdown to the dashboard** — this is the highest-value, most time-sensitive information for any job seeker.

4. **Design the Interview Center Live Assist and Debrief tabs** — these are the most differentiated features and they're unfinished.

5. **Add confirmation dialogs for all high-stakes actions** (auto-apply toggle, bulk apply, trash emails, pause all agents, approve application).

6. **Fix the Settings screen** — target role, location, email, and GitHub URL all contradict other screens. This is the source of truth for the entire platform.

7. **Add offer deadline countdowns** to both the dashboard and the Offer Comparison screen with color-coded urgency.

8. **Design the onboarding flow** — without it, no user can actually start using the platform.

9. **Add "Rejected/Withdrawn" tracking** to the Application Tracker — hiding failures creates a false sense of progress.

10. **Add cover letter preview to the mobile approval flow** — approving an application without seeing the cover letter is a trust-breaking experience.

---

## Overall Assessment

The Aether platform design is **ambitious, well-conceived, and genuinely differentiated** in several areas: the Evidence Trace in Resume Studio, the 10-Dimensional Fit Score in Job Discovery, the Risk Signals, the Market Intelligence dashboard, the Email Center's AI classification and response system, and the Voice DNA authenticity checks. These features would provide real competitive advantage.

However, the design suffers from **inconsistency debt** that would be catastrophic in production. The navigation schema split, the data contradictions across screens, and the profile mismatches suggest the screens were designed in two separate batches without a shared design system or data model. The platform also lacks critical safety rails for its most powerful features — auto-apply, auto-reply, and bulk actions could cause real harm to a job seeker's reputation if triggered incorrectly.

The strongest recommendation is to **freeze feature development and fix the foundation**: standardize navigation, create a single data model, reconcile all numbers, and add confirmation dialogs for every irreversible action. Then proceed with the missing flows (onboarding, error recovery, offer acceptance) before adding any new features.
