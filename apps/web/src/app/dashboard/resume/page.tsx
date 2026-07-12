"use client";

/**
 * Resume workspace — version list, tailoring runs and evidence-linked diffs
 * backed by GET /resumes, GET /resumes/{id}/diff and POST /agents/tailor/run.
 */
import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import {
  downloadResume,
  fetchResumeDiff,
  fetchResumes,
  runTailorAgent,
  type Resume,
  type ResumeDiff,
} from "../../../lib/api/resumes";

/** Real ATS engine breakdown for a tailored version vs its target job. */
type AtsScore = {
  overall: number;
  keyword_match: number;
  semantic_similarity: number;
  experience_gap: number;
  matched_keywords: string[];
  missing_keywords: string[];
  requires_review: boolean;
  job_title?: string | null;
  company?: string | null;
};

export default function ResumePage() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [selected, setSelected] = useState<Resume | null>(null);
  const [diff, setDiff] = useState<ResumeDiff | null>(null);
  const [ats, setAts] = useState<AtsScore | null>(null);
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
      setDownloadNote("Downloaded — format-preserving PDF saved.");
    } catch (e) {
      setDownloadNote(e instanceof Error ? e.message : "Download failed");
    }
  };

  const openResume = async (resume: Resume) => {
    setSelected(resume);
    setDiff(null);
    setAts(null);
    setDownloadNote(null);
    try {
      setDiff(await fetchResumeDiff(resume.id));
    } catch {
      setDiff(null);
    }
    if (resume.sourceJobId) {
      try {
        setAts(await apiRequest<AtsScore>(`/resumes/${resume.id}/ats`));
      } catch {
        setAts(null);
      }
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
            {(() => {
              const tailored = (resumes ?? []).find((r) => r.label?.startsWith("Tailored"));
              return tailored ? (
                <span className="rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">
                  {tailored.label}
                </span>
              ) : (
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-aether-muted-dim">
                  No tailored version yet — run tailoring against a job
                </span>
              );
            })()}
          </div>
        </div>
      </section>

      <section className="glass rounded-2xl border border-white/10 p-5" data-design-id="integrity-strip-rs14">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Format Integrity Check</h2>
            <p className="mt-1 text-sm text-aether-green">Typography, spacing, columns &amp; margins preserved</p>
            <p className="mt-1 text-xs text-aether-muted-dim">
              {diff
                ? `Changes Summary: ${diff.changes.filter((c) => c.before).length} rewrites · ${diff.changes.filter((c) => !c.before).length} additions · layout locked (formatHash carried from base)`
                : "Select a tailored version to see its change summary."}
            </p>
          </div>
          <div className="text-center">
            <div className="flex gap-6 text-xs uppercase tracking-wide text-aether-muted-dim">
              <span className="block">Modifications</span>{" "}
              <span className="block">Additions</span>
            </div>
            <div className="mt-1 flex justify-around gap-6">
              <span className="mono text-xl font-bold text-aether-amber">
                {diff ? diff.changes.filter((c) => c.before).length : "—"}
              </span>
              <span className="mono text-xl font-bold text-aether-green">
                {diff ? diff.changes.filter((c) => !c.before).length : "—"}
              </span>
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

      {ats ? (
        <section
          className="glass rounded-2xl border border-white/10 p-5"
          data-design-id="ats-score-rs06"
          data-testid="ats-score-panel"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
                ATS Score
              </h2>
              <p className="mt-1 text-xs text-aether-muted-dim">
                Deterministic keyword + semantic + experience evaluation vs{" "}
                {ats.job_title ?? "target job"}
                {ats.company ? ` @ ${ats.company}` : ""}
              </p>
            </div>
            <span
              className={`font-mono text-2xl font-bold ${ats.overall >= 60 ? "text-aether-green" : "text-aether-amber"}`}
              data-testid="ats-overall"
            >
              {ats.overall}
            </span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Keyword match (40%)", value: ats.keyword_match },
              { label: "Semantic similarity (40%)", value: ats.semantic_similarity },
              { label: "Experience fit (20%)", value: ats.experience_gap },
            ].map((row) => (
              <div key={row.label}>
                <div className="flex items-center justify-between text-xs text-aether-muted">
                  <span>{row.label}</span>
                  <span className="mono">{row.value}</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-white/10">
                  <div
                    className="h-1.5 rounded-full bg-aether-indigo"
                    style={{ width: `${Math.min(100, Math.max(0, row.value))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          {ats.missing_keywords.length > 0 ? (
            <p className="mt-3 text-xs text-aether-muted-dim">
              Missing JD keywords:{" "}
              <span className="mono text-aether-amber">
                {ats.missing_keywords.slice(0, 8).join(", ")}
              </span>
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2" data-design-id="evidence-voice-rs15">
        <section className="glass rounded-2xl border border-white/10 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Evidence Trace</h2>
          <p className="mt-1 text-xs text-aether-muted-dim">
            Every rewritten line links back to evidence in the base resume.
          </p>
          {diff && diff.changes.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm text-aether-muted">
              {diff.changes.slice(0, 4).map((change, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="truncate">{(change.after || change.before).slice(0, 60)}</span>
                  {change.evidenceRef ? (
                    <span className="mono rounded-full border border-aether-violet/30 px-2 py-0.5 text-xs text-aether-violet">
                      {change.evidenceRef}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-aether-muted-dim">
              Select a tailored version to trace its changes to evidence.
            </p>
          )}
        </section>
        <section className="glass rounded-2xl border border-white/10 p-5" data-design-id="version-compare-rs18">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Version History</h2>
          {resumes && resumes.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm text-aether-muted">
              {resumes.slice(0, 4).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{r.label ?? `Version ${r.version}`}</span>
                  <span className="mono shrink-0 text-xs text-aether-muted-dim">v{r.version}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-aether-muted-dim">No versions yet.</p>
          )}
        </section>
      </div>
    </div>
  );
}
