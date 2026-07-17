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
import { fetchScoutSources } from "../../../lib/api/jobs";
import type { Job, ScoutSourceStatus } from "../../../lib/api/jobs";
import MetricTooltip from "../../../components/MetricTooltip";
import { sourceStatusView } from "../../../components/dashboard/sourceStatus";

// ---------------------------------------------------------------------------
// Types (insights payload from GET /jobs/{id}/insights)
// ---------------------------------------------------------------------------
interface Dimension {
  label: string;
  score: number;
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
  const shape = dims.map((d, i) => pt(i, (maxR * Math.max(4, d.score)) / 100).map((x) => x.toFixed(1)).join(",")).join(" ");
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
  const [sort, setSort] = useState<"fitScore" | "createdAt">("fitScore");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [demoEmpty, setDemoEmpty] = useState(false);

  const [insights, setInsights] = useState<Record<string, Insights>>({});
  const insightsInFlight = useRef<Set<string>>(new Set());

  // Apply flow (per selected job) + submit gate.
  const [applyStep, setApplyStep] = useState<Record<string, "idle" | "tailoring" | "tailored">>({});
  const [tailorResults, setTailorResults] = useState<
    Record<string, { resume_id: string; changes: number; rejected: string[] }>
  >({});
  const [gateOpen, setGateOpen] = useState(false);
  const [gateJobId, setGateJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const gateTriggerRef = useRef<HTMLElement | null>(null);
  const gateConfirmRef = useRef<HTMLButtonElement | null>(null);

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
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
      setJobs([]);
    }
  }, [sort, sourceFilter]);

  useEffect(() => {
    void load();
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
      return true;
    });
  }, [marketJobs, remoteOnly, matchMin, locationQuery]);

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
    return { matches: all.length, newToday, sources };
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

  const selected = visible.find((j) => j.id === selectedId) ?? (market === "saved" ? undefined : visible[0]);
  const selectedInsights = selected ? insights[selected.id] : undefined;
  const step = selected ? applyStep[selected.id] ?? "idle" : "idle";

  const runDiscovery = async () => {
    setRunning(true);
    setError(null);
    try {
      await apiRequest("/agents/scout/run", {
        method: "POST",
        body: { query: "delivery lead, product owner, program manager, business analyst", location: "Australia" },
      });
      await apiRequest("/agents/fit-scorer/run", { method: "POST" });
      setInsights({});
      await Promise.all([load(), loadSourceStatus()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery run failed");
    } finally {
      setRunning(false);
    }
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
    try {
      const raw = await apiRequest<{ resume_id: string; changes: number; rejected: string[] }>(
        "/agents/tailor/run",
        { method: "POST", body: { job_id: jobId } },
      );
      // Dual-shape (GAP-P7-ASYNC-001 §6): unwrap a 202 enqueue envelope by
      // polling; a legacy synchronous body passes through unchanged.
      const out = await resolveRun(raw);
      setTailorResults((p) => ({ ...p, [jobId]: out }));
      setApplyStep((p) => ({ ...p, [jobId]: "tailored" }));
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

  const bulkApply = async (explicitIds?: string[]) => {
    const ids = explicitIds ?? [...selectedIds].filter((id) => visible.some((j) => j.id === id));
    if (ids.length === 0) return;
    setRunning(true);
    try {
      for (const id of ids) {
        const res = await apiRequest<{ job: Job }>(`/jobs/${id}/apply`, { method: "POST" });
        setJobs((prev) => (prev ?? []).map((j) => (j.id === res.job.id ? res.job : j)));
      }
      setSelectedIds(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk apply failed");
    } finally {
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

  const clearAll = () => {
    setSourceFilter("all");
    setRemoteOnly(false);
    setMatchMin(0);
    setLocationQuery("");
    setSort("fitScore");
  };

  const gateJob = gateJobId ? (jobs ?? []).find((j) => j.id === gateJobId) : undefined;

  return (
    <div className="space-y-5">
      {/* Header + stats subtitle (jd03) */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Job Discovery</h1>
          <p className="mono text-xs text-aether-muted-dim" data-testid="jobs-stats">
            {stats.matches} matches across markets · {stats.newToday} new today · {stats.sources} sources connected
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
        <div className="flex items-stretch gap-3 overflow-x-auto pb-1">
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
          <div className="flex gap-2 overflow-x-auto pb-1" aria-busy="true">
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
        <select
          value={sourceFilter}
          aria-label="Filter by source"
          onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          data-testid="job-source-filter"
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs"
        >
          {SOURCE_FILTERS.map((s) => (
            <option key={s} value={s} className="bg-black">
              {s === "all" ? "All sources" : SOURCE_LABEL[s] ?? s}
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
          Clear all
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
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
          onApplyAll={(ids) => void bulkApply(ids)}
        />
      ) : visible.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="jobs-empty-state">
          <p className="text-lg font-semibold">No matching jobs</p>
          <p className="mt-1 text-sm text-aether-muted">
            {(jobs ?? []).length === 0
              ? "Run Sync to let the Scout agent find matching roles."
              : "No roles match the current market and filters — try Clear all."}
          </p>
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
                  onClick={() => void bulkApply()}
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
              {visible.map((job) => {
                const ins = insights[job.id];
                const active = selected?.id === job.id;
                return (
                  <article
                    key={job.id}
                    data-testid="job-card"
                    role="button"
                    tabIndex={0}
                    aria-pressed={active}
                    onClick={() => setSelectedId(job.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(job.id);
                      }
                    }}
                    className={`relative cursor-pointer rounded-xl border p-4 transition ${
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
                              <h2 className="truncate text-sm font-semibold">{job.title}</h2>
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
                              <span className="shrink-0">{timeAgo(job.createdAt)}</span>
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
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
                        {selectedInsights ? `${selectedInsights.skillsMatched} / ${selectedInsights.skillsTotal}` : "—"}
                      </p>
                    </div>
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="mb-1 text-[11px] text-aether-muted-dim">Skill gap</p>
                      <p className="text-sm font-semibold text-aether-yellow" data-testid="skill-gap">
                        {selectedInsights ? selectedInsights.skillGap ?? "None" : "—"}
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
                          <div key={d.label} title={`${d.label}: ${d.score}/100`} data-testid="fit-dimension">
                            <div className="mb-1 flex justify-between text-[11px]">
                              <span className="text-aether-muted">{d.label}</span>
                              <span className="mono" style={{ color: ringColor(d.score) }}>{d.score}</span>
                            </div>
                            <div className="h-1.5 rounded-full bg-white/[0.06]">
                              <div className="h-1.5 rounded-full" style={{ width: `${d.score}%`, background: ringColor(d.score) }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="h-40 animate-pulse rounded-xl bg-white/5" aria-busy="true" />
                  )}
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
                  <p className="max-h-48 overflow-y-auto whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-4 text-sm leading-relaxed text-aether-muted">
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
                          ✓ Resume tailored ·{" "}
                          <span className="mono font-semibold text-aether-green">
                            {tailorResults[selected.id]?.changes ?? 0}
                          </span>{" "}
                          changes applied
                          {tailorResults[selected.id]?.rejected?.length ? (
                            <span className="text-aether-muted-dim">
                              · {tailorResults[selected.id].rejected.length} rejected by fabrication guard
                            </span>
                          ) : null}
                        </div>
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
                  <span className="text-[#C7C7D6]">Applied</span> with your tailored resume attached.{" "}
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
  onApplyAll: (ids: string[]) => void;
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
          onClick={() => onApplyAll(jobs.map((j) => j.id))}
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
