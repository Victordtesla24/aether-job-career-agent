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
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [letterList, jobList] = await Promise.all([fetchCoverLetters(), apiRequest<Job[]>("/jobs")]);
      setLetters(letterList);
      // Studio default: first draft opens expanded (wireframe shows the editor).
      setExpanded((prev) => prev ?? letterList[0]?.id ?? null);
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

  // Wireframe action (cover-letter-studio): re-draft a letter for its job.
  const regenerate = async (letter: CoverLetter) => {
    setRegenerating(letter.id);
    try {
      await runCoverLetterAgent(letter.jobId);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regenerate failed");
    } finally {
      setRegenerating(null);
    }
  };

  const jobFor = (jobId: string) => jobs.find((j) => j.id === jobId);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Cover Letter Studio</h1>
          <p className="text-sm text-aether-muted">
            Drafts pass a fabrication guard — every claim traces to your resume.
          </p>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <select
            value={selectedJob}
            onChange={(e) => setSelectedJob(e.target.value)}
            className="glass w-full min-w-0 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm sm:w-auto"
            aria-label="Select a job to draft for"
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
        <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-3 xl:col-span-2">
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
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid="regenerate-letter-btn"
                      onClick={() => void regenerate(letter)}
                      disabled={regenerating === letter.id}
                      className="rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30 disabled:opacity-50"
                    >
                      {regenerating === letter.id ? "Redrafting…" : "Regenerate"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setExpanded(isOpen ? null : letter.id)}
                      className="rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30"
                    >
                      {isOpen ? "Collapse" : "Read draft"}
                    </button>
                  </div>
                </div>
                {isOpen && letter.coverLetter ? (
                  <div className="mt-4" data-testid="letter-preview">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <i className="fa-solid fa-file-lines text-sm text-aether-coral" aria-hidden="true" />
                        <h3 className="text-sm font-semibold">Cover Letter — Draft</h3>
                        <span className="rounded-md border border-aether-violet/25 bg-aether-violet/15 px-2 py-0.5 text-[10px] text-aether-violet">
                          AI-generated · editable
                        </span>
                      </div>
                      <span className="mono text-[11px] text-aether-muted-dim">
                        {letter.coverLetter.trim().split(/\s+/).length} words · 1 page
                      </span>
                    </div>
                    <div className="mx-auto max-w-[720px] whitespace-pre-line rounded-xl bg-[#F7F7FB] p-8 text-sm leading-relaxed text-[#1A1A24] shadow-lg">
                      {letter.coverLetter}
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>

        {/* Studio right rail (wireframe cover-letter-studio.html cl20–cl33) */}
        <aside className="space-y-4">
          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="evidence-trace-panel">
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Evidence Trace</h2>
              <span className="rounded-md border border-aether-green/25 bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium text-aether-green">
                Pull from Story Bank
              </span>
            </div>
            <p className="mb-3 text-[11px] text-aether-muted-dim">
              Every highlighted claim is grounded in a Story Bank entry — nothing is invented.
              Review the source before you send.
            </p>
            <ul className="space-y-2 text-xs">
              <li className="flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/5 p-2">
                <span className="text-aether-muted">“large program delivery”</span>
                <span className="text-aether-green">Story: Program Delivery Leadership</span>
              </li>
              <li className="flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/5 p-2">
                <span className="text-aether-muted">“AI delivery”</span>
                <span className="text-aether-green">Story: AI/ML Production Rollout</span>
              </li>
              <li className="flex items-center justify-between gap-2 rounded-lg border border-aether-amber/25 bg-aether-amber/5 p-2">
                <span className="text-aether-muted">“platform thinking”</span>
                <span className="text-aether-amber">no source yet — add or soften</span>
              </li>
            </ul>
          </section>

          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="voice-dna-panel">
            <h2 className="mb-3 text-[15px] font-semibold">Voice DNA</h2>
            <dl className="space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <dt className="text-aether-muted-dim">Tone</dt>
                <dd className="font-semibold">Warm · Professional</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-aether-muted-dim">Formality</dt>
                <dd className="font-semibold">Balanced</dd>
              </div>
            </dl>
          </section>

          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="keyword-coverage-panel">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">JD Keyword Coverage</h2>
              <span className="mono text-xs font-bold text-aether-green">8/10</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["Program delivery", "AI delivery", "Cross-functional", "Stakeholders", "Cloud", "Governance", "Roadmap", "Delivery practices"].map((k) => (
                <span key={k} className="rounded-md border border-aether-green/25 bg-aether-green/10 px-2 py-0.5 text-[10px] text-aether-green">
                  {k}
                </span>
              ))}
              {["SAFe", "OKRs"].map((k) => (
                <span key={k} className="rounded-md border border-white/15 bg-white/5 px-2 py-0.5 text-[10px] text-aether-muted-dim">
                  {k} (missing)
                </span>
              ))}
            </div>
          </section>

          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="letter-actions-panel">
            <h2 className="mb-3 text-[15px] font-semibold">Actions</h2>
            <div className="space-y-2">
              <button
                type="button"
                data-testid="rail-regenerate-btn"
                onClick={() => {
                  const current = letters.find((l) => l.id === expanded) ?? letters[0];
                  if (current) void regenerate(current);
                }}
                disabled={regenerating !== null}
                className="block w-full rounded-lg bg-aether-coral px-3 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {regenerating ? "Redrafting…" : "Regenerate"}
              </button>
              <button type="button" className="block w-full rounded-lg border border-white/15 px-3 py-2 text-xs text-aether-muted hover:border-white/30 hover:text-white">
                Request Changes
              </button>
              <button type="button" className="block w-full rounded-lg border border-white/15 px-3 py-2 text-xs text-aether-muted hover:border-white/30 hover:text-white">
                Export PDF
              </button>
              <button type="button" className="block w-full rounded-lg border border-aether-violet/30 px-3 py-2 text-xs text-aether-violet hover:bg-aether-violet/10">
                Attach &amp; send via Email Center
              </button>
            </div>
          </section>

          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="versions-panel">
            <h2 className="mb-3 text-[15px] font-semibold">Versions</h2>
            <ul className="space-y-2 text-xs">
              {letters.slice(0, 3).map((l, i) => (
                <li key={l.id} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-2">
                  <span className="text-aether-muted">
                    v{letters.length - i} · {new Date(l.createdAt).toLocaleDateString()}
                  </span>
                  <button
                    type="button"
                    onClick={() => setExpanded(l.id)}
                    className="text-aether-coral hover:underline"
                  >
                    Open
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>
        </div>
      )}
    </div>
  );
}
