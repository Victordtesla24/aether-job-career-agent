"use client";

/**
 * Resume workspace — version list, tailoring runs and evidence-linked diffs
 * backed by GET /resumes, GET /resumes/{id}/diff and POST /agents/tailor/run.
 */
import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import {
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

  const openResume = async (resume: Resume) => {
    setSelected(resume);
    setDiff(null);
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
        <div className="flex items-center gap-2">
          <select
            value={selectedJob}
            onChange={(e) => setSelectedJob(e.target.value)}
            className="glass rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm"
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
                <h2 className="font-semibold">
                  Version {selected.version}
                  {selected.label ? ` — ${selected.label}` : ""}
                </h2>
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
    </div>
  );
}
