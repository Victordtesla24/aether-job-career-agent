"use client";

/**
 * Job Discovery — wireframe `design/screens/job-discovery.html` (jd01–jd49).
 *
 * Live wiring (no mock data):
 *   GET  /jobs                     ranked list (market/source/remote/match filters)
 *   GET  /jobs/{id}/insights       ATS-derived match analysis, 10-dim fit, risk signals
 *   POST /jobs/{id}/save           toggle bookmark (persists)
 *   POST /jobs/{id}/apply          create Application + advance job → applied
 *   POST /agents/scout/run + /agents/fit-scorer/run   discovery/sync
 *
 * Market tabs (Australia / International / Saved) partition the live list by
 * derived location; the source bar, filters, list, detail panel, two-step apply
 * flow and submit-confirmation gate all reflect real data.
 *
 * `?demo=empty` forces the saved-jobs empty state.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiBaseUrl, apiRequest, getToken } from "../../../lib/api/client";
import { resolveRun } from "../../../lib/api/agents";
import { fetchMe } from "../../../lib/api/admin";
import {
  deriveSearchTarget,
  missingTargetLabel,
  type DiscoveryProfile,
  type EnteredTarget,
} from "../../../lib/discovery/search-target";
import { fetchScoutSources, fetchSourceAvailability } from "../../../lib/api/jobs";
import type { Job, ScoutSourceStatus, SourceAvailability } from "../../../lib/api/jobs";
import type { TailorRunResult } from "../../../lib/api/resumes";
import MetricTooltip from "../../../components/MetricTooltip";
import { sourceStatusView } from "../../../components/dashboard/sourceStatus";

// ---------------------------------------------------------------------------
// Types (insights payload from GET /jobs/{id}/insights)
// ---------------------------------------------------------------------------
interface Dimension {
  label: string;
  score: number;
  /** GMV4-ats-002: true when this dimension is wholly or partly built from
   *  the semantic-similarity component AND that component was not genuinely
   *  measured (`semanticPath` not in "local"/"hf_api") — a placeholder, not
   *  a real number. Absent/false on dimensions that never touch `semantic`. */
  degraded?: boolean;
}
interface RiskSignal {
  label: string;
  severity: "high" | "medium";
}
interface Insights {
  jobId: string;
  scored: boolean;
  overall: number;
  keywordMatch: number;
  semantic: number;
  /** GMV4-ats-002: which path produced `semantic` — "local"/"hf_api"
   *  (genuine) or "degraded"/"untracked"/unknown (neutral placeholder). */
  semanticPath?: string | null;
  /** Unambiguous, client-branchable twin of semanticPath — true iff
   *  `semantic` (and everything blended from it below) is a placeholder. */
  semanticDegraded?: boolean;
  /** R-04: false when the ATS ENGINE produced no score at all for this
   *  (résumé, posting) pair — `scored` can still be true there, because the
   *  router falls back to copying `Job.fitScore` into every subscore. A copied
   *  fit score is not a measured keyword match, so nothing résumé-derived on
   *  this payload may be presented as one. */
  atsMeasured?: boolean;
  experience: number;
  skillsMatched: number;
  skillsTotal: number;
  matchedSkills: string[];
  missingSkills: string[];
  skillGap: string | null;
  narrative: string;
  dimensions: Dimension[];
  riskSignals: RiskSignal[];
  isAustralia: boolean;
}

type Market = "au" | "intl" | "saved";

const SOURCE_FILTERS = [
  "all",
  "greenhouse",
  "lever",
  "remotive",
  "remoteok",
  "seek",
  "linkedin",
  "indeed",
] as const;
type SourceFilter = (typeof SOURCE_FILTERS)[number];

/** Minimum-salary bands (in thousands, "0" = no filter) — MV-job-discovery-004. */
const SALARY_FILTERS = ["0", "100", "150", "200"] as const;
type SalaryFilter = (typeof SALARY_FILTERS)[number];

/**
 * U-UI JOBS-HEIGHT-BLOWOUT-MOBILE / JOBS-SCREENSHOT-TIMEOUT-DESKTOP: with
 * every discovered job rendered into the DOM at once, a real account with
 * ~3,800 discovered jobs pushed `document.body.scrollHeight` to ~733,000px
 * (≈870x a 844px mobile viewport) — 2,921 unvirtualized card DOM nodes.
 * Render only the first `JOBS_RENDER_PAGE_SIZE` matches; "Load more" grows
 * the render window. Selection, counts, the detail panel and bulk actions
 * all keep operating against the full filtered `visible` list below — only
 * the list DOM is paginated.
 */
const JOBS_RENDER_PAGE_SIZE = 60;

/** Display label + badge for a job source (wireframe source bar naming). */
const SOURCE_LABEL: Record<string, string> = {
  seek: "Seek.com.au",
  linkedin: "LinkedIn AU",
  indeed: "Indeed AU",
  jora: "Jora",
  greenhouse: "Greenhouse",
  lever: "Lever",
  remotive: "Remotive",
  remoteok: "RemoteOK",
  workforce: "Workforce AU",
};

/** Badge initials for a job source key (wireframe jd24–jd28 source bar). */
function sourceBadge(source: string): string {
  return source.slice(0, 4).toUpperCase();
}

/** Location tokens classifying a posting as Australia-local (mirrors backend). */
const AU_TOKENS = [
  "australia", "nsw", "vic", "qld", "act", "tas", "sydney", "melbourne",
  "brisbane", "perth", "adelaide", "canberra", "hobart", "darwin",
  "gold coast", "newcastle", "wollongong",
];
function isAuLocation(loc?: string | null): boolean {
  if (!loc) return false;
  const l = ` ${loc.toLowerCase()} `;
  if (AU_TOKENS.some((t) => l.includes(t))) return true;
  return / au[ ,-]|[ ,-]au /.test(l);
}

function initials(company: string): string {
  return company
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

function salaryLabel(job: Job): string {
  const j = job as Job & { salaryMin?: number | null; salaryMax?: number | null; currency?: string | null };
  const fmt = (n: number) => `${j.currency === "USD" ? "US$" : "AU$"}${Math.round(n / 1000)}k`;
  if (j.salaryMin && j.salaryMax && Math.round(j.salaryMin / 1000) === Math.round(j.salaryMax / 1000))
    return fmt(j.salaryMax);
  if (j.salaryMin && j.salaryMax) return `${fmt(j.salaryMin)} – ${fmt(j.salaryMax)}`;
  if (j.salaryMax) return `up to ${fmt(j.salaryMax)}`;
  if (j.salaryMin) return `from ${fmt(j.salaryMin)}`;
  return "—";
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function ringColor(v: number): string {
  return v >= 85 ? "#34D399" : v >= 70 ? "#FBBF24" : "#F87171";
}

/**
 * BLOCKER-006 — the honest age line on a job card.
 *
 * The card used to render `timeAgo(job.createdAt)`: the date WE discovered the
 * row, unlabelled. A role advertised 187 days ago that the scout first saw 11
 * days ago therefore read "11d ago". That was survivable only while the feed
 * silently dropped everything older than 30 days; now that genuinely-live old
 * listings are shown (an ATS board only publishes open roles), presenting one
 * as freshly posted would be the dishonest half of the trade.
 *
 * So: state the posting age when the server knows it, and when it does not,
 * say which date is actually being shown rather than passing the discovery
 * date off as the posting date.
 */
function listingAgeLabel(job: Job): string {
  const days = job.postedAgeDays;
  if (typeof days === "number") {
    if (days < 1) return "Posted today";
    if (days === 1) return "Posted 1 day ago";
    return `Posted ${days} days ago`;
  }
  const discovered = timeAgo(job.createdAt);
  return discovered ? `Found ${discovered}` : "";
}

/**
 * QA #4 residual (ML-W25) — the board-sweep autopilot's cover-failure
 * backoff (RT-007/ML-W19) correctly stops retrying a job for up to 24h once
 * it accrues repeated letterless coverLetter runs, but until now nothing in
 * the product told the owner WHY autopilot had gone quiet on that job. The
 * backend now carries the honest expiry as `job.autopilotSuppressedUntil`
 * (null when not suppressed) — this renders it as a small, muted hint.
 */
function formatSuppressionUntil(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function autopilotSuppressionHint(job: Job): string | null {
  if (!job.autopilotSuppressedUntil) return null;
  const when = formatSuppressionUntil(job.autopilotSuppressedUntil);
  if (!when) return null;
  return `Autopilot paused for this job until ${when} — recent generation attempts couldn't produce a letter`;
}

// ---------------------------------------------------------------------------
// Presentational: circular match-score ring (SVG)
// ---------------------------------------------------------------------------
function MatchRing({ value, size = 44 }: { value: number | null | undefined; size?: number }) {
  const v = value == null ? 0 : Math.round(value);
  const r = 15.5;
  const circ = 2 * Math.PI * r;
  const off = circ * (1 - v / 100);
  const color = ringColor(v);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 36 36" className="-rotate-90" style={{ width: size, height: size }}>
        <circle cx="18" cy="18" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeDasharray={circ}
          strokeDashoffset={value == null ? circ : off}
          strokeLinecap="round"
        />
      </svg>
      <span className="mono absolute inset-0 flex items-center justify-center font-bold" style={{ fontSize: size / 4 }}>
        {value == null ? "—" : v}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Presentational: 10-dimension radar chart (SVG)
// ---------------------------------------------------------------------------
function RadarChart({ dims }: { dims: Dimension[] }) {
  const n = dims.length || 10;
  const cx = 100;
  const cy = 100;
  const maxR = 80;
  const pt = (i: number, radius: number) => {
    const a = (-90 + (360 / n) * i) * (Math.PI / 180);
    return [cx + radius * Math.cos(a), cy + radius * Math.sin(a)];
  };
  const ring = (frac: number) =>
    dims.map((_, i) => pt(i, maxR * frac).map((x) => x.toFixed(1)).join(",")).join(" ");
  // GMV4-ats-002: a degraded dimension's `score` is a placeholder, not a
  // measurement — floor it to the chart's minimum visible radius (same as an
  // honest 0) instead of plotting the placeholder number as a real point.
  const shape = dims
    .map((d, i) => pt(i, (maxR * Math.max(4, d.degraded ? 0 : d.score)) / 100).map((x) => x.toFixed(1)).join(","))
    .join(" ");
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" role="img" aria-label="10-dimensional fit radar">
      <g fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="1">
        <polygon points={ring(1)} />
        <polygon points={ring(0.66)} />
        <polygon points={ring(0.33)} />
      </g>
      <g stroke="rgba(255,255,255,0.06)" strokeWidth="1">
        {dims.map((_, i) => {
          const [x, y] = pt(i, maxR);
          return <line key={i} x1={cx} y1={cy} x2={x} y2={y} />;
        })}
      </g>
      <polygon points={shape} fill="rgba(255,107,53,0.18)" stroke="#FF6B35" strokeWidth="2" />
    </svg>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [market, setMarket] = useState<Market>("au");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [matchMin, setMatchMin] = useState(0);
  const [locationQuery, setLocationQuery] = useState("");
  const [roleQuery, setRoleQuery] = useState("");
  const [salaryMinFilter, setSalaryMinFilter] = useState<SalaryFilter>("0");
  const [sort, setSort] = useState<"fitScore" | "createdAt">("fitScore");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Honest-no-op notice (MV-adv-A-002) — a legitimate business outcome (every
  // proposed edit rejected by the anti-fabrication guard), rendered as an
  // informational notice, never the red error banner, matching Resume
  // Studio's identical no-op handling (MV-resume-studio-003).
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [demoEmpty, setDemoEmpty] = useState(false);

  // F-02 — what Sync Now searches for belongs to the SIGNED-IN user.
  //
  // This screen used to POST a literal
  // `{query: "delivery lead, product owner, program manager, business analyst",
  //   location: "Australia"}` for everyone, so a Senior Data Scientist got
  // 1,621 project-management postings written into their account. The target is
  // now derived from their own profile (GET /auth/me's `targetRole`/`location`,
  // the same columns Settings > Profile writes), and when the profile says
  // nothing we ASK rather than substitute — see `deriveSearchTarget`, which
  // owns no default query at all.
  //
  // The lookup is memoised in a ref rather than read straight off state so a
  // Sync Now pressed before the fetch settles waits for the real answer instead
  // of racing to "nothing configured".
  const [profile, setProfile] = useState<DiscoveryProfile | null>(null);
  const [profileSettled, setProfileSettled] = useState(false);
  const profileLoad = useRef<Promise<DiscoveryProfile | null> | null>(null);
  const loadProfile = useCallback((): Promise<DiscoveryProfile | null> => {
    profileLoad.current ??= fetchMe()
      .then((me) => ({ targetRole: me.targetRole, location: me.location }))
      // A failed lookup stays UNKNOWN (null). It must never degrade into a
      // guessed search — `deriveSearchTarget(null)` asks the user instead.
      .catch(() => null);
    return profileLoad.current;
  }, []);
  useEffect(() => {
    let cancelled = false;
    void loadProfile().then((p) => {
      if (cancelled) return;
      setProfile(p);
      setProfileSettled(true);
    });
    return () => {
      cancelled = true;
    };
  }, [loadProfile]);
  /** A role/location typed into the prompt below, for this session only. */
  const [enteredTarget, setEnteredTarget] = useState<EnteredTarget | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  const [askRole, setAskRole] = useState("");
  const [askLocation, setAskLocation] = useState("");
  const [askError, setAskError] = useState<string | null>(null);
  const searchTarget = useMemo(
    () => deriveSearchTarget(profile, enteredTarget),
    [profile, enteredTarget],
  );

  const [insights, setInsights] = useState<Record<string, Insights>>({});
  const insightsInFlight = useRef<Set<string>>(new Set());

  // Apply flow (per selected job) + submit gate.
  const [applyStep, setApplyStep] = useState<Record<string, "idle" | "tailoring" | "tailored">>({});
  const [tailorResults, setTailorResults] = useState<Record<string, TailorRunResult>>({});
  const [gateOpen, setGateOpen] = useState(false);
  const [gateJobId, setGateJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const gateTriggerRef = useRef<HTMLElement | null>(null);
  const gateConfirmRef = useRef<HTMLButtonElement | null>(null);
  // Success toast for a confirmed apply (GOV-010 / GMV2 §10.2) — the in-modal
  // "submitted" state auto-closes the gate after 1.6s, so a visible,
  // independent confirmation is needed for the new per-card entry point too.
  // Shared by every path that calls confirmSubmit (card, detail panel).
  const [applyToast, setApplyToast] = useState<string | null>(null);

  // Bulk-apply confirmation gate (MV-job-discovery-002) — the same
  // "irreversible action, explicit confirm" safety the single-job flow
  // enforces, applied to bulk apply too (both the list "Apply (N)" button and
  // the Saved view's "Apply to all").
  const [bulkGateOpen, setBulkGateOpen] = useState(false);
  const [bulkGateIds, setBulkGateIds] = useState<string[]>([]);
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkSubmitted, setBulkSubmitted] = useState(false);
  const bulkGateTriggerRef = useRef<HTMLElement | null>(null);
  const bulkGateConfirmRef = useRef<HTMLButtonElement | null>(null);

  // ?demo=empty → saved empty state.
  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "empty") {
      setDemoEmpty(true);
      setMarket("saved");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ sort });
      if (sourceFilter !== "all") params.set("source", sourceFilter);
      const data = await apiRequest<Job[]>(`/jobs?${params.toString()}`);
      setJobs(data);
      // RT-010: seed the apply step from the backend's tailored-résumé truth so
      // a job already tailored (this session, a prior session, or the agents)
      // opens at "Review & Apply" — never re-prompting to tailor or warning
      // "untailored". Client-set steps (a tailoring run in THIS session) win.
      setApplyStep((prev) => {
        const next = { ...prev };
        for (const job of data) {
          if (job.tailoredResumeId && next[job.id] == null) {
            next[job.id] = "tailored";
          }
        }
        return next;
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
      setJobs([]);
    }
  }, [sort, sourceFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  // BLOCKER-006 — never show an empty board without saying what happened to
  // the rows that ARE persisted. The active feed hides listings whose source
  // has stopped returning them, plus applied/archived ones; when that leaves
  // nothing, "Run Sync to let the Scout agent find matching roles" is wrong
  // (a production user with 52 persisted rows saw exactly that). Ask the
  // history view — the same endpoint, unfiltered — for the real count, and
  // only when the board is actually empty so the normal path costs nothing.
  const [historyCount, setHistoryCount] = useState<number | null>(null);
  useEffect(() => {
    if (jobs === null || jobs.length > 0) {
      setHistoryCount(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const all = await apiRequest<Job[]>("/jobs?include_stale=true");
        if (!cancelled) setHistoryCount(all.length);
      } catch {
        // Leave the count unknown rather than assert a number we don't have.
        if (!cancelled) setHistoryCount(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobs]);

  // Real-time board sync (HOTFIX realtime-board-refresh): agents (scout,
  // fit-scorer, tailor, board sweep) mutate Job rows server-side outside any
  // click the user makes, and applying a job removes it from the active feed
  // server-side too — without a periodic refetch the list only ever reflects
  // the single mutation this tab itself just made, going stale the moment a
  // background agent run (or another tab) advances a job. Poll every 20s
  // (fast enough to feel live, well under the API's per-request cost) and
  // pause while the tab is hidden so a backgrounded tab doesn't burn quota.
  // Mirrors the existing sidebar.tsx (30s) / topbar.tsx (60s) polling idiom.
  useEffect(() => {
    if (typeof document === "undefined") return;
    let cancelled = false;
    const tick = () => {
      if (document.visibilityState !== "visible" || cancelled) return;
      void load();
    };
    const timer = window.setInterval(tick, 20_000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [load]);

  // Lazily fetch insights for a job (cached; powers cards + detail panel).
  const fetchInsights = useCallback(async (jobId: string) => {
    if (insights[jobId] || insightsInFlight.current.has(jobId)) return;
    insightsInFlight.current.add(jobId);
    try {
      const data = await apiRequest<Insights>(`/jobs/${jobId}/insights`);
      setInsights((prev) => ({ ...prev, [jobId]: data }));
    } catch {
      /* insights are enhancement-only; the card still renders without them */
    } finally {
      insightsInFlight.current.delete(jobId);
    }
  }, [insights]);

  // AU/International partition + filters applied to the live list.
  const marketJobs = useMemo(() => {
    const all = demoEmpty ? [] : jobs ?? [];
    if (market === "saved") return all.filter((j) => j.saved);
    if (market === "au") return all.filter((j) => isAuLocation(j.location));
    return all.filter((j) => !isAuLocation(j.location));
  }, [jobs, market, demoEmpty]);

  const visible = useMemo(() => {
    return marketJobs.filter((j) => {
      if (remoteOnly && !j.remote) return false;
      if (matchMin > 0 && (j.fitScore == null || j.fitScore < matchMin)) return false;
      if (locationQuery && !(j.location ?? "").toLowerCase().includes(locationQuery.toLowerCase())) return false;
      if (roleQuery && !(j.title ?? "").toLowerCase().includes(roleQuery.toLowerCase())) return false;
      if (salaryMinFilter !== "0") {
        const threshold = Number(salaryMinFilter) * 1000;
        const j2 = j as Job & { salaryMin?: number | null; salaryMax?: number | null };
        const cap = j2.salaryMax ?? j2.salaryMin ?? null;
        if (cap == null || cap < threshold) return false;
      }
      return true;
    });
  }, [marketJobs, remoteOnly, matchMin, locationQuery, roleQuery, salaryMinFilter]);

  // U-UI JOBS-HEIGHT-BLOWOUT-MOBILE: only the first `renderLimit` matches of
  // `visible` are mounted as cards; `visible` itself (used for selection,
  // counts, "select all" and the detail panel below) stays the full filtered
  // list. Reset to the first page whenever the filter/sort criteria change —
  // not merely when `visible`'s contents shift (e.g. a background refresh
  // updating a fitScore in place shouldn't yank an already-loaded page back).
  const [renderLimit, setRenderLimit] = useState(JOBS_RENDER_PAGE_SIZE);
  useEffect(() => {
    setRenderLimit(JOBS_RENDER_PAGE_SIZE);
  }, [market, remoteOnly, matchMin, locationQuery, roleQuery, salaryMinFilter, sort, sourceFilter]);
  const renderedJobs = useMemo(
    () => visible.slice(0, renderLimit),
    [visible, renderLimit],
  );

  const counts = useMemo(() => {
    const all = jobs ?? [];
    return {
      au: all.filter((j) => isAuLocation(j.location)).length,
      intl: all.filter((j) => !isAuLocation(j.location)).length,
      saved: all.filter((j) => j.saved).length,
    };
  }, [jobs]);

  // Keep a valid selection within the visible list; prefetch its insights.
  useEffect(() => {
    if (market === "saved") return;
    setSelectedId((prev) => (visible.some((j) => j.id === prev) ? prev : visible[0]?.id ?? null));
  }, [visible, market]);

  useEffect(() => {
    visible.slice(0, 12).forEach((j) => void fetchInsights(j.id));
  }, [visible, fetchInsights]);

  // Always fetch insights for the selected job — selection isn't limited to
  // the prefetched first 12.
  useEffect(() => {
    if (selectedId) void fetchInsights(selectedId);
  }, [selectedId, fetchInsights]);

  const stats = useMemo(() => {
    const all = jobs ?? [];
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    const newToday = all.filter((j) => j.createdAt && new Date(j.createdAt).getTime() >= midnight.getTime()).length;
    const sources = new Set(all.map((j) => j.source)).size;
    // F-02 labelling. Every discovered row used to be counted as a "match"
    // ("1,621 matches across markets") even though nothing had been scored
    // against the user's résumé — the screen asserted a relevance the system
    // had not measured. A "match" claim needs a fit score behind it, so the
    // two populations are now counted separately, using the same
    // `fitScore != null` test the dashboard already treats as "scored"
    // (dashboard/page.tsx:194).
    const scored = all.filter((j) => j.fitScore != null).length;
    return { total: all.length, scored, unscored: all.length - scored, newToday, sources };
  }, [jobs]);

  // Source bar: real per-source counts from the loaded jobs, most jobs first.
  const sourceCards = useMemo(() => {
    const bySource = new Map<string, number>();
    for (const j of jobs ?? []) bySource.set(j.source, (bySource.get(j.source) ?? 0) + 1);
    return [...bySource.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([source, count]) => ({ source, count }));
  }, [jobs]);

  // "Last synced" from the scout agent's real last run.
  const [lastSync, setLastSync] = useState<string | null>(null);
  useEffect(() => {
    apiRequest<{ name: string; last_run?: string | null }[]>("/agents")
      .then((agents) => setLastSync(agents.find((a) => a.name === "scout")?.last_run ?? null))
      .catch(() => setLastSync(null));
  }, []);

  // Per-source sync status (GAP-SRC-003): honest ok/error/skipped per board,
  // independent of whether that source currently has any discovered jobs.
  const [scoutSources, setScoutSources] = useState<ScoutSourceStatus[] | null>(null);
  const loadSourceStatus = useCallback(async () => {
    try {
      const token = await getToken();
      const data = await fetchScoutSources({ token, baseUrl: apiBaseUrl() });
      setScoutSources(data);
    } catch {
      // Sync status is enhancement-only; the rest of the page still works.
      setScoutSources((prev) => prev ?? []);
    }
  }, []);
  useEffect(() => {
    void loadSourceStatus();
  }, [loadSourceStatus]);

  // Backend-derived source availability (ML-audit-seek-fe-hardcode-001): the
  // adapter registry (incl. the AETHER_ENABLE_SEEK gate) is the single
  // authority on which sources are live-filterable — never hardcoded here.
  // On fetch failure availability is UNKNOWN: options stay enabled rather
  // than showing a fabricated "(unavailable)" label; filtering a dead source
  // then surfaces the backend's honest 422.
  const [sourceAvailability, setSourceAvailability] = useState<Record<
    string,
    SourceAvailability
  > | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const rows = await fetchSourceAvailability({ token, baseUrl: apiBaseUrl() });
        if (!cancelled) {
          setSourceAvailability(Object.fromEntries(rows.map((r) => [r.source, r])));
        }
      } catch {
        if (!cancelled) setSourceAvailability(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  const isSourceUnavailable = useCallback(
    (source: string) => sourceAvailability?.[source]?.available === false,
    [sourceAvailability],
  );

  const selected = visible.find((j) => j.id === selectedId) ?? (market === "saved" ? undefined : visible[0]);
  const selectedInsights = selected ? insights[selected.id] : undefined;
  // GMV4-ats-002 round 3: WHITELIST — trust the semantic-derived dimensions
  // (Industry Match / Culture Fit / North Star Align) only when the backend
  // genuinely measured them; any other/missing `semanticPath` value reads as
  // not measured (fails closed, matching the same rule applied server-side).
  const insightsSemanticTrusted =
    selectedInsights?.semanticPath === "local" || selectedInsights?.semanticPath === "hf_api";
  // FAIL CLOSED, same rule as every other provenance read on this screen: only
  // an explicit `true` counts as measured.
  const insightsAtsMeasured = selectedInsights?.atsMeasured === true;
  const step = selected ? applyStep[selected.id] ?? "idle" : "idle";

  /** Run the real discovery pass for an already-resolved, user-owned target. */
  const runDiscoveryFor = async (query: string, location: string) => {
    setRunning(true);
    setError(null);
    try {
      await apiRequest("/agents/scout/run", { method: "POST", body: { query, location } });
      await apiRequest("/agents/fit-scorer/run", { method: "POST" });
      setInsights({});
      await Promise.all([load(), loadSourceStatus()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery run failed");
    } finally {
      setRunning(false);
    }
  };

  const runDiscovery = async () => {
    // Wait for the profile lookup if it is still in flight, so a fast click
    // gets the user's real target rather than a premature "nothing set".
    const current = profileSettled ? profile : await loadProfile();
    const target = deriveSearchTarget(current, enteredTarget);
    if (target.status !== "ready") {
      // Nothing of this user's own to search for. Ask — never borrow someone
      // else's query, and never report a run that did not happen.
      setAskRole(target.role);
      setAskLocation(target.location);
      setAskError(null);
      setAskOpen(true);
      setError(null);
      return;
    }
    await runDiscoveryFor(target.query, target.location);
  };

  /** Search exactly what the user typed into the prompt — nothing added. */
  const submitAskedTarget = async () => {
    const target = deriveSearchTarget(profile, { role: askRole, location: askLocation });
    if (target.status !== "ready") {
      setAskError(
        `Enter a ${missingTargetLabel(target.missing)} so the search describes the job you actually want.`,
      );
      return;
    }
    setEnteredTarget({ role: target.query, location: target.location });
    setAskError(null);
    setAskOpen(false);
    await runDiscoveryFor(target.query, target.location);
  };

  const toggleSave = async (jobId: string) => {
    try {
      const updated = await apiRequest<Job>(`/jobs/${jobId}/save`, { method: "POST" });
      setJobs((prev) => (prev ?? []).map((j) => (j.id === jobId ? updated : j)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update saved");
    }
  };

  const startTailoring = async (jobId: string) => {
    setApplyStep((p) => ({ ...p, [jobId]: "tailoring" }));
    setError(null);
    setNotice(null);
    try {
      const raw = await apiRequest<TailorRunResult>(
        "/agents/tailor/run",
        { method: "POST", body: { job_id: jobId } },
      );
      // Dual-shape (GAP-P7-ASYNC-001 §6): unwrap a 202 enqueue envelope by
      // polling; a legacy synchronous body passes through unchanged.
      const out = await resolveRun(raw);
      if (out.noChangesApplied) {
        // Honest no-op — the guards rejected every edit; nothing was created
        // or billed. Surface it as an informational notice (never the red
        // error banner, never a leaked exception-class name), matching
        // Resume Studio (MV-resume-studio-003 / MV-adv-A-002).
        setNotice(
          out.message ??
            "No changes could be applied — your résumé is unchanged and you were not charged.",
        );
        setApplyStep((p) => ({ ...p, [jobId]: "idle" }));
        return;
      }
      setTailorResults((p) => ({ ...p, [jobId]: out }));
      setApplyStep((p) => ({ ...p, [jobId]: "tailored" }));
      // §12.3: reflect the freshly-computed score on the card without a
      // manual reload. The tailor-run response itself carries the new score
      // (`conversionMetrics.tailoredATSScore` — apps/web/src/lib/api/resumes.ts:52),
      // so patch it straight into `jobs` state (never recomputed locally,
      // matching Resume Studio's discipline of using the API value verbatim
      // — apps/web/src/app/dashboard/resume/page.tsx:135). This drives both
      // the list-card and detail-panel MatchRings, since `selected` is
      // derived from `jobs`.
      if (out.conversionMetrics?.tailoredATSScore != null) {
        const freshScore = out.conversionMetrics.tailoredATSScore;
        setJobs((prev) => (prev ?? []).map((j) => (j.id === jobId ? { ...j, fitScore: freshScore } : j)));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tailoring failed");
      setApplyStep((p) => ({ ...p, [jobId]: "idle" }));
    }
  };
  const resetTailoring = (jobId: string) => setApplyStep((p) => ({ ...p, [jobId]: "idle" }));

  const openGate = (jobId: string, trigger: HTMLElement | null) => {
    gateTriggerRef.current = trigger;
    setGateJobId(jobId);
    setSubmitted(false);
    setGateOpen(true);
  };
  const closeGate = useCallback(() => {
    setGateOpen(false);
    setGateJobId(null);
    gateTriggerRef.current?.focus?.();
  }, []);

  const confirmSubmit = async () => {
    if (!gateJobId) return;
    setSubmitting(true);
    try {
      const res = await apiRequest<{ job: Job }>(`/jobs/${gateJobId}/apply`, { method: "POST" });
      setJobs((prev) => (prev ?? []).map((j) => (j.id === res.job.id ? res.job : j)));
      setSubmitted(true);
      // Independent success confirmation (GOV-010) — the in-modal
      // "submitted" state auto-closes shortly after, so the per-card entry
      // point (which never opened the detail panel) still leaves a visible
      // trace that the apply succeeded.
      setApplyToast(`Applied to ${res.job.company} — tracking in Applications.`);
      window.setTimeout(() => setApplyToast(null), 3500);
      window.setTimeout(closeGate, 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply failed");
      setGateOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const skipToNext = (jobId: string) => {
    const idx = visible.findIndex((j) => j.id === jobId);
    const next = visible[(idx + 1) % Math.max(1, visible.length)];
    if (next && next.id !== jobId) setSelectedId(next.id);
  };

  // Bulk selection over the visible list.
  const allSelected = visible.length > 0 && visible.every((j) => selectedIds.has(j.id));
  const toggleSelectAll = () =>
    setSelectedIds(allSelected ? new Set() : new Set(visible.map((j) => j.id)));
  const toggleSelect = (jobId: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });

  // Bulk apply (MV-job-discovery-002): opens the same kind of irreversible-
  // action confirmation gate the single-job flow enforces — no silent mass
  // apply. `requestBulkApply` only stages the ids and opens the gate;
  // `confirmBulkApply` performs the actual POSTs, and only after the user
  // explicitly confirms.
  const requestBulkApply = (ids: string[], trigger: HTMLElement | null) => {
    if (ids.length === 0) return;
    bulkGateTriggerRef.current = trigger;
    setBulkGateIds(ids);
    setBulkSubmitted(false);
    setBulkGateOpen(true);
  };
  const closeBulkGate = useCallback(() => {
    setBulkGateOpen(false);
    setBulkGateIds([]);
    bulkGateTriggerRef.current?.focus?.();
  }, []);

  const confirmBulkApply = async () => {
    const ids = bulkGateIds;
    if (ids.length === 0) return;
    setBulkSubmitting(true);
    setRunning(true);
    try {
      for (const id of ids) {
        const res = await apiRequest<{ job: Job }>(`/jobs/${id}/apply`, { method: "POST" });
        setJobs((prev) => (prev ?? []).map((j) => (j.id === res.job.id ? res.job : j)));
      }
      setSelectedIds(new Set());
      setBulkSubmitted(true);
      window.setTimeout(closeBulkGate, 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk apply failed");
      setBulkGateOpen(false);
    } finally {
      setBulkSubmitting(false);
      setRunning(false);
    }
  };

  // Modal a11y: focus the confirm button on open; trap focus; ESC closes.
  useEffect(() => {
    if (!gateOpen) return;
    gateConfirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeGate();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [gateOpen, closeGate]);

  useEffect(() => {
    if (!bulkGateOpen) return;
    bulkGateConfirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeBulkGate();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [bulkGateOpen, closeBulkGate]);

  const clearAll = () => {
    setSourceFilter("all");
    setRemoteOnly(false);
    setMatchMin(0);
    setLocationQuery("");
    setRoleQuery("");
    setSalaryMinFilter("0");
    setSort("fitScore");
  };

  const gateJob = gateJobId ? (jobs ?? []).find((j) => j.id === gateJobId) : undefined;
  // Honest resume-status for the gate copy (GOV-010): the per-card Apply
  // button can open this same gate WITHOUT the detail panel's tailoring step
  // having run, so the dialog must not always claim "tailored resume
  // attached" — it must reflect this job's real state, same as the bulk gate
  // already does for its "current, untailored" case.
  const gateJobTailored = gateJobId ? applyStep[gateJobId] === "tailored" : false;
  const bulkGateJobs = useMemo(
    () => (jobs ?? []).filter((j) => bulkGateIds.includes(j.id)),
    [jobs, bulkGateIds],
  );

  return (
    <div className="space-y-5">
      {/* Apply success toast (GOV-010 / GMV2 §10.2) */}
      {applyToast ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="jobs-toast"
          className="fixed right-6 top-20 z-50 rounded-xl border border-aether-green/40 bg-aether-green/15 px-5 py-3 text-sm font-medium text-aether-green shadow-lg backdrop-blur-md"
        >
          ✓ {applyToast}
        </div>
      ) : null}
      {/* Header + stats subtitle (jd03) */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Job Discovery</h1>
          <p className="mono text-xs text-aether-muted-dim" data-testid="jobs-stats">
            {stats.total} discovered · {stats.scored} scored against your résumé ·{" "}
            {stats.unscored} not yet scored · {stats.newToday} new today · {stats.sources} sources connected
          </p>
        </div>
        <button
          type="button"
          data-testid="run-discovery-btn"
          onClick={() => void runDiscovery()}
          disabled={running}
          className="flex items-center gap-2 rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
        >
          {running ? "Syncing…" : "Sync Now"}
        </button>
      </header>

      {/* F-02 — say plainly what Sync Now will search for, and where that came
          from. Rendered only once the profile lookup has settled, so the line
          never states a target before one is known. */}
      {profileSettled ? (
        <p className="text-xs text-aether-muted-dim" data-testid="discovery-search-target">
          {searchTarget.status === "ready" ? (
            <>
              Sync Now searches for{" "}
              <span className="font-semibold text-white">{searchTarget.query}</span> in{" "}
              <span className="font-semibold text-white">{searchTarget.location}</span>
              {searchTarget.source === "profile" ? (
                <>
                  {" "}
                  — from your profile.{" "}
                  <Link href="/dashboard/settings" className="underline hover:text-white">
                    Change it in Settings
                  </Link>
                </>
              ) : (
                <>
                  {" "}
                  — what you entered for this session.{" "}
                  <Link href="/dashboard/settings" className="underline hover:text-white">
                    Save it to your profile
                  </Link>
                </>
              )}
            </>
          ) : (
            <>
              No {missingTargetLabel(searchTarget.missing)} on your profile yet — Sync Now will
              ask what you are looking for rather than search for a role you did not choose.
            </>
          )}
        </p>
      ) : null}

      {/* F-02 — the honest empty-profile path. The product's promise is that it
          does not fabricate, so with nothing configured the screen asks the
          question instead of quietly running somebody else's search and
          labelling the results "matches". */}
      {askOpen ? (
        <section
          data-testid="discovery-target-prompt"
          aria-labelledby="discovery-target-prompt-heading"
          className="rounded-2xl border border-aether-coral/30 bg-aether-coral/5 p-5"
        >
          <h2 id="discovery-target-prompt-heading" className="text-sm font-semibold">
            What should we search for?
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-aether-muted">
            Your profile has no {missingTargetLabel(searchTarget.status === "needs-input" ? searchTarget.missing : ["role"])}{" "}
            set, so there is nothing here to search for yet. Tell us what you want and we
            will search for exactly that — we will not guess a target role on your behalf,
            because results we cannot justify are not results.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-aether-muted-dim">
              Target role
              <input
                type="text"
                data-testid="discovery-role-input"
                value={askRole}
                onChange={(e) => setAskRole(e.target.value)}
                placeholder="e.g. Senior Data Scientist"
                className="w-64 rounded-lg border border-white/15 bg-black/30 px-3 py-1.5 text-sm text-white placeholder:text-aether-muted-dim"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-aether-muted-dim">
              Location
              <input
                type="text"
                data-testid="discovery-location-input"
                value={askLocation}
                onChange={(e) => setAskLocation(e.target.value)}
                placeholder="e.g. Melbourne, Australia"
                className="w-64 rounded-lg border border-white/15 bg-black/30 px-3 py-1.5 text-sm text-white placeholder:text-aether-muted-dim"
              />
            </label>
            <button
              type="button"
              data-testid="discovery-target-submit"
              onClick={() => void submitAskedTarget()}
              disabled={running}
              className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
            >
              {running ? "Searching…" : "Search this"}
            </button>
            <button
              type="button"
              data-testid="discovery-target-cancel"
              onClick={() => {
                setAskOpen(false);
                setAskError(null);
              }}
              className="rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-aether-muted hover:text-white"
            >
              Cancel
            </button>
          </div>
          {askError ? (
            <p className="mt-2 text-xs text-red-300" data-testid="discovery-target-error">
              {askError}
            </p>
          ) : null}
          <p className="mt-2 text-[11px] text-aether-muted-dim">
            Prefer to set it once?{" "}
            <Link href="/dashboard/settings" className="underline hover:text-white">
              Add your target role in Settings
            </Link>{" "}
            and every future sync will use it.
          </p>
        </section>
      ) : null}

      {/* Market tabs (jd20/jd21/jd41) */}
      <div className="flex items-center gap-1 border-b border-white/10" role="tablist" aria-label="Market">
        {([
          { key: "au", label: "🇦🇺 Australia (Local)", count: counts.au },
          { key: "intl", label: "🌏 International", count: counts.intl },
          { key: "saved", label: "Saved", count: counts.saved },
        ] as const).map((t) => {
          const active = market === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              data-testid={`market-tab-${t.key}`}
              onClick={() => {
                setMarket(t.key);
                if (t.key !== "saved") setDemoEmpty(false);
              }}
              className={`flex items-center gap-2 rounded-t-lg border-b-2 px-4 py-2.5 text-sm transition ${
                active
                  ? "border-aether-coral font-semibold text-white"
                  : "border-transparent font-medium text-aether-muted hover:text-white"
              }`}
            >
              {t.label}
              <span
                className={`mono rounded-md px-1.5 py-0.5 text-[10px] ${
                  active ? "bg-aether-coral/15 text-aether-coral" : "bg-white/10 text-aether-muted-dim"
                }`}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Source integration bar (jd22–jd28) */}
      <section data-testid="source-bar" aria-label="Connected job boards">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Connected Job Boards — {market === "intl" ? "International" : "Australia"}
          </span>
          <span className="mono text-[11px] text-aether-muted-dim">
            {lastSync ? `Last synced: ${timeAgo(lastSync)}` : "Sync time unavailable"}
          </span>
        </div>
        <div
          className="flex items-stretch gap-3 overflow-x-auto pb-1"
          role="region"
          aria-label="Connected job board cards (scrollable)"
          tabIndex={0}
        >
          {sourceCards.map((s) => (
            <div key={s.source} className="glass-raised w-52 shrink-0 rounded-xl border border-white/10 p-3.5">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                    {sourceBadge(s.source)}
                  </span>
                  <span className="text-xs font-semibold">{SOURCE_LABEL[s.source] ?? s.source}</span>
                </div>
                <span className="h-2 w-2 rounded-full bg-aether-green" aria-hidden="true" />
              </div>
              <p className="mb-2.5 text-[11px] text-aether-green">
                {s.count} live {s.count === 1 ? "job" : "jobs"} discovered
              </p>
            </div>
          ))}
          <div className="flex w-52 shrink-0 flex-col items-center justify-center rounded-xl border border-dashed border-white/15 p-3.5 text-center">
            <p className="text-[11px] leading-relaxed text-aether-muted-dim">
              Counts reflect live discovered jobs per source — run <span className="text-white">Sync Now</span> to
              refresh from all connected boards
            </p>
          </div>
        </div>
      </section>

      {/* Per-source sync status (GAP-SRC-003) — ok/error/skipped per board,
          independent of whether that source has any discovered jobs. */}
      <section data-testid="source-status-panel" aria-label="Per-source sync status">
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
          Sync Status
        </span>
        {scoutSources === null ? (
          <div
            className="flex gap-2 overflow-x-auto pb-1"
            aria-busy="true"
            role="region"
            aria-label="Per-source sync status (loading)"
            tabIndex={0}
          >
            {[0, 1, 2].map((i) => (
              <div key={i} className="glass h-11 w-48 shrink-0 animate-pulse rounded-lg border border-white/10" />
            ))}
          </div>
        ) : scoutSources.length === 0 ? (
          <p className="text-[11px] text-aether-muted-dim">Sync status unavailable — run Sync Now to populate it.</p>
        ) : (
          <div className="flex flex-wrap items-stretch gap-2" data-testid="source-status-list">
            {sourceStatusView(scoutSources).map((s) => (
              <div
                key={s.source}
                data-testid="source-status-chip"
                className={`flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-[11px] ${
                  s.badge === "error"
                    ? "border-red-500/30 bg-red-500/10"
                    : s.badge === "ok"
                      ? "border-aether-green/20 bg-aether-green/[0.06]"
                      : "border-white/10 bg-white/5"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    s.badge === "error" ? "bg-red-400" : s.badge === "ok" ? "bg-aether-green" : "bg-aether-muted-dim"
                  }`}
                />
                <span className="shrink-0 font-semibold">{SOURCE_LABEL[s.source] ?? s.source}</span>
                <span
                  data-testid="source-status-badge"
                  className={s.badge === "error" ? "text-red-300" : s.badge === "ok" ? "text-aether-green" : "text-aether-muted-dim"}
                >
                  {s.badgeLabel}
                </span>
                <span className="shrink-0 text-aether-muted-dim">· {s.lastSyncLabel}</span>
                {s.errorText ? (
                  <span
                    data-testid="source-status-error"
                    title={s.errorText}
                    className="max-w-[220px] truncate text-red-300/90"
                  >
                    — {s.errorText}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Filters (jd04–jd08, jd29) */}
      <div className="flex flex-wrap items-center gap-2.5" data-testid="job-filter-bar">
        <input
          type="text"
          value={roleQuery}
          onChange={(e) => setRoleQuery(e.target.value)}
          placeholder="Role…"
          aria-label="Filter by role"
          data-testid="job-role-filter"
          className="glass w-32 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs placeholder:text-aether-muted-dim"
        />
        <select
          value={sourceFilter}
          aria-label="Filter by source"
          onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          data-testid="job-source-filter"
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs"
        >
          {SOURCE_FILTERS.map((s) => (
            <option
              key={s}
              value={s}
              disabled={isSourceUnavailable(s)}
              className="bg-black"
            >
              {s === "all" ? "All sources" : SOURCE_LABEL[s] ?? s}
              {isSourceUnavailable(s) ? " (unavailable)" : ""}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={locationQuery}
          onChange={(e) => setLocationQuery(e.target.value)}
          placeholder="Location…"
          aria-label="Filter by location"
          data-testid="job-location-filter"
          className="glass w-32 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs placeholder:text-aether-muted-dim"
        />
        <select
          value={salaryMinFilter}
          aria-label="Filter by minimum salary"
          onChange={(e) => setSalaryMinFilter(e.target.value as SalaryFilter)}
          data-testid="job-salary-filter"
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs"
        >
          {SALARY_FILTERS.map((s) => (
            <option key={s} value={s} className="bg-black">
              {s === "0" ? "Any salary" : `$${s}k+`}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="remote-toggle"
          aria-pressed={remoteOnly}
          onClick={() => setRemoteOnly((v) => !v)}
          className={`rounded-lg border px-3.5 py-2 text-xs font-medium transition ${
            remoteOnly
              ? "border-aether-indigo/25 bg-aether-indigo/15 text-[#a5b4fc]"
              : "border-white/10 bg-white/5 hover:bg-white/10"
          }`}
        >
          Remote · Hybrid
        </button>
        <select
          value={sort}
          aria-label="Sort jobs"
          onChange={(e) => setSort(e.target.value as "fitScore" | "createdAt")}
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs"
        >
          <option value="fitScore" className="bg-black">Sort: fit score</option>
          <option value="createdAt" className="bg-black">Sort: newest</option>
        </select>
        <div className="flex items-center gap-2.5">
          <span className="text-xs text-aether-muted-dim">Match ≥</span>
          <span className="mono text-xs font-semibold text-aether-coral" data-testid="match-min-value">{matchMin}%</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={matchMin}
            aria-label="Minimum match score"
            data-testid="match-min-slider"
            onChange={(e) => setMatchMin(Number(e.target.value))}
            className="h-1.5 w-28 accent-aether-coral"
          />
        </div>
        <button
          type="button"
          data-testid="clear-filters"
          onClick={clearAll}
          className="ml-auto text-xs text-aether-muted transition hover:text-white"
        >
          Clear filters
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {notice ? (
        <p
          data-testid="tailor-notice"
          className="rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber"
        >
          {notice}
        </p>
      ) : null}

      {/* Loading skeletons */}
      {jobs === null ? (
        <div className="grid gap-4 md:grid-cols-2" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass h-36 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : market === "saved" ? (
        <SavedView
          jobs={visible}
          onUnsave={(id) => void toggleSave(id)}
          onApplyAll={(ids, trigger) => requestBulkApply(ids, trigger)}
        />
      ) : visible.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="jobs-empty-state">
          <p className="text-lg font-semibold">No matching jobs</p>
          <p className="mt-1 text-sm text-aether-muted">
            {(jobs ?? []).length > 0
              ? "No roles match the current market and filters — try Clear filters."
              : historyCount && historyCount > 0
                ? `None of your ${historyCount} saved roles are on the active board right now — they have been applied to, archived, or their source has stopped listing them.`
                : "Run Sync to let the Scout agent find matching roles."}
          </p>
          {/* BLOCKER-006: an empty board with rows in history is a filtered
              state, not an empty account — link to the unfiltered view rather
              than telling the user to sync jobs they already have. */}
          {(jobs ?? []).length === 0 && historyCount && historyCount > 0 ? (
            <a
              href="/dashboard/applications"
              data-testid="jobs-empty-history-link"
              className="mt-3 inline-block text-sm text-aether-coral underline underline-offset-4"
            >
              View all {historyCount} in your application history
            </a>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-5">
          {/* Job list column (jd09–jd15) */}
          <div className="min-w-0 xl:col-span-2">
            {/* Select-all + bulk actions (jd09–jd11) */}
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-xs text-aether-muted">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  aria-label="Select all jobs"
                  data-testid="select-all"
                  className="h-[18px] w-[18px] accent-aether-coral"
                />
                Select all · <span className="text-white" data-testid="selected-count">{selectedIds.size} selected</span>
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="bulk-apply"
                  onClick={(e) =>
                    requestBulkApply(
                      [...selectedIds].filter((id) => visible.some((j) => j.id === id)),
                      e.currentTarget,
                    )
                  }
                  disabled={selectedIds.size === 0 || running}
                  className="rounded-lg bg-aether-coral px-3 py-1.5 text-xs font-medium hover:opacity-90 disabled:opacity-40"
                >
                  Apply ({selectedIds.size})
                </button>
                <button
                  type="button"
                  data-testid="bulk-skip"
                  onClick={() => setSelectedIds(new Set())}
                  disabled={selectedIds.size === 0}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium transition hover:bg-white/10 disabled:opacity-40"
                >
                  Skip
                </button>
              </div>
            </div>

            <div className="grid content-start gap-3">
              {renderedJobs.map((job) => {
                const ins = insights[job.id];
                const active = selected?.id === job.id;
                return (
                  <article
                    key={job.id}
                    data-testid="job-card"
                    onClick={() => setSelectedId(job.id)}
                    className={`relative cursor-pointer overflow-hidden rounded-xl border p-4 transition ${
                      active ? "border-aether-coral/40 bg-aether-coral/[0.08]" : "glass border-white/10 hover:border-white/20"
                    }`}
                  >
                    {active ? <span className="absolute bottom-4 left-0 top-4 w-0.5 rounded-full bg-aether-coral" /> : null}
                    <div className="flex min-w-0 gap-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(job.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleSelect(job.id)}
                        aria-label={`Select ${job.title}`}
                        data-testid="job-select"
                        className="mt-1 h-[18px] w-[18px] shrink-0 accent-aether-coral"
                      />
                      <div className="flex min-w-0 flex-1 gap-3">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-sm font-bold">
                          {initials(job.company)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <h2 className="truncate text-sm font-semibold">
                                {/* Keyboard path for card selection — the card
                                    <article> is mouse-only sugar; nesting
                                    controls under role="button" fails axe
                                    nested-interactive (W-E quality sweep). */}
                                <button
                                  type="button"
                                  aria-pressed={active}
                                  aria-label={`${job.title} at ${job.company}, view details`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedId(job.id);
                                  }}
                                  className="block w-full truncate text-left"
                                >
                                  {job.title}
                                </button>
                              </h2>
                              <p className="truncate text-xs text-aether-muted">
                                {job.company}
                                {job.location ? ` · ${job.location}` : ""}
                                {job.remote ? " · Remote" : ""}
                              </p>
                            </div>
                            <MatchRing value={job.fitScore} size={44} />
                          </div>
                          {/* Skill tags (from ATS insights: matched=green, gap=amber) */}
                          <div className="mt-2.5 flex flex-wrap gap-1.5" data-testid="job-tags">
                            {ins ? (
                              <>
                                {ins.matchedSkills.slice(0, 3).map((s) => (
                                  <span key={s} className="rounded-md border border-aether-green/20 bg-aether-green/[0.12] px-2 py-0.5 text-[10px] text-aether-green">
                                    {s}
                                  </span>
                                ))}
                                {ins.skillGap ? (
                                  <span className="rounded-md border border-aether-yellow/20 bg-aether-yellow/[0.12] px-2 py-0.5 text-[10px] text-aether-yellow">
                                    {ins.skillGap} (gap)
                                  </span>
                                ) : null}
                              </>
                            ) : (
                              <span className="h-[18px] w-24 animate-pulse rounded-md bg-white/5" />
                            )}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                            <span className="mono text-xs text-aether-muted">{salaryLabel(job)}</span>
                            <span className="flex min-w-0 items-center gap-2 text-[11px] text-aether-muted-dim">
                              {job.sourceUrl ? (
                                <a
                                  href={job.sourceUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  data-testid="job-source-link"
                                  title={`Open the original posting on ${SOURCE_LABEL[job.source] ?? job.source}`}
                                  className="truncate rounded bg-white/8 px-1.5 py-0.5 font-medium text-aether-muted underline-offset-2 transition hover:bg-white/15 hover:text-white"
                                >
                                  {SOURCE_LABEL[job.source] ?? job.source} ↗
                                </a>
                              ) : (
                                <span className="truncate rounded bg-white/8 px-1.5 py-0.5 font-medium text-aether-muted">
                                  {SOURCE_LABEL[job.source] ?? job.source}
                                </span>
                              )}
                              <span
                                className="shrink-0"
                                data-testid="job-listing-age"
                                title={
                                  job.lastConfirmedAt
                                    ? `Still listed at the source ${timeAgo(job.lastConfirmedAt)}`
                                    : undefined
                                }
                              >
                                {listingAgeLabel(job)}
                              </span>
                            </span>
                          </div>
                          {autopilotSuppressionHint(job) ? (
                            <p
                              data-testid="autopilot-suppressed-hint"
                              className="mt-2 rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] leading-snug text-aether-muted-dim"
                            >
                              {autopilotSuppressionHint(job)}
                            </p>
                          ) : null}
                          {/* Per-card Apply (GOV-010 / GMV2 §10.2) — reuses the
                              SAME single-job confirmation gate + apply handler
                              the detail panel's "Review & Apply" button opens
                              (openGate/confirmSubmit below), never a second
                              modal implementation (§13.1). */}
                          <div className="mt-2.5 flex justify-end">
                            {job.status === "applied" ? (
                              <span
                                data-testid="job-card-applied"
                                className="rounded-lg border border-aether-green/25 bg-aether-green/10 px-3 py-1.5 text-[11px] font-semibold text-aether-green"
                              >
                                ✓ Applied
                              </span>
                            ) : (
                              <button
                                type="button"
                                data-testid="job-card-apply"
                                aria-label={`Apply to ${job.title} at ${job.company}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openGate(job.id, e.currentTarget);
                                }}
                                className="rounded-lg bg-aether-coral px-3 py-1.5 text-[11px] font-semibold transition hover:opacity-90"
                              >
                                Apply
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
            {visible.length > renderedJobs.length ? (
              <div className="mt-4 flex justify-center">
                <button
                  type="button"
                  data-testid="jobs-load-more"
                  onClick={() => setRenderLimit((n) => n + JOBS_RENDER_PAGE_SIZE)}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-medium text-aether-muted transition hover:bg-white/10 hover:text-white"
                >
                  Load more ({visible.length - renderedJobs.length} remaining)
                </button>
              </div>
            ) : null}
          </div>

          {/* Detail panel (jd16–jd36) */}
          {selected ? (
            <aside className="min-w-0 xl:col-span-3" data-testid="job-detail-panel">
              <div className="glass h-fit rounded-2xl border border-white/10 p-6">
                {/* header */}
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-4">
                    <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-lg font-bold">
                      {initials(selected.company)}
                    </span>
                    <div className="min-w-0">
                      <h2 className="text-xl font-bold">{selected.title}</h2>
                      <p className="mt-0.5 text-sm text-aether-muted">
                        {selected.company}
                        {selected.location ? ` · ${selected.location}` : ""}
                        {selected.remote ? " · Remote" : ""} · <span className="mono">{salaryLabel(selected)}</span>
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {selected.sourceUrl ? (
                          <a
                            href={selected.sourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid="detail-source-link"
                            className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-aether-muted transition hover:border-white/25 hover:text-white"
                          >
                            Sourced from {SOURCE_LABEL[selected.source] ?? selected.source} ↗
                          </a>
                        ) : (
                          <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-aether-muted">
                            Sourced from {SOURCE_LABEL[selected.source] ?? selected.source}
                          </span>
                        )}
                        <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-aether-muted">
                          {selected.postedAt
                            ? `Posted ${timeAgo(selected.postedAt)}`
                            : `Discovered ${timeAgo(selected.createdAt) || "recently"}`}
                        </span>
                      </div>
                      {autopilotSuppressionHint(selected) ? (
                        <p
                          data-testid="autopilot-suppressed-hint-detail"
                          className="mt-2 max-w-md rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[11px] leading-relaxed text-aether-muted-dim"
                        >
                          {autopilotSuppressionHint(selected)}
                        </p>
                      ) : null}
                      <Link
                        href="/dashboard/networking"
                        data-testid="crm-link"
                        className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-[#a5b4fc] transition hover:text-white"
                      >
                        View company in CRM →
                      </Link>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      data-testid="detail-save"
                      onClick={() => void toggleSave(selected.id)}
                      aria-pressed={selected.saved}
                      title={selected.saved ? "Remove from saved" : "Save this role"}
                      className={`flex h-9 w-9 items-center justify-center rounded-lg border transition ${
                        selected.saved
                          ? "border-aether-coral/40 bg-aether-coral/15 text-aether-coral"
                          : "border-white/10 bg-white/5 text-aether-muted hover:bg-white/10 hover:text-white"
                      }`}
                    >
                      {selected.saved ? "🔖" : "🏷️"}
                    </button>
                    <div className="text-center">
                      <MatchRing value={selected.fitScore} size={64} />
                      <p className="mt-1 flex items-center justify-center gap-1 text-[10px] text-aether-muted-dim">
                        <MetricTooltip
                          value="match score"
                          tooltip="How well this posting matches your resume — a 0–100 blend of keyword, semantic and experience fit."
                        />
                      </p>
                    </div>
                  </div>
                </div>

                {/* AI Match Analysis (jd78) */}
                <section className="relative mt-5 overflow-hidden rounded-2xl border border-aether-indigo/25 bg-aether-indigo/5 p-5" data-testid="match-analysis">
                  <div className="mb-3 flex items-center gap-2">
                    <h3 className="text-sm font-semibold">🧠 AI Match Analysis</h3>
                  </div>
                  <p className="text-sm leading-relaxed text-[#C8C8DC]">
                    {selectedInsights?.narrative ?? "Analysing this role against your resume…"}
                  </p>
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="mb-1 text-[11px] text-aether-muted-dim">Skills matched</p>
                      <p className="mono text-sm font-semibold text-aether-green" data-testid="skills-matched">
                        {selectedInsights && insightsAtsMeasured
                          ? `${selectedInsights.skillsMatched} / ${selectedInsights.skillsTotal}`
                          : "—"}
                      </p>
                    </div>
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="mb-1 text-[11px] text-aether-muted-dim">Skill gap</p>
                      <p className="text-sm font-semibold text-aether-yellow" data-testid="skill-gap">
                        {selectedInsights && insightsAtsMeasured
                          ? selectedInsights.skillGap ?? "None"
                          : "—"}
                      </p>
                    </div>
                  </div>
                </section>

                {/* 10-Dimensional Fit Score (jd30) */}
                <section className="mt-5 rounded-2xl border border-white/10 bg-white/[0.02] p-5" data-testid="fit-score">
                  <div className="mb-4 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">📡 10-Dimensional Fit Score</h3>
                    <span className="mono text-xs text-aether-muted-dim">hover a dimension for detail</span>
                  </div>
                  {selectedInsights ? (
                    <div className="flex flex-col gap-6 sm:flex-row">
                      <div className="relative mx-auto h-[188px] w-[188px] shrink-0">
                        <RadarChart dims={selectedInsights.dimensions} />
                      </div>
                      <div className="grid flex-1 grid-cols-1 gap-x-5 gap-y-2.5 sm:grid-cols-2">
                        {selectedInsights.dimensions.map((d) => (
                          <div
                            key={d.label}
                            title={d.degraded ? `${d.label}: not measured` : `${d.label}: ${d.score}/100`}
                            data-testid="fit-dimension"
                          >
                            <div className="mb-1 flex justify-between text-[11px]">
                              <span className="text-aether-muted">
                                {d.label}
                                {d.degraded ? (
                                  <span
                                    className="ml-1.5 rounded-full border border-white/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-aether-muted-dim"
                                    data-testid="dimension-not-measured-badge"
                                  >
                                    not measured
                                  </span>
                                ) : null}
                              </span>
                              <span className="mono" style={{ color: d.degraded ? undefined : ringColor(d.score) }}>
                                {d.degraded ? "—" : d.score}
                              </span>
                            </div>
                            <div className="h-1.5 rounded-full bg-white/[0.06]">
                              <div
                                className={d.degraded ? "h-1.5 rounded-full bg-white/20" : "h-1.5 rounded-full"}
                                style={
                                  d.degraded
                                    ? { width: "0%" }
                                    : { width: `${d.score}%`, background: ringColor(d.score) }
                                }
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="h-40 animate-pulse rounded-xl bg-white/5" aria-busy="true" />
                  )}
                  {selectedInsights && !insightsAtsMeasured ? (
                    /* R-04: the engine itself failed, so keyword match and
                       experience fit were never computed either — a narrower
                       "semantic only" caveat would understate what is missing. */
                    <p className="mt-3 text-xs text-aether-muted-dim" data-testid="insights-ats-unmeasured-note">
                      The scoring engine could not analyse this posting against your
                      résumé, so every résumé-derived dimension above reads as “—”.
                      The salary, location and source-stability signals are computed
                      from the posting itself and are unaffected.
                    </p>
                  ) : selectedInsights && !insightsSemanticTrusted ? (
                    <p className="mt-3 text-xs text-aether-muted-dim" data-testid="insights-semantic-degraded-note">
                      Semantic similarity could not be measured for this analysis — a
                      neutral placeholder stood in instead, so Industry Match, Culture
                      Fit and North Star Align above should be treated as directional
                      until this is available again.
                    </p>
                  ) : null}
                </section>

                {/* Risk Signals (jd31) */}
                <section className="mt-5 rounded-2xl border border-aether-yellow/25 bg-white/[0.02] p-5" data-testid="risk-signals">
                  <div className="mb-3 flex items-center gap-2">
                    <h3 className="text-sm font-semibold">⚠️ Risk Signals</h3>
                    <span className="ml-auto rounded-full bg-aether-yellow/15 px-2 py-0.5 text-[10px] font-semibold text-aether-yellow" data-testid="risk-count">
                      {selectedInsights ? `${selectedInsights.riskSignals.length} flags` : "…"}
                    </span>
                  </div>
                  {selectedInsights && selectedInsights.riskSignals.length > 0 ? (
                    <div className="grid gap-2.5 sm:grid-cols-2">
                      {selectedInsights.riskSignals.map((r) => (
                        <div key={r.label} className="glass-raised flex items-center gap-2.5 rounded-lg border border-white/10 px-3 py-2.5" data-testid="risk-flag">
                          <span className={r.severity === "high" ? "text-[#F87171]" : "text-aether-yellow"}>●</span>
                          <span className="text-xs text-[#C8C8DC]">{r.label}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-aether-muted">{selectedInsights ? "No material risk signals detected." : "…"}</p>
                  )}
                </section>

                {/* Role Description */}
                <section className="mt-5" data-testid="role-description">
                  <h3 className="mb-2 text-sm font-semibold">Role Description</h3>
                  <p
                    className="max-h-48 overflow-y-auto whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-4 text-sm leading-relaxed text-aether-muted"
                    role="region"
                    aria-label="Role description (scrollable)"
                    tabIndex={0}
                  >
                    {selected.description || "No description captured for this posting."}
                  </p>
                </section>

                {/* Two-step apply (jd32–jd36) */}
                <div className="mt-5 flex flex-col gap-3" data-testid="apply-flow">
                  {/* step indicator */}
                  <div className="flex items-center gap-3 text-[11px]">
                    <div className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-semibold ${
                      step === "idle" ? "border-aether-coral/30 bg-aether-coral/15 text-aether-coral" : "border-aether-green/30 bg-aether-green/15 text-aether-green"
                    }`}>
                      <span className="mono flex h-4 w-4 items-center justify-center rounded-full bg-current text-[9px]">
                        <span className="text-[#12121C]">{step === "idle" ? "1" : "✓"}</span>
                      </span>
                      Tailor Resume
                    </div>
                    <div className="h-px flex-1 bg-white/10" />
                    <div className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${
                      step === "tailored" ? "border-aether-coral/30 bg-aether-coral/15 font-semibold text-aether-coral" : "border-white/10 bg-white/5 text-aether-muted-dim"
                    }`}>
                      <span className="mono flex h-4 w-4 items-center justify-center rounded-full bg-white/10 text-[9px]">2</span>
                      Review &amp; Apply
                    </div>
                  </div>

                  {step === "idle" ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        data-testid="tailor-resume"
                        onClick={() => startTailoring(selected.id)}
                        className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-aether-coral py-3 text-sm font-semibold shadow-lg shadow-aether-coral/25 hover:opacity-90"
                      >
                        ✦ Tailor Resume →
                      </button>
                      <Link
                        href={`/dashboard/resume?job=${selected.id}`}
                        data-testid="preview-link"
                        className="rounded-xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-medium transition hover:bg-white/10"
                      >
                        Preview
                      </Link>
                      {selected.sourceUrl ? (
                        <a
                          href={selected.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid="view-posting-link"
                          className="rounded-xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-medium transition hover:bg-white/10"
                        >
                          View posting ↗
                        </a>
                      ) : null}
                      <button
                        type="button"
                        data-testid="skip-job"
                        onClick={() => skipToNext(selected.id)}
                        className="rounded-xl px-5 py-3 text-sm font-medium text-aether-muted transition hover:bg-white/5 hover:text-white"
                      >
                        Skip
                      </button>
                    </div>
                  ) : step === "tailoring" ? (
                    <div className="glass-raised flex items-center gap-3 rounded-xl border border-aether-indigo/25 px-4 py-3" data-testid="tailoring-progress" aria-live="polite">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#a5b4fc] border-t-transparent" />
                      <span className="text-sm text-[#C8C8DC]">
                        Tailoring your resume for <span className="font-semibold text-white">{selected.company}</span> — matching keywords, preserving your voice…
                      </span>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3" data-testid="apply-step2">
                      <div className="rounded-xl border border-aether-green/25 bg-aether-green/10 px-4 py-3">
                        <div className="flex items-center gap-2 text-[13px] text-[#C8C8DC]">
                          {/* RT-010: an in-session tailoring run reports its
                              change count; a job already tailored in a prior
                              session / by the agents has no local result, so
                              state the honest fact without a fake "0 changes". */}
                          {tailorResults[selected.id] ? (
                            <>
                              ✓ Resume tailored ·{" "}
                              <span className="mono font-semibold text-aether-green">
                                {tailorResults[selected.id].changes}
                              </span>{" "}
                              changes applied
                              {tailorResults[selected.id]?.rejected?.length ? (
                                <span className="text-aether-muted-dim">
                                  · {tailorResults[selected.id].rejected.length} rejected by fabrication guard
                                </span>
                              ) : null}
                            </>
                          ) : selected.tailoredResumeStatus === "pending" ? (
                            <span className="text-aether-amber">
                              ✓ Resume tailored —{" "}
                              <a
                                href="/dashboard/approvals"
                                className="font-semibold underline"
                              >
                                pending your review
                              </a>
                            </span>
                          ) : (
                            <>✓ Resume already tailored for this role</>
                          )}
                        </div>
                        {tailorResults[selected.id]?.rejected?.length ? (
                          <p
                            className="mt-2 text-[11px] leading-relaxed text-aether-muted-dim"
                            data-testid="tailor-rejected-note"
                          >
                            {tailorResults[selected.id].changes} of{" "}
                            {tailorResults[selected.id].changes + tailorResults[selected.id].rejected.length}{" "}
                            suggestions applied — the rest were rejected by the fabrication guard because they
                            couldn&apos;t be verified against your real experience, so nothing unsupported was added
                            to your resume.
                          </p>
                        ) : null}
                        <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px]">
                          <Link href="/dashboard/stories" className="font-medium text-[#a5b4fc] transition hover:text-white">
                            Pull from Story Bank →
                          </Link>
                          <Link href={`/dashboard/resume?job=${selected.id}`} className="text-aether-muted transition hover:text-white">
                            Open in Resume Studio
                          </Link>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          data-testid="review-apply"
                          onClick={(e) => openGate(selected.id, e.currentTarget)}
                          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-aether-coral py-3 text-sm font-semibold shadow-lg shadow-aether-coral/25 hover:opacity-90"
                        >
                          ✈ Review &amp; Apply →
                        </button>
                        <button
                          type="button"
                          data-testid="retailor"
                          onClick={() => resetTailoring(selected.id)}
                          className="rounded-xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-medium transition hover:bg-white/10"
                        >
                          Re-tailor
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </aside>
          ) : null}
        </div>
      )}

      {/* Submit confirmation gate (jd37–jd39) */}
      {gateOpen && gateJob ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" data-testid="submit-gate">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={closeGate} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="submitGateTitle"
            className="glass-raised relative w-[480px] max-w-[92vw] rounded-2xl border border-aether-coral/40 p-6 shadow-2xl"
          >
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-aether-yellow/30 bg-aether-yellow/15 text-aether-yellow">⚠️</span>
              <div className="flex-1">
                <h3 id="submitGateTitle" className="text-base font-semibold leading-snug">
                  Submit application to <span className="text-aether-coral">{gateJob.company}</span>?
                </h3>
                <p className="mt-1 text-[12px] text-aether-muted">
                  Your application for <span className="text-[#C7C7D6]">{gateJob.title}</span> will be recorded as{" "}
                  <span className="text-[#C7C7D6]">Applied</span>{" "}
                  {gateJobTailored ? (
                    "with your tailored resume attached."
                  ) : (
                    <>
                      using your <span className="text-aether-yellow">current, untailored</span> resume.
                    </>
                  )}{" "}
                  <span className="text-aether-yellow">
                    Complete the submission on {SOURCE_LABEL[gateJob.source] ?? gateJob.source}
                    {gateJob.sourceUrl ? (
                      <>
                        {" — "}
                        <a
                          href={gateJob.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid="gate-posting-link"
                          className="font-semibold underline underline-offset-2 transition hover:text-white"
                        >
                          open the job posting ↗
                        </a>
                      </>
                    ) : (
                      " via the job posting link"
                    )}
                    .
                  </span>
                </p>
              </div>
              <button type="button" onClick={closeGate} aria-label="Close" className="text-aether-muted transition hover:text-white">✕</button>
            </div>

            <div className="mt-4 space-y-2 rounded-xl border border-white/10 bg-black/25 p-3.5 text-[12px]">
              <div className="flex items-center justify-between"><span className="text-aether-muted-dim">Role</span><span className="text-[#C7C7D6]">{gateJob.title}</span></div>
              <div className="flex items-center justify-between"><span className="text-aether-muted-dim">Company</span><span className="text-[#C7C7D6]">{gateJob.company}</span></div>
              <div className="flex items-center justify-between">
                <span className="text-aether-muted-dim">Resume</span>
                <span
                  data-testid="gate-resume-status"
                  className={gateJobTailored ? "font-medium text-aether-green" : "font-medium text-aether-yellow"}
                >
                  {gateJobTailored ? "Tailored for this role" : "Current (not tailored)"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-aether-muted-dim">Match score</span>
                <span className="mono font-semibold text-aether-green">
                  <MetricTooltip
                    value={gateJob.fitScore != null ? Math.round(gateJob.fitScore) : "—"}
                    tooltip="How well this posting matches your resume — a 0–100 blend of keyword, semantic and experience fit."
                  />
                </span>
              </div>
            </div>

            {submitted ? (
              <div className="mt-4 flex items-center gap-2 rounded-xl border border-aether-green/25 bg-aether-green/10 px-3.5 py-2.5 text-[12px]" data-testid="submitted-state" role="status">
                ✓ Application recorded for {gateJob.company}.{" "}
                <span className="text-aether-muted">
                  Tracking in Applications ·{" "}
                  {gateJob.sourceUrl ? (
                    <a
                      href={gateJob.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline underline-offset-2 transition hover:text-white"
                    >
                      finish the submission on the job board ↗
                    </a>
                  ) : (
                    "finish the submission on the job board."
                  )}
                </span>
              </div>
            ) : (
              <div className="mt-5 flex items-center justify-end gap-2">
                <button type="button" data-testid="submit-cancel" onClick={closeGate} className="glass-raised rounded-xl px-4 py-2.5 text-[13px] transition hover:border-white/20">Cancel</button>
                <button
                  ref={gateConfirmRef}
                  type="button"
                  data-testid="submit-confirm"
                  onClick={() => void confirmSubmit()}
                  disabled={submitting}
                  className="flex items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-[13px] font-semibold hover:opacity-90 disabled:opacity-50"
                >
                  {submitting ? "Submitting…" : "✈ Submit Application"}
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {/* Bulk-apply confirmation gate (MV-job-discovery-002) — same
          irreversible-action safety as the single-job submit gate above,
          applied to "Apply (N)" and Saved's "Apply to all". No per-job
          tailoring runs for a bulk submission; the dialog says so. */}
      {bulkGateOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" data-testid="bulk-apply-gate">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={closeBulkGate} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="bulkGateTitle"
            className="glass-raised relative w-[520px] max-w-[92vw] rounded-2xl border border-aether-coral/40 p-6 shadow-2xl"
          >
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-aether-yellow/30 bg-aether-yellow/15 text-aether-yellow">⚠️</span>
              <div className="flex-1">
                <h3 id="bulkGateTitle" className="text-base font-semibold leading-snug">
                  Submit {bulkGateIds.length} application{bulkGateIds.length === 1 ? "" : "s"} without tailoring?
                </h3>
                <p className="mt-1 text-[12px] text-aether-muted">
                  Th{bulkGateIds.length === 1 ? "is job" : "ese jobs"} will be recorded as{" "}
                  <span className="text-[#C7C7D6]">Applied</span> using your{" "}
                  <span className="text-aether-yellow">current, untailored</span> resume — bulk submission does not
                  run per-job tailoring. This action cannot be undone.
                </p>
              </div>
              <button type="button" onClick={closeBulkGate} aria-label="Close" className="text-aether-muted transition hover:text-white">✕</button>
            </div>

            <div
              className="mt-4 max-h-52 space-y-1.5 overflow-y-auto rounded-xl border border-white/10 bg-black/25 p-3.5 text-[12px]"
              data-testid="bulk-apply-gate-list"
            >
              {bulkGateJobs.map((j) => (
                <div key={j.id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-[#C7C7D6]">{j.title}</span>
                  <span className="shrink-0 text-aether-muted-dim">{j.company}</span>
                </div>
              ))}
            </div>

            {bulkSubmitted ? (
              <div
                className="mt-4 flex items-center gap-2 rounded-xl border border-aether-green/25 bg-aether-green/10 px-3.5 py-2.5 text-[12px]"
                data-testid="bulk-submitted-state"
                role="status"
              >
                ✓ {bulkGateIds.length} application{bulkGateIds.length === 1 ? "" : "s"} recorded.
              </div>
            ) : (
              <div className="mt-5 flex items-center justify-end gap-2">
                <button
                  type="button"
                  data-testid="bulk-apply-cancel"
                  onClick={closeBulkGate}
                  className="glass-raised rounded-xl px-4 py-2.5 text-[13px] transition hover:border-white/20"
                >
                  Cancel
                </button>
                <button
                  ref={bulkGateConfirmRef}
                  type="button"
                  data-testid="bulk-apply-confirm"
                  onClick={() => void confirmBulkApply()}
                  disabled={bulkSubmitting}
                  className="flex items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-[13px] font-semibold hover:opacity-90 disabled:opacity-50"
                >
                  {bulkSubmitting
                    ? "Submitting…"
                    : `✈ Submit ${bulkGateIds.length} Application${bulkGateIds.length === 1 ? "" : "s"}`}
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Saved view (jd42–jd49)
// ---------------------------------------------------------------------------
function SavedView({
  jobs,
  onUnsave,
  onApplyAll,
}: {
  jobs: Job[];
  onUnsave: (id: string) => void;
  onApplyAll: (ids: string[], trigger: HTMLElement | null) => void;
}) {
  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center" data-testid="saved-jobs-empty-state">
        <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-xl">🔖</div>
        <p className="text-sm font-semibold">No saved jobs yet</p>
        <p className="mt-1 max-w-xs text-xs text-aether-muted-dim">
          Tap the bookmark on any role to save it here and revisit it later.
        </p>
      </div>
    );
  }
  return (
    <div data-testid="saved-view">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold">
            🔖 Saved jobs <span className="mono text-xs font-semibold text-aether-muted-dim">· {jobs.length}</span>
          </h2>
          <p className="mt-0.5 text-xs text-aether-muted-dim">
            Roles you bookmarked to revisit — tailor &amp; apply when you&apos;re ready.
          </p>
        </div>
        <button
          type="button"
          data-testid="saved-apply-all"
          onClick={(e) =>
            onApplyAll(
              jobs.map((j) => j.id),
              e.currentTarget,
            )
          }
          className="flex items-center gap-2 rounded-lg bg-aether-coral px-4 py-2 text-xs font-semibold shadow-lg shadow-aether-coral/25 hover:opacity-90"
        >
          ✦ Apply to all ({jobs.length})
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {jobs.map((job) => (
          <article key={job.id} data-testid="saved-card" className="glass relative rounded-xl border border-white/10 p-4 transition hover:border-white/20">
            <button
              type="button"
              data-testid="unsave"
              onClick={() => onUnsave(job.id)}
              title="Remove from saved"
              aria-label={`Remove ${job.title} from saved`}
              className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-aether-coral transition hover:bg-white/10"
            >
              🔖
            </button>
            <div className="flex gap-3 pr-8">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-sm font-bold">
                {initials(job.company)}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold leading-tight">{job.title}</h3>
                <p className="mt-0.5 truncate text-xs text-aether-muted">
                  {job.company}
                  {job.location ? ` · ${job.location}` : ""}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="mono text-xs text-aether-muted">{salaryLabel(job)}</span>
                  <span className="flex items-center gap-2 text-[11px] text-aether-muted-dim">
                    {job.sourceUrl ? (
                      <a
                        href={job.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        data-testid="saved-source-link"
                        title={`Open the original posting on ${SOURCE_LABEL[job.source] ?? job.source}`}
                        className="rounded bg-white/8 px-1.5 py-0.5 font-medium text-aether-muted transition hover:bg-white/15 hover:text-white"
                      >
                        {SOURCE_LABEL[job.source] ?? job.source} ↗
                      </a>
                    ) : (
                      <span className="rounded bg-white/8 px-1.5 py-0.5 font-medium text-aether-muted">
                        {SOURCE_LABEL[job.source] ?? job.source}
                      </span>
                    )}
                    {job.fitScore != null ? <span className="mono text-aether-green">{Math.round(job.fitScore)}</span> : null}
                  </span>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
