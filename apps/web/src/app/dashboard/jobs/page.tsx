"use client";

/**
 * Jobs workspace — live wiring to GET /jobs, POST /agents/scout/run and
 * POST /jobs/{id}/save (P2 frontend).
 */
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

const SOURCE_FILTERS = ["all", "seek", "linkedin", "indeed"] as const;
type SourceFilter = (typeof SOURCE_FILTERS)[number];

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [savedOnly, setSavedOnly] = useState(false);
  const [sort, setSort] = useState<"createdAt" | "fitScore">("fitScore");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ sort });
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (sourceFilter !== "all") params.set("source", sourceFilter);
      if (savedOnly) params.set("saved", "true");
      const data = await apiRequest<Job[]>(`/jobs?${params.toString()}`);
      setJobs(data);
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
        body: { query: "software engineer", location: "Australia" },
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

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Jobs</h1>
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

      <div className="flex flex-wrap items-center gap-3" data-testid="job-filter-bar">
        <select
          value={statusFilter}
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
            onChange={(e) => setSavedOnly(e.target.checked)}
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
      ) : jobs.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="jobs-empty-state">
          <p className="text-lg font-semibold">No jobs yet</p>
          <p className="mt-1 text-sm text-aether-muted">
            Run Discovery to let the Scout agent find matching roles.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {jobs.map((job) => (
            <article
              key={job.id}
              data-testid="job-card"
              className="glass rounded-2xl border border-white/10 p-5 transition hover:border-white/20"
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
                  onClick={() => void toggleSave(job.id)}
                  aria-pressed={job.saved}
                  className={`text-lg ${job.saved ? "text-aether-amber" : "text-aether-muted-dim"}`}
                  title={job.saved ? "Unsave" : "Save"}
                >
                  ★
                </button>
              </div>
              <p className="mt-2 line-clamp-2 text-sm text-aether-muted">{job.description}</p>
              <div className="mt-3 flex items-center gap-3 text-xs text-aether-muted-dim">
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
      )}
    </div>
  );
}
