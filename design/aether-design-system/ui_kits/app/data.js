/* Fixture data for the command-center kit. Shapes mirror the real API payloads
   (jobs, agent runs, approvals, funnel, agents); values are illustrative. */
window.AE_DATA = {
  nav: [
    { group: "Work", items: [
      { label: "Dashboard", href: "dashboard", icon: "fa-solid fa-gauge-high" },
      { label: "Jobs", href: "jobs", icon: "fa-solid fa-magnifying-glass", count: 128 }
    ]},
    { group: "Studio", items: [
      { label: "Resume Studio", href: "resume", icon: "fa-solid fa-file-lines" },
      { label: "Cover Letter Studio", href: "cover-letters", icon: "fa-solid fa-envelope-open-text" },
      { label: "Story Bank", href: "stories", icon: "fa-solid fa-book-bookmark" }
    ]},
    { group: "Pipeline", items: [
      { label: "Applications", href: "applications", icon: "fa-solid fa-paper-plane", count: 42 },
      { label: "Interview Center", href: "interviews", icon: "fa-solid fa-microphone-lines" },
      { label: "Networking", href: "networking", icon: "fa-solid fa-handshake" },
      { label: "Email Center", href: "email", icon: "fa-solid fa-envelope" }
    ]},
    { group: "System", items: [
      { label: "Agents", href: "agents", icon: "fa-solid fa-robot", count: 3, live: true },
      { label: "Analytics", href: "analytics", icon: "fa-solid fa-chart-line" },
      { label: "Offers", href: "offers", icon: "fa-solid fa-scale-balanced" }
    ]},
    { group: "Account", items: [
      { label: "Settings", href: "settings", icon: "fa-solid fa-gear" }
    ]}
  ],
  stats: [
    { label: "Active applications", value: "42", delta: 2, note: "+3 this week", tip: "Applications you've submitted to an employer — every status past draft (screening, interview, offer, or rejected)." },
    { label: "Interview rate", value: "18", unit: "%", note: "7 of 39 applied", tip: "Share of your applications that progressed to at least one interview (Application → Interview %)." },
    { label: "Offers", value: "2", delta: 1, note: "2 pending decision", tip: "Applications where an employer has extended a formal offer." },
    { label: "AI confidence", value: "87", unit: "%", note: "avg match quality", tip: "Average ATS/AI fit score across all scored jobs — a 0–100 estimate of resume-to-role match quality." }
  ],
  runs: [
    { agent: "Scout", icon: "fa-solid fa-satellite-dish", text: "discovered", highlight: "14 new roles", meta: "4 min ago · 128 rows scanned", stage: "Discovered", tone: "ok", live: true },
    { agent: "Tailor", icon: "fa-solid fa-pen-nib", text: "rewrote 6 bullets for", highlight: "Senior Data Analyst · Telstra", meta: "12 min ago · ATS 91", stage: "Tailored", tone: "ok" },
    { agent: "Scribe", icon: "fa-solid fa-envelope-open-text", text: "drafted a cover letter for", highlight: "Analytics Lead · Coles Group", meta: "26 min ago · awaiting approval", stage: "Waiting", tone: "warn", approve: true },
    { agent: "Courier", icon: "fa-solid fa-paper-plane", text: "submitted an application to", highlight: "REA Group", meta: "1 h ago · confirmation captured", stage: "Submitted", tone: "ok" },
    { agent: "Scribe", icon: "fa-solid fa-envelope-open-text", text: "returned no draft for", highlight: "Data Governance Lead", meta: "2 h ago · nothing was sent", stage: "Waiting", tone: "degraded" },
    { agent: "Scout", icon: "fa-solid fa-satellite-dish", text: "scanned", highlight: "Seek · LinkedIn · company boards", meta: "3 h ago · 9 sources", stage: "Discovered", tone: "ok" }
  ],
  opportunities: [
    { org: "Telstra", role: "Senior Data Analyst", where: "Melbourne · Hybrid", pay: "AU$140k – 165k", fit: 94 },
    { org: "Coles Group", role: "Analytics Lead", where: "Hawthorn East · Hybrid", pay: "AU$155k – 175k", fit: 88 },
    { org: "REA Group", role: "Product Data Manager", where: "Richmond · Onsite", pay: "AU$150k – 170k", fit: 81 }
  ],
  approvals: [
    { title: "Send cover letter", sub: "Analytics Lead · Coles Group", when: "requested 26 min ago · waiting on you" },
    { title: "Submit application", sub: "Product Data Manager · REA Group", when: "requested 48 min ago · waiting on you" },
    { title: "Send email", sub: "Follow-up · Nadia Haque, Telstra", when: "requested 2 h ago · waiting on you" }
  ],
  ticker: [
    { t: "09:41:02", m: "jobs · 14 rows added by Scout" },
    { t: "09:38:55", m: "agent_runs · tailor completed in 41s" },
    { t: "09:31:20", m: "approvals · 1 request created" },
    { t: "09:22:07", m: "applications · REA Group moved to screening" },
    { t: "09:04:44", m: "jobs · watermark advanced" }
  ],
  funnel: [
    { stage: "Discovered", n: 128 },
    { stage: "Scored", n: 96 },
    { stage: "Tailored", n: 61 },
    { stage: "Applied", n: 39 },
    { stage: "Screening", n: 11 },
    { stage: "Interview", n: 7 },
    { stage: "Offer", n: 2 }
  ],
  jobs: [
    { id: "j1", org: "Telstra", role: "Senior Data Analyst", where: "Melbourne · Hybrid", pay: "AU$140k – 165k", fit: 94, ats: 91, source: "Seek", age: "2 h", saved: true,
      why: ["8 of 9 must-have skills matched", "Your Snowflake + dbt evidence maps to their stack", "Salary band clears your floor by AU$12k"],
      blurb: "Own the analytics layer for Telstra's consumer growth squad — modelling, experimentation and executive reporting across a 40M-event/day pipeline." },
    { id: "j2", org: "Coles Group", role: "Analytics Lead", where: "Hawthorn East · Hybrid", pay: "AU$155k – 175k", fit: 88, ats: 84, source: "LinkedIn", age: "5 h",
      why: ["Leadership scope matches your last two roles", "Retail media experience is a stated nice-to-have", "One must-have missing: Databricks"],
      blurb: "Lead a team of five analysts across supply-chain and loyalty, reporting to the Head of Data." },
    { id: "j3", org: "REA Group", role: "Product Data Manager", where: "Richmond · Onsite", pay: "AU$150k – 170k", fit: 81, ats: 79, source: "Company board", age: "1 d",
      why: ["Product analytics core matched", "Onsite five days is outside your stated preference"],
      blurb: "Partner with product on funnel instrumentation, experiment design and the metric layer for realestate.com.au." },
    { id: "j4", org: "NAB", role: "Data Governance Lead", where: "Docklands · Hybrid", pay: "AU$145k – 160k", fit: null, ats: null, source: "Seek", age: "1 d",
      why: [], blurb: "Governance uplift across the retail bank's data domains." },
    { id: "j5", org: "Culture Amp", role: "Staff Analytics Engineer", where: "Remote · AU", pay: "AU$160k – 185k", fit: 76, ats: 74, source: "LinkedIn", age: "2 d",
      why: ["Analytics engineering stack matched", "Two must-haves missing: Looker, Terraform"],
      blurb: "Own the semantic layer and the dbt project for a 400-person product org." }
  ],
  resumeVersions: [
    { id: "v3", name: "Telstra · Senior Data Analyst", ats: 91, when: "12 min ago", current: true },
    { id: "v2", name: "Coles · Analytics Lead", ats: 84, when: "yesterday" },
    { id: "v1", name: "Master resume", ats: 72, when: "3 Aug", master: true }
  ],
  changes: [
    { was: "Responsible for reporting and dashboards for the growth team.",
      now: "Rebuilt the growth reporting layer in dbt, cutting dashboard refresh from 40 min to 90 s for 120 weekly users.",
      why: "Story Bank · \u201cGrowth reporting rebuild\u201d — metrics 40 min → 90 s, 120 users", tone: "ok" },
    { was: "Worked with stakeholders on experimentation.",
      now: "Ran 34 A/B tests with the consumer squad; 9 shipped, lifting activation 6.2%.",
      why: "Story Bank · \u201cExperimentation program\u201d — 34 tests, 6.2% lift", tone: "ok" },
    { was: "Managed data quality processes.",
      now: "Introduced contract tests across 61 dbt models, holding freshness SLAs above 99%.",
      why: "Evidence thin — figure taken from your 2025 review, not a Story Bank entry", tone: "warn" }
  ],
  keywords: [
    { k: "dbt", n: 4, ok: true }, { k: "Snowflake", n: 3, ok: true }, { k: "experimentation", n: 2, ok: true },
    { k: "stakeholder management", n: 2, ok: true }, { k: "Databricks", n: 0, ok: false }, { k: "Looker", n: 0, ok: false }
  ],
  agents: [
    { name: "Scout", role: "Discovery", icon: "fa-solid fa-satellite-dish", model: "claude-sonnet-4-5", status: "ok", statusLabel: "Running", last: "4 min ago", runs: 214, note: "Reads 9 sources on a 6-hour cadence." },
    { name: "Analyst", role: "Scoring", icon: "fa-solid fa-brain", model: "claude-sonnet-4-5", status: "ok", statusLabel: "Running", last: "6 min ago", runs: 198, note: "Scores fit and ATS against your resume." },
    { name: "Tailor", role: "Resume", icon: "fa-solid fa-pen-nib", model: "claude-opus-4-1", status: "ok", statusLabel: "Running", last: "12 min ago", runs: 61, note: "Rewrites bullets from Story Bank evidence only." },
    { name: "Scribe", role: "Cover letters", icon: "fa-solid fa-envelope-open-text", model: "claude-opus-4-1", status: "degraded", statusLabel: "Produced nothing", last: "2 h ago", runs: 44, note: "Last run returned no draft. Nothing was sent." },
    { name: "Courier", role: "Submission", icon: "fa-solid fa-paper-plane", model: "claude-haiku-4-5", status: "warn", statusLabel: "Awaiting approval", last: "26 min ago", runs: 39, note: "Holds every outbound action for your approval." },
    { name: "Envoy", role: "Outreach", icon: "fa-solid fa-handshake", model: "claude-haiku-4-5", status: "neutral", statusLabel: "Idle", last: "no runs yet", runs: 0, note: "Not configured — connect a mailbox to enable." }
  ]
};
