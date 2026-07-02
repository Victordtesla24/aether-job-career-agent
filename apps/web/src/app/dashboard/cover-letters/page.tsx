"use client";

/**
 * Cover letters — evidence-guarded drafts backed by GET /cover-letters and
 * POST /agents/cover-letter/run. Every draft routes through the approval queue.
 */
import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../../lib/api/client";
import {
  fetchCoverLetters,
  runCoverLetterAgent,
  type CoverLetter,
} from "../../../lib/api/coverLetters";
import type { Job } from "../../../lib/api/jobs";

export default function CoverLettersPage() {
  const [letters, setLetters] = useState<CoverLetter[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [letterList, jobList] = await Promise.all([fetchCoverLetters(), apiRequest<Job[]>("/jobs")]);
      setLetters(letterList);
      setJobs(jobList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cover letters");
      setLetters([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const generate = async () => {
    if (!selectedJob) return;
    setRunning(true);
    try {
      await runCoverLetterAgent(selectedJob);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cover letter run failed");
    } finally {
      setRunning(false);
    }
  };

  const jobFor = (jobId: string) => jobs.find((j) => j.id === jobId);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Cover Letters</h1>
          <p className="text-sm text-aether-muted">
            Drafts pass a fabrication guard — every claim traces to your resume.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedJob}
            onChange={(e) => setSelectedJob(e.target.value)}
            className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm"
            data-testid="cover-letter-job-select"
          >
            <option value="" className="bg-black">
              Select a job…
            </option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id} className="bg-black">
                {job.title} · {job.company}
              </option>
            ))}
          </select>
          <button
            type="button"
            data-testid="run-cover-letter-btn"
            onClick={() => void generate()}
            disabled={running || !selectedJob}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {running ? "Drafting..." : "Generate Draft"}
          </button>
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {letters === null ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass h-28 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : letters.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="cover-letters-empty-state">
          <p className="text-lg font-semibold">No cover letters yet</p>
          <p className="mt-1 text-sm text-aether-muted">
            Select a job and generate a draft — it will land in the approval queue.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {letters.map((letter) => {
            const job = jobFor(letter.jobId);
            const isOpen = expanded === letter.id;
            return (
              <article
                key={letter.id}
                data-testid="cover-letter-card"
                className="glass rounded-2xl border border-white/10 p-5"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">
                      {job ? `${job.title} · ${job.company}` : `Job ${letter.jobId.slice(0, 8)}`}
                    </h2>
                    <p className="mt-0.5 text-xs text-aether-muted-dim">
                      {letter.status} · {new Date(letter.createdAt).toLocaleString()}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setExpanded(isOpen ? null : letter.id)}
                    className="rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30"
                  >
                    {isOpen ? "Collapse" : "Read draft"}
                  </button>
                </div>
                {isOpen && letter.coverLetter ? (
                  <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-white/10 bg-white/5 p-4 font-sans text-sm text-aether-muted">
                    {letter.coverLetter}
                  </pre>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
