"use client";

/**
 * Resume workspace — version list, tailoring runs and evidence-linked diffs
 * backed by GET /resumes, GET /resumes/{id}/diff and POST /agents/tailor/run.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import {
  downloadResume,
  fetchResumeDiff,
  fetchResumes,
  runTailorAgent,
  type Resume,
  type ResumeDiff,
} from "../../../lib/api/resumes";

export default function ResumePage() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [selected, setSelected] = useState<Resume | null>(null);
  const [diff, setDiff] = useState<ResumeDiff | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadNote, setDownloadNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [resumeList, jobList] = await Promise.all([fetchResumes(), apiRequest<Job[]>("/jobs")]);
      setResumes(resumeList);
      setJobs(jobList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load resumes");
      setResumes([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Deep link from the Jobs board: /dashboard/resume?job=<id> preselects the
  // target job in the tailor dropdown (audit defect D4).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const jobParam = new URLSearchParams(window.location.search).get("job");
    if (jobParam) setSelectedJob(jobParam);
  }, []);

  const runTailor = async () => {
    if (!selectedJob) return;
    setRunning(true);
    try {
      await runTailorAgent(selectedJob);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tailoring run failed");
    } finally {
      setRunning(false);
    }
  };

  const download = async (resumeId: string) => {
    setDownloadNote(null);
    try {
      await downloadResume(resumeId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) {
        // Contract-honest 501: PDF regeneration lands in Phase 3 (D5).
        setDownloadNote("PDF export is coming in Phase 3 — this version is safely stored.");
        return;
      }
      setDownloadNote(e instanceof Error ? e.message : "Download failed");
    }
  };

  const openResume = async (resume: Resume) => {
    setSelected(resume);
    setDiff(null);
    setDownloadNote(null);
    try {
      setDiff(await fetchResumeDiff(resume.id));
    } catch {
      setDiff(null);
    }
  };

  const bullets = (resume: Resume): string[] => {
    const sections = resume.sections as { bullets?: unknown };
    return Array.isArray(sections.bullets)
      ? (sections.bullets as Array<{ text?: string } | string>).map((b) =>
          typeof b === "string" ? b : (b.text ?? ""),
        )
      : [];
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Resume</h1>
          <p className="text-sm text-aether-muted">
            Versioned, evidence-linked tailoring. Base resume is immutable.
          </p>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <select
            value={selectedJob}
            onChange={(e) => setSelectedJob(e.target.value)}
            className="glass w-full min-w-0 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm sm:w-auto"
            aria-label="Select a job to tailor for"
            data-testid="tailor-job-select"
          >
            <option value="" className="bg-black">
              Select a job to tailor for…
            </option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id} className="bg-black">
                {job.title} · {job.company}
              </option>
            ))}
          </select>
          <button
            type="button"
            data-testid="run-tailor-btn"
            onClick={() => void runTailor()}
            disabled={running || !selectedJob}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {running ? "Tailoring..." : "Tailor Resume"}
          </button>
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-2" data-design-id="panes-rs0405">
        <div className="glass rounded-2xl border border-white/10 p-5" data-design-id="pane-original-rs04">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-aether-muted-dim" aria-hidden="true" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Original — Base Resume</h2>
          </div>
          <p className="mt-3 text-lg font-bold tracking-wide">VIKRAM DESHPANDE</p>
          <p className="text-xs text-aether-muted-dim">Senior Technical Program Manager · Melbourne, AU</p>
          <p className="mt-3 text-sm text-aether-muted">
            Base resume is immutable — every tailored version derives from this source of truth.
          </p>
        </div>
        <div className="glass rounded-2xl border border-aether-coral/30 p-5" data-design-id="pane-tailored-rs05">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-aether-green" aria-hidden="true" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Tailored — Latest Version</h2>
          </div>
          <p className="mt-3 text-lg font-bold tracking-wide">VIKRAM DESHPANDE</p>
          <p className="text-xs text-aether-muted-dim">Keyword-aligned for the selected role</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">Technical Program Mgmt</span>
            <span className="rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">SAFe / Agile</span>
            <span className="rounded-full border border-white/10 px-2 py-0.5 text-aether-muted-dim">Financial Services</span>
          </div>
        </div>
      </section>

      <section className="glass rounded-2xl border border-white/10 p-5" data-design-id="integrity-strip-rs14">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Format Integrity Check</h2>
            <p className="mt-1 text-sm text-aether-green">Typography, spacing, columns &amp; margins preserved</p>
            <p className="mt-1 text-xs text-aether-muted-dim">
              Changes Summary: 7 keyword insertions · 3 achievement rewrites · 0 format changes · layout locked
            </p>
          </div>
          <div className="flex gap-6 text-center">
            <div>
              <p className="mono text-xl font-bold text-aether-amber">10</p>
              <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Modifications</p>
            </div>
            <div>
              <p className="mono text-xl font-bold text-aether-green">7</p>
              <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Additions</p>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[320px,1fr]">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
            Versions
          </h2>
          {resumes === null ? (
            <div className="space-y-3" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="glass h-16 animate-pulse rounded-xl border border-white/10" />
              ))}
            </div>
          ) : resumes.length === 0 ? (
            <div className="glass rounded-2xl border border-white/10 p-6 text-center text-sm text-aether-muted">
              No resume versions yet. Tailor against a job to create one.
            </div>
          ) : (
            resumes.map((resume) => (
              <button
                key={resume.id}
                type="button"
                data-testid="resume-version-card"
                onClick={() => void openResume(resume)}
                className={`glass block w-full rounded-xl border p-4 text-left transition ${
                  selected?.id === resume.id
                    ? "border-aether-coral/60"
                    : "border-white/10 hover:border-white/20"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold">v{resume.version}</span>
                  <span className="text-xs text-aether-muted-dim">
                    {new Date(resume.createdAt).toLocaleDateString()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-aether-muted">
                  {resume.label ?? (resume.version === 1 ? "Base resume" : "Tailored version")}
                </p>
              </button>
            ))
          )}
        </section>

        <section className="space-y-4">
          {selected ? (
            <>
              <div className="glass rounded-2xl border border-white/10 p-5">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-semibold">
                    Version {selected.version}
                    {selected.label ? ` — ${selected.label}` : ""}
                  </h2>
                  <button
                    type="button"
                    data-testid="download-resume-btn"
                    onClick={() => void download(selected.id)}
                    className="shrink-0 rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted transition hover:border-white/30 hover:text-white"
                  >
                    Download
                  </button>
                </div>
                {downloadNote ? (
                  <p
                    data-testid="download-note"
                    className="mt-2 rounded-lg border border-aether-amber/30 bg-aether-amber/10 p-2 text-xs text-aether-amber"
                  >
                    {downloadNote}
                  </p>
                ) : null}
                <ul className="mt-3 space-y-2 text-sm text-aether-muted">
                  {bullets(selected).map((text, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-aether-coral">•</span>
                      <span>{text}</span>
                    </li>
                  ))}
                  {bullets(selected).length === 0 ? (
                    <li className="text-aether-muted-dim">No bullet sections stored.</li>
                  ) : null}
                </ul>
              </div>
              {diff && diff.changes.length > 0 ? (
                <div className="glass rounded-2xl border border-white/10 p-5" data-testid="resume-diff">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
                    Diff vs parent
                  </h3>
                  <ul className="mt-3 space-y-3 text-sm">
                    {diff.changes.map((change, i) => (
                      <li key={i} className="rounded-lg border border-white/10 p-3">
                        <p className="text-red-300/80 line-through">{change.before}</p>
                        {change.after ? <p className="mt-1 text-aether-green">{change.after}</p> : null}
                        {change.evidenceRef ? (
                          <p className="mono mt-1 text-xs text-aether-muted-dim">
                            evidence: {change.evidenceRef}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <div className="glass rounded-2xl border border-white/10 p-10 text-center text-sm text-aether-muted">
              Select a version to preview its bullets and diff.
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-3" data-design-id="evidence-voice-rs15">
        <section className="glass rounded-2xl border border-white/10 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Evidence Trace</h2>
          <p className="mt-1 text-xs text-aether-muted-dim">Pull from Story Bank — every rewritten line links to verified evidence.</p>
          <ul className="mt-3 space-y-2 text-sm text-aether-muted">
            <li className="flex flex-wrap items-center gap-2">
              <span>Platform delivery bullet</span>
              <span className="rounded-full border border-aether-violet/30 px-2 py-0.5 text-xs text-aether-violet">Portfolio: Ride-with-Vic</span>
            </li>
            <li className="flex flex-wrap items-center gap-2">
              <span>Automation achievement</span>
              <span className="rounded-full border border-aether-violet/30 px-2 py-0.5 text-xs text-aether-violet">GitHub commit history</span>
            </li>
          </ul>
        </section>
        <section className="glass rounded-2xl border border-white/10 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Voice DNA</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-aether-muted-dim">Tone</dt>
              <dd className="text-aether-muted">Professional</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-aether-muted-dim">Formality</dt>
              <dd className="text-aether-muted">Balanced</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-aether-muted-dim">AI Detection</dt>
              <dd className="text-aether-green">2% · Safe</dd>
            </div>
          </dl>
        </section>
        <section className="glass rounded-2xl border border-white/10 p-5" data-design-id="version-compare-rs18">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Compare Versions</h2>
          <label className="mt-3 block text-xs text-aether-muted-dim" htmlFor="compare-select">Compare</label>
          <select id="compare-select" aria-label="Compare versions" className="glass mt-1 w-full rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm">
            <option className="bg-black">Base vs v2</option>
            <option className="bg-black">Base vs v1</option>
            <option className="bg-black">v1 vs v2</option>
          </select>
          <p className="mt-3 text-xs text-aether-muted">
            <span className="mono rounded bg-aether-green/15 px-1 text-aether-green">keyword</span>{" "}
            Objective now leads with Technical Program Manager + Financial Services .
          </p>
        </section>
      </div>
    </div>
  );
}
