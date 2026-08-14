/**
 * U-STORY-3a — the CROSS-WORKFLOW LINKAGE TABLE.
 *
 * THE PROBLEM IT ANSWERS (user mandate, 2026-08-14): "story extraction and
 * resume tailoring / cover letter agents are on separate workflows on the UI —
 * users must be able to KNOW THE LINKAGES VISUALLY to know what happened to
 * their job search and application and when."
 *
 * The orchestration maps are three separate panels because the API defines
 * three workflows. That is honest, and it is also why the single most important
 * fact about this product — the stories you bank are the evidence your resume
 * and cover letter are allowed to use — was invisible: the two ends of that
 * sentence render in different panels.
 *
 * TWO CLASSES OF EDGE, AND ONLY ONE OF THEM IS BUILDABLE TODAY
 * ------------------------------------------------------------------------
 * STRUCTURAL (this file). "Story Bank feeds Resume Tailoring." True of the
 * system as built, sourced from a read of the API, and drawable now. Every
 * entry below carries the hop-by-hop `file:line` provenance it was derived
 * from, copied verbatim out of the AGENT-GRAPH discovery artefact. Structural
 * edges are drawn as system WIRING: quiet, labelled, and never animated —
 * nothing is flowing along them, so nothing may move along them.
 *
 * CAUSAL, run-level. "This tailoring run consumed stories X and Y at 10:42."
 * That needs a parent run id the API does not record yet. It is NOT in this
 * slice: no faked traces, no dead UI built ahead of the data. The legend under
 * the toggle says so in the user's own words, and promises no date.
 *
 * WHY EACH ENTRY LOOKS LIKE THIS
 * ------------------------------------------------------------------------
 * A linkage is one CHAIN of graph hops from one catalog agent to another,
 * usually through the artefact they share (the Story Bank, the Resume, the
 * Jobs board). The chain is carried rather than flattened so a reviewer can
 * follow the same path the discovery walked, and so `drawableLinkages` can
 * check the chain actually joins up before anything is drawn.
 *
 * INCLUSION RULE (applied by hand, and re-checkable against the snapshot):
 *   - both endpoints are catalog agents that live on DIFFERENT workflow maps
 *     — a link between two neighbours on one map is already drawn by that
 *     map's own stage order, and re-drawing it would be noise;
 *   - every hop in the chain is `status: "live"` in the discovery. Wires the
 *     discovery found ABSENT are deliberately missing from this table: the
 *     "learning feedback re-tunes tailoring" edge everyone expects is one of
 *     them (`quality_policy.py:301` imports no learningFeedback), and drawing
 *     it would be exactly the fabrication this file exists to prevent;
 *   - the downstream agent's read is of the ARTEFACT KIND the upstream agent
 *     produces. Match scoring also writes to the Jobs table, but it writes fit
 *     SCORES onto rows discovery created — market trends counts postings, not
 *     scores, so `matchScoring -> marketTrends` is not a linkage and is not
 *     listed. The email agent, by contrast, creates postings "through the SAME
 *     upsert path as a board adapter" (its own graph note), so it is.
 *
 * THE LAW THIS FILE OPERATES UNDER. `orchestration-map-model.ts` forbids
 * fabricated topology: stage-to-stage order is the only relationship the
 * orchestration-map endpoint defines, so agent-to-agent arrows may never be
 * invented from it. Nothing here weakens that. These edges do not come from
 * that endpoint at all — they come from a read of the API source, they are
 * checked in with their citations, and `drawableLinkages` refuses to draw any
 * edge whose provenance does not hold up.
 */
import type { MapModel } from "./orchestration-map-model";

/** Live = the call exists on the default production codepath (graph rule). */
export type LinkageHopStatus = "live" | "partial" | "absent";

/** One hop of the chain, copied verbatim from the AGENT-GRAPH discovery. */
export interface LinkageHop {
  /** Graph node id, e.g. `agent.storyExtraction` / `store.StoryEntry`. */
  from: string;
  to: string;
  kind: "writes" | "reads" | "feeds" | "triggers" | "feeds_ui";
  /** How the hop happens, in the discovery's words. */
  mechanism: string;
  /** `apps/api/app/agents/story_extractor.py:96` — a line, never prose. */
  evidence: string;
  status: LinkageHopStatus;
}

export interface WorkflowLinkage {
  /** `${from}->${to}`, stable across renders and safe in a testid. */
  id: string;
  /** Catalog agent key (`agentKey` on the orchestration-map payload). */
  from: string;
  to: string;
  /** The artefact the two agents share, in the user's words; null if direct. */
  via: string | null;
  /** Short label drawn on the connection line. */
  label: string;
  /** One plain-language sentence: what this wire actually means. */
  meaning: string;
  /** The chain, in order. NEVER empty — see `drawableLinkages`. */
  provenance: LinkageHop[];
}

/**
 * Where the table came from, so the claim stays auditable from the UI code.
 *
 * The snapshot is a byte-identical copy of the discovery artefact, checked in
 * BESIDE THE TEST rather than left in the evidence tree — `uat/reports/
 * evidence/` is gitignored, and a provenance test whose ground truth is not in
 * the repository is a test that cannot run in CI.
 */
export const LINKAGE_SOURCE = {
  /** Repo-relative path to the checked-in graph the table is verified against. */
  snapshotPath: "apps/web/src/__tests__/agents/fixtures/AGENT-GRAPH.snapshot.json",
  derivedFrom: "uat/reports/evidence/market-perf/u-story/AGENT-GRAPH.json",
  generatedAt: "2026-08-14",
  nodes: 81,
  edges: 105,
} as const;

/** The toggle's label, and the one sentence under it. */
export const LINKAGE_TOGGLE_LABEL = "Show connections";
export const LINKAGE_LEGEND =
  "System wiring — how agents feed each other. Live run traces are coming and will be drawn only from real run records.";

/**
 * The wire's ink. Deliberately NOT `#FF6B35`: on this console coral means one
 * thing only — "live run, the only thing that moves" — and a structural wire is
 * the opposite of that. A fine dot pattern also keeps it distinct from the two
 * strokes the maps already spend: solid = implemented stage transition,
 * 5-5 dash = planned/roadmap.
 */
export const LINKAGE_STROKE = "rgba(255,255,255,0.30)";
export const LINKAGE_STROKE_DIM = "rgba(255,255,255,0.09)";
export const LINKAGE_STROKE_FOCUS = "rgba(255,255,255,0.62)";
export const LINKAGE_DASH = "1 4";

export const WORKFLOW_LINKAGES: readonly WorkflowLinkage[] = [
  {
    id: "storyExtraction->resumeTailoring",
    from: "storyExtraction",
    to: "resumeTailoring",
    via: "Story Bank",
    label: "banked stories → tailoring evidence",
    meaning: "Stories the extractor banks become the evidence resume tailoring is allowed to draw on.",
    provenance: [
      {
        from: "agent.storyExtraction",
        to: "store.StoryEntry",
        kind: "writes",
        mechanism:
          "StoryRepository.create keyed by achievementKey (upsert-in-place on re-run)",
        evidence:
          "apps/api/app/agents/story_extractor.py:96; dedup index apps/api/app/db.py:1159",
        status: "live",
      },
      {
        from: "store.StoryEntry",
        to: "svc.build_story_evidence",
        kind: "reads",
        mechanism:
          "StoryRepository.list_by_user -> flattened title+tags+STAR+metrics text",
        evidence:
          "apps/api/app/agents/tailor_agent.py:146-188",
        status: "live",
      },
      {
        from: "svc.build_story_evidence",
        to: "agent.resumeTailoring",
        kind: "feeds",
        mechanism:
          "story_evidence joined into evidence_extra and threaded to TailoringLoop.run",
        evidence:
          "apps/api/app/agents/tailor_agent.py:546,556,573",
        status: "live",
      },
    ],
  },
  {
    id: "storyExtraction->coverLetter",
    from: "storyExtraction",
    to: "coverLetter",
    via: "Story Bank",
    label: "banked stories → cover-letter evidence",
    meaning: "The same banked stories become the claim evidence the cover letter has to stay inside.",
    provenance: [
      {
        from: "agent.storyExtraction",
        to: "store.StoryEntry",
        kind: "writes",
        mechanism:
          "StoryRepository.create keyed by achievementKey (upsert-in-place on re-run)",
        evidence:
          "apps/api/app/agents/story_extractor.py:96; dedup index apps/api/app/db.py:1159",
        status: "live",
      },
      {
        from: "store.StoryEntry",
        to: "svc.build_story_evidence",
        kind: "reads",
        mechanism:
          "StoryRepository.list_by_user -> flattened title+tags+STAR+metrics text",
        evidence:
          "apps/api/app/agents/tailor_agent.py:146-188",
        status: "live",
      },
      {
        from: "svc.build_story_evidence",
        to: "agent.coverLetter",
        kind: "feeds",
        mechanism:
          "story_evidence -> claim_evidence corpus for unsupported_claim_tokens + FabricationGuard",
        evidence:
          "apps/api/app/agents/cover_letter_agent.py:1557,1558-1563",
        status: "live",
      },
    ],
  },
  {
    id: "storyExtraction->interviewPrep",
    from: "storyExtraction",
    to: "interviewPrep",
    via: "Story Bank",
    label: "banked stories → answer sketches",
    meaning: "Every interview answer sketch is grounded in one banked story and cites it.",
    provenance: [
      {
        from: "agent.storyExtraction",
        to: "store.StoryEntry",
        kind: "writes",
        mechanism:
          "StoryRepository.create keyed by achievementKey (upsert-in-place on re-run)",
        evidence:
          "apps/api/app/agents/story_extractor.py:96; dedup index apps/api/app/db.py:1159",
        status: "live",
      },
      {
        from: "store.StoryEntry",
        to: "agent.interviewPrep",
        kind: "reads",
        mechanism:
          "StoryRepository; each answer sketch grounded ONLY in the one cited story",
        evidence:
          "apps/api/app/agents/interview_prep_agent.py:67,223-226",
        status: "live",
      },
    ],
  },
  {
    id: "resumeTailoring->storyExtraction",
    from: "resumeTailoring",
    to: "storyExtraction",
    via: "Resume",
    label: "tailored resume → extraction input",
    meaning: "The resume tailoring writes is the document story extraction reads its bullets from.",
    provenance: [
      {
        from: "agent.resumeTailoring",
        to: "store.Resume",
        kind: "writes",
        mechanism:
          "new tailored Resume version (raw_text regenerated from tailored bullets); raises NoChangesApplied when net_changes==0 so no billed no-op version is created",
        evidence:
          "apps/api/app/agents/tailor_agent.py:611-620",
        status: "live",
      },
      {
        from: "store.Resume",
        to: "agent.storyExtraction",
        kind: "reads",
        mechanism:
          "resolve_user_resume_text -> extract_resume_bullets",
        evidence:
          "apps/api/app/agents/story_extractor.py:118,204-205",
        status: "live",
      },
    ],
  },
  {
    id: "submission->learningFeedback",
    from: "submission",
    to: "learningFeedback",
    via: "Applications",
    label: "applications → conversion measurement",
    meaning: "The applications submission records are what the learning loop measures conversion from.",
    provenance: [
      {
        from: "agent.submission",
        to: "store.Application",
        kind: "writes",
        mechanism:
          "reuses routers.jobs.submit_application_for_job VERBATIM — the same gate and write the Jobs board Apply button performs",
        evidence:
          "apps/api/app/agents/submission_agent.py:42,87",
        status: "live",
      },
      {
        from: "store.Application",
        to: "agent.learningFeedback",
        kind: "reads",
        mechanism:
          "raw SQL join: status x fitScore x resumeSourceJobId (tailored?) x hasLetter; read-only, never re-weights anything",
        evidence:
          "apps/api/app/agents/learning_feedback_agent.py:37,139-165",
        status: "live",
      },
    ],
  },
  {
    id: "emailAgent->sentimentAnalysis",
    from: "emailAgent",
    to: "sentimentAnalysis",
    via: "Email threads",
    label: "email threads → reply sentiment",
    meaning: "Threads the email agent files are where sentiment analysis reads employer replies.",
    provenance: [
      {
        from: "agent.emailAgent",
        to: "store.EmailThread",
        kind: "writes",
        mechanism:
          "triage mode: UPDATE EmailThread SET classification, aiScore (NULL when the model gave no real score)",
        evidence:
          "apps/api/app/agents/email_agent.py:365-382",
        status: "live",
      },
      {
        from: "store.EmailThread",
        to: "agent.sentimentAnalysis",
        kind: "reads",
        mechanism:
          "one synced thread per run; never mutates the Email Agent's triage labels",
        evidence:
          "apps/api/app/agents/sentiment_analysis_agent.py:51; catalog copy agents.py:343",
        status: "live",
      },
    ],
  },
  {
    id: "orchestration->jobDiscovery",
    from: "orchestration",
    to: "jobDiscovery",
    via: null,
    label: "pipeline run → discovery",
    meaning: "Running the whole pipeline dispatches job discovery as its first step.",
    provenance: [
      {
        from: "agent.orchestration",
        to: "agent.jobDiscovery",
        kind: "triggers",
        mechanism:
          "_pipeline_core sequential _dispatch",
        evidence:
          "apps/api/app/routers/agents.py:3380",
        status: "live",
      },
    ],
  },
  {
    id: "jobDiscovery->marketTrends",
    from: "jobDiscovery",
    to: "marketTrends",
    via: "Jobs",
    label: "discovered postings → market volumes",
    meaning: "Market trends are counted from the postings discovery banked on your board.",
    provenance: [
      {
        from: "agent.jobDiscovery",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "JobRepository.create upsert on (userId, sourceUrl) with dedupHash/contentHash/lastSeenAt",
        evidence:
          "apps/api/app/agents/scout_agent.py:23,98",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.marketTrends",
        kind: "reads",
        mechanism:
          "trends WITHIN this user's own discovery feed; no external market feed",
        evidence:
          "apps/api/app/agents/market_trends_agent.py:36",
        status: "live",
      },
    ],
  },
  {
    id: "jobDiscovery->salaryIntelligence",
    from: "jobDiscovery",
    to: "salaryIntelligence",
    via: "Jobs",
    label: "discovered postings → salary benchmarks",
    meaning: "Salary benchmarks are computed from the advertised pay on those same postings.",
    provenance: [
      {
        from: "agent.jobDiscovery",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "JobRepository.create upsert on (userId, sourceUrl) with dedupHash/contentHash/lastSeenAt",
        evidence:
          "apps/api/app/agents/scout_agent.py:23,98",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.salaryIntelligence",
        kind: "reads",
        mechanism:
          "aggregates only the pay the user's OWN postings disclosed",
        evidence:
          "apps/api/app/agents/salary_intelligence_agent.py:70",
        status: "live",
      },
    ],
  },
  {
    id: "jobDiscovery->companyResearch",
    from: "jobDiscovery",
    to: "companyResearch",
    via: "Jobs",
    label: "discovered postings → employer research",
    meaning: "Employer research starts from the company on the posting discovery banked.",
    provenance: [
      {
        from: "agent.jobDiscovery",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "JobRepository.create upsert on (userId, sourceUrl) with dedupHash/contentHash/lastSeenAt",
        evidence:
          "apps/api/app/agents/scout_agent.py:23,98",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.companyResearch",
        kind: "reads",
        mechanism:
          "synthesis over the user's own postings; optional guard-checked LLM narrative",
        evidence:
          "apps/api/app/agents/company_research_agent.py:53; narrative opt-in at apps/api/app/routers/agents.py:2020-2027",
        status: "live",
      },
    ],
  },
  {
    id: "jobDiscovery->interviewPrep",
    from: "jobDiscovery",
    to: "interviewPrep",
    via: "Jobs",
    label: "discovered postings → prep pack",
    meaning: "Interview prep reads the posting itself, as discovery banked it.",
    provenance: [
      {
        from: "agent.jobDiscovery",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "JobRepository.create upsert on (userId, sourceUrl) with dedupHash/contentHash/lastSeenAt",
        evidence:
          "apps/api/app/agents/scout_agent.py:23,98",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.interviewPrep",
        kind: "reads",
        mechanism:
          "questions predicted from the real posting + requirements",
        evidence:
          "apps/api/app/agents/interview_prep_agent.py:66",
        status: "live",
      },
    ],
  },
  {
    id: "emailAgent->marketTrends",
    from: "emailAgent",
    to: "marketTrends",
    via: "Jobs",
    label: "job-alert postings → market volumes",
    meaning: "Postings parsed out of job-alert emails join the same board rows market trends counts.",
    provenance: [
      {
        from: "agent.emailAgent",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "job_alerts mode: detect_alert_platform -> parse_job_alert -> JobRepository.create(posting.to_job_raw()) through the SAME upsert path as a board adapter; counts jobsCreated vs jobsUpdated from wasInserted",
        evidence:
          "apps/api/app/agents/email_agent.py:410-420,505-518",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.marketTrends",
        kind: "reads",
        mechanism:
          "trends WITHIN this user's own discovery feed; no external market feed",
        evidence:
          "apps/api/app/agents/market_trends_agent.py:36",
        status: "live",
      },
    ],
  },
  {
    id: "emailAgent->salaryIntelligence",
    from: "emailAgent",
    to: "salaryIntelligence",
    via: "Jobs",
    label: "job-alert postings → salary benchmarks",
    meaning: "Salaries advertised in job-alert postings are benchmarked with every other posting.",
    provenance: [
      {
        from: "agent.emailAgent",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "job_alerts mode: detect_alert_platform -> parse_job_alert -> JobRepository.create(posting.to_job_raw()) through the SAME upsert path as a board adapter; counts jobsCreated vs jobsUpdated from wasInserted",
        evidence:
          "apps/api/app/agents/email_agent.py:410-420,505-518",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.salaryIntelligence",
        kind: "reads",
        mechanism:
          "aggregates only the pay the user's OWN postings disclosed",
        evidence:
          "apps/api/app/agents/salary_intelligence_agent.py:70",
        status: "live",
      },
    ],
  },
  {
    id: "emailAgent->companyResearch",
    from: "emailAgent",
    to: "companyResearch",
    via: "Jobs",
    label: "job-alert postings → employer research",
    meaning: "Employers named in job-alert postings are researched from the same job rows.",
    provenance: [
      {
        from: "agent.emailAgent",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "job_alerts mode: detect_alert_platform -> parse_job_alert -> JobRepository.create(posting.to_job_raw()) through the SAME upsert path as a board adapter; counts jobsCreated vs jobsUpdated from wasInserted",
        evidence:
          "apps/api/app/agents/email_agent.py:410-420,505-518",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.companyResearch",
        kind: "reads",
        mechanism:
          "synthesis over the user's own postings; optional guard-checked LLM narrative",
        evidence:
          "apps/api/app/agents/company_research_agent.py:53; narrative opt-in at apps/api/app/routers/agents.py:2020-2027",
        status: "live",
      },
    ],
  },
  {
    id: "emailAgent->interviewPrep",
    from: "emailAgent",
    to: "interviewPrep",
    via: "Jobs",
    label: "job-alert postings → prep pack",
    meaning: "Interview prep reads a job-alert posting exactly as it reads a discovered one.",
    provenance: [
      {
        from: "agent.emailAgent",
        to: "store.Job",
        kind: "writes",
        mechanism:
          "job_alerts mode: detect_alert_platform -> parse_job_alert -> JobRepository.create(posting.to_job_raw()) through the SAME upsert path as a board adapter; counts jobsCreated vs jobsUpdated from wasInserted",
        evidence:
          "apps/api/app/agents/email_agent.py:410-420,505-518",
        status: "live",
      },
      {
        from: "store.Job",
        to: "agent.interviewPrep",
        kind: "reads",
        mechanism:
          "questions predicted from the real posting + requirements",
        evidence:
          "apps/api/app/agents/interview_prep_agent.py:66",
        status: "live",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// The guard — structural at RUNTIME, not only in the test suite
// ---------------------------------------------------------------------------

/**
 * A citation is a real `apps/…/file.ext:line`, not a sentence. Prose in the
 * evidence field is the shape a fabricated edge takes, so it is rejected here
 * rather than merely frowned at in review.
 */
const CITATION = /(?:^|\s)apps\/[\w./-]+\.(?:py|ts|tsx|prisma):\d+/;

/**
 * Every linkage that may be DRAWN. The renderer calls this and never the raw
 * table, so an entry that loses its provenance — or is added without any —
 * silently stops being drawn instead of quietly becoming a claim.
 *
 * Four ways an entry fails, all of them ways a wire could be invented:
 *   1. no provenance at all;
 *   2. a hop that is not `live` (the discovery found it absent or gated);
 *   3. a hop whose citation is not a file:line;
 *   4. a chain that does not run, joined end to end, from `agent.<from>` to
 *      `agent.<to>` — i.e. the path does not actually reach the agent it
 *      claims to feed.
 */
export function drawableLinkages(
  links: readonly WorkflowLinkage[] = WORKFLOW_LINKAGES,
): WorkflowLinkage[] {
  return links.filter((link) => {
    const hops = link.provenance;
    if (!hops || hops.length === 0) return false;
    if (!hops.every((h) => h.status === "live" && CITATION.test(h.evidence))) return false;
    if (hops[0].from !== `agent.${link.from}`) return false;
    if (hops[hops.length - 1].to !== `agent.${link.to}`) return false;
    return hops.every((hop, i) => i === 0 || hops[i - 1].to === hop.from);
  });
}

// ---------------------------------------------------------------------------
// Placement — which workflow map each agent is actually on, per THIS payload
// ---------------------------------------------------------------------------

export interface LinkagePlacement {
  agentKey: string;
  /** The agent's display name as the API named it — never hardcoded here. */
  name: string;
  mapKey: string;
  mapName: string;
}

/**
 * Index the loaded maps by agent key.
 *
 * Placement is read from the payload every render and never baked into the
 * table, so if the backend moves an agent into a different workflow (or drops
 * it), this UI follows silently and correctly: a linkage whose two ends land on
 * ONE map simply stops being cross-map, and a linkage with a missing end stops
 * being drawn. Neither case can leave a stale wire on screen.
 */
export function placementIndex(models: readonly MapModel[]): Map<string, LinkagePlacement> {
  const index = new Map<string, LinkagePlacement>();
  models.forEach((model) => {
    model.stages.forEach((stage) => {
      stage.nodes.forEach((node) => {
        // First placement wins: an agent listed twice is one agent, and the
        // "unmapped" catch-all bucket must never displace a real workflow.
        if (index.has(node.agent.agentKey)) return;
        index.set(node.agent.agentKey, {
          agentKey: node.agent.agentKey,
          name: node.agent.name,
          mapKey: model.key,
          mapName: model.name,
        });
      });
    });
  });
  return index;
}

export interface CrossMapLink {
  link: WorkflowLinkage;
  from: LinkagePlacement;
  to: LinkagePlacement;
}

/** The drawable linkages whose two endpoints are on this payload's maps, and
 *  on DIFFERENT ones. Everything else is dropped, never approximated. */
export function crossMapLinks(
  models: readonly MapModel[],
  links: readonly WorkflowLinkage[] = WORKFLOW_LINKAGES,
): CrossMapLink[] {
  const index = placementIndex(models);
  const out: CrossMapLink[] = [];
  drawableLinkages(links).forEach((link) => {
    const from = index.get(link.from);
    const to = index.get(link.to);
    if (!from || !to) return;
    if (from.mapKey === to.mapKey) return;
    out.push({ link, from, to });
  });
  return out;
}

// ---------------------------------------------------------------------------
// Ports — the chip on the node's edge
// ---------------------------------------------------------------------------

export type PortDirection = "out" | "in";

export interface NodePort {
  link: WorkflowLinkage;
  direction: PortDirection;
  /** The node at the OTHER end, with the map it lives on. */
  counterpart: LinkagePlacement;
  /** "→ feeds Resume Tailoring Agent (Application Pipeline)". */
  label: string;
  /** The label plus the linkage's plain-language meaning — title + aria. */
  description: string;
}

export function portLabel(direction: PortDirection, counterpart: LinkagePlacement): string {
  return direction === "out"
    ? `→ feeds ${counterpart.name} (${counterpart.mapName})`
    : `← from ${counterpart.name} (${counterpart.mapName})`;
}

/**
 * The ports one node shows: outbound first (what it feeds), then inbound (what
 * feeds it), each group in table order so the same node always reads the same
 * way.
 */
export function portsFor(agentKey: string, links: readonly CrossMapLink[]): NodePort[] {
  const port = (entry: CrossMapLink, direction: PortDirection): NodePort => {
    const counterpart = direction === "out" ? entry.to : entry.from;
    const label = portLabel(direction, counterpart);
    return {
      link: entry.link,
      direction,
      counterpart,
      label,
      description: `${label} — ${entry.link.meaning}`,
    };
  };
  return [
    ...links.filter((l) => l.link.from === agentKey).map((l) => port(l, "out")),
    ...links.filter((l) => l.link.to === agentKey).map((l) => port(l, "in")),
  ];
}

// ---------------------------------------------------------------------------
// Neighbourhood — what lights up when a node is selected
// ---------------------------------------------------------------------------

export interface LinkageNeighborhood {
  /** The focused agents plus every cross-map counterpart, in or out. */
  keys: Set<string>;
  /** The linkage ids that touch the focus. */
  linkIds: Set<string>;
}

export function neighborhoodOf(
  focus: readonly string[],
  links: readonly CrossMapLink[],
): LinkageNeighborhood {
  const keys = new Set<string>(focus);
  const linkIds = new Set<string>();
  focus.forEach((key) => {
    links.forEach((entry) => {
      if (entry.link.from === key) {
        keys.add(entry.link.to);
        linkIds.add(entry.link.id);
      } else if (entry.link.to === key) {
        keys.add(entry.link.from);
        linkIds.add(entry.link.id);
      }
    });
  });
  return { keys, linkIds };
}

// ---------------------------------------------------------------------------
// Geometry — pure, so the drawn wire is testable without a browser
// ---------------------------------------------------------------------------

/** A measured node box in the overlay's own coordinate space. */
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The horizontal band a node's map scroller actually shows. A node scrolled
 * past the fold still exists, so its wire is drawn to the fold rather than
 * flying across the panel that is in the way — the endpoint is CLAMPED, never
 * moved to a position the node does not occupy.
 */
export interface Clip {
  left: number;
  right: number;
}

export interface LinkageLine {
  id: string;
  /** Agent keys, so a renderer can key highlight state off the line. */
  from: string;
  to: string;
  label: string;
  /** Full sentence for the title/accessible description. */
  description: string;
  path: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  labelX: number;
  labelY: number;
  /**
   * Width of the plate the label needs, estimated from its length at the 9.5px
   * label size (SVG cannot size a box to text). Purely cosmetic: it decides how
   * wide the backing plate is drawn so a wire's name stays readable where it
   * crosses a card or another label — it asserts nothing about the data.
   */
  labelWidth: number;
  /**
   * ALWAYS "none". A structural wire describes how the system is put together,
   * not something happening now, so it can never carry motion. The type keeps
   * that a compile-time fact rather than a convention.
   */
  motion: "none";
  structural: true;
}

function clampX(x: number, clip: Clip | undefined): number {
  if (!clip) return x;
  return Math.min(Math.max(x, clip.left + 2), clip.right - 2);
}

/**
 * One wire between two measured node boxes.
 *
 * The three maps stack vertically, so the common case is a vertical run from
 * the lower edge of one card to the upper edge of another; two cards that
 * overlap vertically (same band of the page) are joined side to side instead.
 * A cubic keeps the wire clear of the cards it passes.
 */
export function linkageLine(
  entry: CrossMapLink,
  from: Box,
  to: Box,
  clips?: { from?: Clip; to?: Clip },
  /**
   * Where along the curve this wire's label sits, 0–1. Staggered by the caller
   * so two wires leaving the same node (story bank → tailoring AND → cover
   * letter) do not print their labels on top of each other — measured on the
   * first capture, where they overlapped into an unreadable smear.
   */
  labelT = 0.5,
): LinkageLine {
  const fromCx = clampX(from.x + from.w / 2, clips?.from);
  const toCx = clampX(to.x + to.w / 2, clips?.to);
  let x1 = fromCx;
  let y1 = from.y + from.h;
  let x2 = toCx;
  let y2 = to.y;
  let c1x = x1;
  let c1y = y1;
  let c2x = x2;
  let c2y = y2;

  if (to.y >= from.y + from.h) {
    // Target sits below: leave the bottom edge, arrive at the top edge.
    const dy = Math.max(24, (y2 - y1) * 0.45);
    c1y = y1 + dy;
    c2y = y2 - dy;
  } else if (from.y >= to.y + to.h) {
    // Target sits above: leave the top edge, arrive at the bottom edge.
    y1 = from.y;
    y2 = to.y + to.h;
    const dy = Math.max(24, (y1 - y2) * 0.45);
    c1y = y1 - dy;
    c2y = y2 + dy;
  } else {
    // Side by side — join the facing edges horizontally.
    const leftFirst = from.x <= to.x;
    x1 = clampX(leftFirst ? from.x + from.w : from.x, clips?.from);
    x2 = clampX(leftFirst ? to.x : to.x + to.w, clips?.to);
    y1 = from.y + from.h / 2;
    y2 = to.y + to.h / 2;
    const dx = Math.max(24, Math.abs(x2 - x1) * 0.45) * (leftFirst ? 1 : -1);
    c1x = x1 + dx;
    c1y = y1;
    c2x = x2 - dx;
    c2y = y2;
  }

  const path = `M ${round(x1)} ${round(y1)} C ${round(c1x)} ${round(c1y)}, ${round(c2x)} ${round(c2y)}, ${round(x2)} ${round(y2)}`;
  return {
    id: entry.link.id,
    from: entry.link.from,
    to: entry.link.to,
    label: entry.link.label,
    description: `${entry.from.name} (${entry.from.mapName}) → ${entry.to.name} (${entry.to.mapName}) — ${entry.link.meaning}`,
    path,
    x1: round(x1),
    y1: round(y1),
    x2: round(x2),
    y2: round(y2),
    // A point ON the cubic, so the label never floats off the line it names.
    labelX: round(cubicAt(x1, c1x, c2x, x2, labelT)),
    labelY: round(cubicAt(y1, c1y, c2y, y2, labelT)),
    labelWidth: Math.round(entry.link.label.length * 4.9 + 12),
    motion: "none",
    structural: true,
  };
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/** One coordinate of a cubic Bézier at parameter `t`. */
function cubicAt(p0: number, c1: number, c2: number, p3: number, t: number): number {
  const u = 1 - t;
  return u * u * u * p0 + 3 * u * u * t * c1 + 3 * u * t * t * c2 + t * t * t * p3;
}

/**
 * Candidate positions along a wire for its label, best first (the middle of the
 * run), then progressively further out. `buildLinkageLines` walks these and
 * takes the first that lands on NOTHING — no node card, no label already
 * placed. Measured need, not taste: at rest the first capture printed labels
 * across node titles and over each other.
 */
const LABEL_STOPS = [0.5, 0.38, 0.62, 0.28, 0.72, 0.2, 0.8, 0.44, 0.56];

/** A rectangle a label must not be printed on top of. */
export interface LinkageRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The plate a label occupies, in the same coordinates as the node boxes. */
function labelRect(line: LinkageLine): LinkageRect {
  return { x: line.labelX - line.labelWidth / 2, y: line.labelY - 15, w: line.labelWidth, h: 14 };
}

function overlaps(a: LinkageRect, b: LinkageRect, pad = 2): boolean {
  return (
    a.x - pad < b.x + b.w &&
    a.x + a.w + pad > b.x &&
    a.y - pad < b.y + b.h &&
    a.y + a.h + pad > b.y
  );
}

/**
 * Every wire that can be drawn from what has actually been MEASURED. A linkage
 * with an unmeasured end (off-screen tab, SSR, a node the payload dropped) is
 * skipped — never drawn to a guessed coordinate.
 */
export function buildLinkageLines(
  links: readonly CrossMapLink[],
  boxes: Readonly<Record<string, Box>>,
  clips: Readonly<Record<string, Clip>> = {},
  /**
   * Everything else on the page a label must stay off — map headings, stage
   * labels, the ports under the cards, the honesty footnotes. The node cards
   * are added automatically; this is the rest of the type.
   */
  keepOut: readonly LinkageRect[] = [],
): LinkageLine[] {
  const out: LinkageLine[] = [];
  const occupied: LinkageRect[] = [
    ...Object.values(boxes).map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.h })),
    ...keepOut,
  ];
  links.forEach((entry) => {
    const from = boxes[entry.link.from];
    const to = boxes[entry.link.to];
    if (!from || !to) return;
    const clipPair = { from: clips[entry.link.from], to: clips[entry.link.to] };
    const candidates = LABEL_STOPS.map((t) => linkageLine(entry, from, to, clipPair, t));
    const clear = candidates.find((c) => !occupied.some((r) => overlaps(labelRect(c), r)));
    // Nowhere on this wire is clear (a short hop between crowded columns): the
    // wire is still drawn at its natural midpoint — a label sitting on a busy
    // patch is a legibility cost, never a wrong statement.
    const chosen = clear ?? candidates[0];
    occupied.push(labelRect(chosen));
    out.push(chosen);
  });
  return out;
}

/**
 * The wiring stated in words — the accessible equivalent of the overlay, and
 * the thing a screen reader gets instead of curves it cannot see.
 */
export function linkageSentences(links: readonly CrossMapLink[]): string[] {
  return links.map(
    (entry) =>
      `${entry.from.name} (${entry.from.mapName}) feeds ${entry.to.name} (${entry.to.mapName})` +
      `${entry.link.via ? ` via ${entry.link.via}` : ""}. ${entry.link.meaning}`,
  );
}
