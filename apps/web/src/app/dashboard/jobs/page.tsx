"use client";

/**
 * Job Discovery — live wiring to GET /jobs, POST /agents/scout/run and
 * POST /jobs/{id}/save. Wireframe: job-discovery.html — source connection
 * bar, ranked job list, detail panel with AI Match Analysis / Risk Signals /
 * Role Description and the Tailor → Review & Apply flow.
 *
 * `?demo=empty` renders the saved-jobs empty state (same conditional branch
 * that production shows when the saved filter matches nothing).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../../lib/api/client";
import type { Job, JobStatus } from "../../../lib/api/jobs";

const STATUS_FILTERS: Array<JobStatus | "all"> = [
  "all",
  "discovered",
  "matched",
  "tailoring",
  "ready",
  "applied",
  "archived",
];

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

/** Display label for a job source (wireframe source bar naming). */
const SOURCE_LABEL: Record<string, string> = {
  seek: "Seek.com.au",
  linkedin: "LinkedIn AU",
  indeed: "Indeed AU",
  jora: "Jora",
  greenhouse: "Greenhouse",
  lever: "Lever",
  remotive: "Remotive",
  remoteok: "RemoteOK",
};

/** Job-board connections (wireframe jd05–jd10 source bar). */
const SOURCE_CONNECTIONS = [
  { badge: "SEEK", name: "Seek.com.au", state: "Connected · via Browser", note: "Playwright session — jobs sourced from Seek.com.au", connected: true },
  { badge: "in", name: "LinkedIn AU", state: "Connected · OAuth", note: "Manage", connected: true },
  { badge: "WF", name: "Workforce AU", state: "MyGov login req.", note: "Connect via MyGov", connected: false },
  { badge: "Jora", name: "Jora", state: "Not connected", note: "Connect via Browser", connected: false },
  { badge: "in", name: "Indeed AU", state: "Not connected", note: "Connect via Browser", connected: false },
];

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [savedOnly, setSavedOnly] = useState(false);
  const [sort, setSort] = useState<"createdAt" | "fitScore">("fitScore");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [demoEmpty, setDemoEmpty] = useState(false);

  // ?demo=empty → force the saved-jobs empty state (same conditional branch).
  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "empty") {
      setDemoEmpty(true);
      setSavedOnly(true);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ sort });
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (sourceFilter !== "all") params.set("source", sourceFilter);
      if (savedOnly) params.set("saved", "true");
      const data = await apiRequest<Job[]>(`/jobs?${params.toString()}`);
      setJobs(data);
      setSelectedId((prev) => (data.some((j) => j.id === prev) ? prev : (data[0]?.id ?? null)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
      setJobs([]);
    }
  }, [sort, statusFilter, sourceFilter, savedOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const runDiscovery = async () => {
    setRunning(true);
    try {
      await apiRequest("/agents/scout/run", {
        method: "POST",
        body: {
          query: "delivery lead, product owner, business analyst, program manager",
          location: "Melbourne, Australia",
        },
      });
      await apiRequest("/agents/fit-scorer/run", { method: "POST" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery run failed");
    } finally {
      setRunning(false);
    }
  };

  const toggleSave = async (jobId: string) => {
    const updated = await apiRequest<Job>(`/jobs/${jobId}/save`, { method: "POST" });
    setJobs((prev) => (prev ?? []).map((j) => (j.id === jobId ? updated : j)));
  };

  const visible = demoEmpty ? [] : (jobs ?? []);
  const selected = visible.find((j) => j.id === selectedId) ?? visible[0];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Job Discovery</h1>
          <p className="text-sm text-aether-muted">
            Discovered postings, ranked by ATS fit score.
          </p>
        </div>
        <button
          type="button"
          data-testid="run-discovery-btn"
          onClick={() => void runDiscovery()}
          disabled={running}
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {running ? "Running…" : "Run Discovery"}
        </button>
      </header>

      {/* Source connections bar (wireframe jd05–jd10) */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" data-testid="source-bar">
        {SOURCE_CONNECTIONS.map((s) => (
          <div key={s.name} className={`glass rounded-xl border p-3 ${s.connected ? "border-aether-green/25" : "border-white/10"}`}>
            <div className="flex items-center gap-2">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold ${s.connected ? "bg-aether-green/15 text-aether-green" : "bg-white/10 text-aether-muted-dim"}`}>
                {s.badge}
              </span>
              <p className="truncate text-xs font-semibold">{s.name}</p>
            </div>
            <p className={`mt-1.5 text-[11px] ${s.connected ? "text-aether-green" : "text-aether-muted-dim"}`}>{s.state}</p>
            <p className="truncate text-[10px] text-aether-muted-dim">{s.note}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3" data-testid="job-filter-bar">
        <select
          value={statusFilter}
          aria-label="Filter by status"
          onChange={(e) => setStatusFilter(e.target.value as JobStatus | "all")}
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-1.5 text-sm"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s} className="bg-black">
              {s === "all" ? "All statuses" : s}
            </option>
          ))}
        </select>
        <select
          value={sourceFilter}
          aria-label="Filter by source"
          onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          data-testid="job-source-filter"
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-1.5 text-sm"
        >
          {SOURCE_FILTERS.map((s) => (
            <option key={s} value={s} className="bg-black">
              {s === "all" ? "All sources" : s}
            </option>
          ))}
        </select>
        <select
          value={sort}
          aria-label="Sort jobs"
          onChange={(e) => setSort(e.target.value as "createdAt" | "fitScore")}
          className="glass rounded-lg border border-white/10 bg-transparent px-3 py-1.5 text-sm"
        >
          <option value="fitScore" className="bg-black">Sort: fit score</option>
          <option value="createdAt" className="bg-black">Sort: newest</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-aether-muted">
          <input
            type="checkbox"
            checked={savedOnly}
            onChange={(e) => {
              setSavedOnly(e.target.checked);
              if (!e.target.checked) setDemoEmpty(false);
            }}
          />
          Saved only
        </label>
      </div>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {jobs === null ? (
        <div className="grid gap-4 md:grid-cols-2" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass h-36 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        savedOnly ? (
          <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="saved-jobs-empty-state">
            <p className="text-lg font-semibold">No saved jobs yet</p>
            <p className="mt-1 text-sm text-aether-muted">
              Tap the bookmark on any role to save it here and revisit it later.
            </p>
          </div>
        ) : (
          <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="jobs-empty-state">
            <p className="text-lg font-semibold">No jobs yet</p>
            <p className="mt-1 text-sm text-aether-muted">
              Run Discovery to let the Scout agent find matching roles.
            </p>
          </div>
        )
      ) : (
        <div className="grid gap-6 xl:grid-cols-5">
          {/* Job list */}
          <div className="grid content-start gap-4 xl:col-span-2">
            {visible.map((job) => (
              <article
                key={job.id}
                data-testid="job-card"
                role="button"
                tabIndex={0}
                onClick={() => setSelectedId(job.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedId(job.id);
                }}
                className={`glass cursor-pointer rounded-2xl border p-5 transition hover:border-white/25 ${
                  selected?.id === job.id ? "border-aether-coral/40" : "border-white/10"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">{job.title}</h2>
                    <p className="text-sm text-aether-muted">
                      {job.company}
                      {job.location ? ` · ${job.location}` : ""}
                      {job.remote ? " · Remote" : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    data-testid="save-job-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      void toggleSave(job.id);
                    }}
                    aria-pressed={job.saved}
                    className={`text-lg ${job.saved ? "text-aether-amber" : "text-aether-muted-dim"}`}
                    title={job.saved ? "Unsave" : "Save"}
                  >
                    ★
                  </button>
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-aether-muted">{job.description}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-aether-muted-dim">
                  <span className="rounded-full border border-white/10 px-2 py-0.5">{job.source}</span>
                  <span className="rounded-full border border-white/10 px-2 py-0.5">{job.status}</span>
                  {job.fitScore != null ? (
                    <span className="mono text-aether-green">fit {Math.round(job.fitScore)}</span>
                  ) : (
                    <span>unscored</span>
                  )}
                </div>
              </article>
            ))}
          </div>

          {/* Detail panel (wireframe jd17–jd43) */}
          {selected ? (
            <aside className="glass h-fit rounded-2xl border border-white/10 p-6 xl:col-span-3" data-testid="job-detail-panel">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold">{selected.title}</h2>
                  <p className="text-sm text-aether-muted">
                    {selected.company}
                    {selected.location ? ` · ${selected.location}` : ""}
                    {selected.remote ? " · Remote" : ""}
                  </p>
                </div>
                <span className="rounded-md border border-white/15 bg-white/5 px-2 py-1 text-[11px] text-aether-muted">
                  Sourced from {SOURCE_LABEL[selected.source] ?? selected.source}
                </span>
              </div>

              {/* AI Match Analysis */}
              <section className="mt-5" data-testid="match-analysis">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-violet">
                  AI Match Analysis
                </h3>
                <div className="flex items-center gap-4 rounded-xl border border-aether-violet/25 bg-aether-violet/5 p-4">
                  <span className="mono text-2xl font-bold text-aether-green">
                    {selected.fitScore != null ? `${Math.round(selected.fitScore)}%` : "—"}
                  </span>
                  <p className="text-xs text-aether-muted">
                    {selected.fitScore != null
                      ? "Fit score from the Evaluator agent — resume keywords, seniority and domain overlap against this posting."
                      : "Not scored yet — run the Fit Scorer agent to analyse this role against your resume."}
                  </p>
                </div>
                <p className="mt-2 text-[11px] text-aether-muted-dim">
                  Benchmarked against your target role: Senior Technical Program Manager.
                </p>
              </section>

              {/* Risk Signals */}
              <section className="mt-4" data-testid="risk-signals">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-amber">
                  Risk Signals
                </h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {!/\$\s?\d/.test(selected.description ?? "") ? (
                    <div className="rounded-xl border border-aether-amber/25 bg-aether-amber/5 p-3">
                      <p className="text-xs font-semibold text-aether-amber">No salary listed</p>
                      <p className="mt-0.5 text-[11px] text-aether-muted-dim">
                        Posting omits a salary band — clarify before the final round.
                      </p>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-aether-green/25 bg-aether-green/5 p-3">
                      <p className="text-xs font-semibold text-aether-green">Salary listed</p>
                      <p className="mono mt-0.5 text-[11px] text-aether-muted-dim">See role description for the band.</p>
                    </div>
                  )}
                  <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                    <p className="text-xs font-semibold text-aether-muted">Recruiter response: Low</p>
                    <p className="mt-0.5 text-[11px] text-aether-muted-dim">
                      This board&apos;s recruiters typically reply to fewer than 1 in 5 applicants.
                    </p>
                  </div>
                </div>
              </section>

              {/* Role Description */}
              <section className="mt-4" data-testid="role-description">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                  Role Description
                </h3>
                <p className="max-h-48 overflow-y-auto whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-aether-muted">
                  {selected.description || "No description captured for this posting."}
                </p>
              </section>

              {/* Apply flow (wireframe stepper: 1 Tailor Resume → 2 Review & Apply) */}
              <section className="mt-5 rounded-xl border border-white/10 bg-white/5 p-4" data-testid="apply-flow">
                <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
                  <span className="flex items-center gap-1.5">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-aether-coral text-[10px] font-bold text-white">1</span>
                    <span className="font-semibold">Tailor Resume</span>
                  </span>
                  <span className="text-aether-muted-dim">→</span>
                  <span className="flex items-center gap-1.5">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-[10px] font-bold text-aether-muted-dim">2</span>
                    <span className="text-aether-muted">Review &amp; Apply</span>
                  </span>
                  <span className="ml-auto rounded-md border border-aether-green/25 bg-aether-green/10 px-2 py-0.5 text-[10px] text-aether-green">
                    Voice-Authentic
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link
                    href={`/dashboard/resume?job=${selected.id}`}
                    data-testid="tailor-job-link"
                    className="rounded-lg bg-aether-coral px-3 py-2 text-xs font-semibold text-white transition hover:opacity-90"
                  >
                    Tailor Resume
                  </Link>
                  {selected.sourceUrl && !selected.sourceUrl.includes("demo.aether.dev") ? (
                    <a
                      href={selected.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid="apply-link"
                      className="rounded-lg border border-aether-green/40 px-3 py-2 text-xs font-semibold text-aether-green transition hover:bg-aether-green/10"
                    >
                      Preview
                    </a>
                  ) : (
                    <button
                      type="button"
                      className="rounded-lg border border-white/15 px-3 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white"
                    >
                      Preview
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      const idx = visible.findIndex((j) => j.id === selected.id);
                      const next = visible[(idx + 1) % visible.length];
                      if (next) setSelectedId(next.id);
                    }}
                    className="rounded-lg border border-white/15 px-3 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white"
                  >
                    Skip
                  </button>
                </div>
              </section>
            </aside>
          ) : null}
        </div>
      )}
    </div>
  );
}
