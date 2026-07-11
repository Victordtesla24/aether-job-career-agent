"use client";

/**
 * Cover Letter Studio (wireframe cover-letter-studio.html) — evidence-guarded
 * drafts backed by GET /cover-letters + POST /agents/cover-letter/run, with a
 * real intelligence rail (GET /cover-letters/{id}/insights): evidence trace,
 * Voice DNA, JD keyword coverage, versions, refine and PDF export.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ActionsPanel } from "../../../components/cover-letters/ActionsPanel";
import { EvidenceTracePanel } from "../../../components/cover-letters/EvidenceTracePanel";
import { KeywordCoveragePanel } from "../../../components/cover-letters/KeywordCoveragePanel";
import { VersionsPanel } from "../../../components/cover-letters/VersionsPanel";
import { VoiceDnaPanel } from "../../../components/cover-letters/VoiceDnaPanel";
import {
  downloadCoverLetterPdf,
  fetchLetterInsights,
  refineCoverLetter,
  type LetterInsights,
} from "../../../components/cover-letters/api";
import {
  highlightSegments,
  parseApiDate,
  wordCount,
} from "../../../components/cover-letters/insights";
import { apiRequest } from "../../../lib/api/client";
import {
  fetchCoverLetters,
  runCoverLetterAgent,
  type CoverLetter,
} from "../../../lib/api/coverLetters";
import type { Job } from "../../../lib/api/jobs";

const SEGMENT_CLASS = {
  plain: "",
  grounded: "rounded bg-[#34D399]/25 px-0.5",
  ungrounded: "rounded bg-[#FBBF24]/30 px-0.5",
} as const;

export default function CoverLettersPage() {
  const [letters, setLetters] = useState<CoverLetter[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [insights, setInsights] = useState<LetterInsights | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [tone, setTone] = useState(60);
  const [formality, setFormality] = useState(55);
  const [running, setRunning] = useState(false);
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [refining, setRefining] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (selectId?: string) => {
    try {
      const [letterList, jobList] = await Promise.all([
        fetchCoverLetters(),
        apiRequest<Job[]>("/jobs"),
      ]);
      setLetters(letterList);
      // Studio default: newest draft opens expanded (wireframe shows the editor).
      setExpanded((prev) => selectId ?? prev ?? letterList[0]?.id ?? null);
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

  // The rail is driven by the selected (expanded) letter's insights.
  useEffect(() => {
    if (!expanded) {
      setInsights(null);
      return;
    }
    let cancelled = false;
    setInsightsLoading(true);
    fetchLetterInsights(expanded)
      .then((data) => {
        if (!cancelled) setInsights(data);
      })
      .catch((e) => {
        if (!cancelled) {
          setInsights(null);
          setError(e instanceof Error ? e.message : "Failed to load letter insights");
        }
      })
      .finally(() => {
        if (!cancelled) setInsightsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [expanded]);

  const generate = async () => {
    if (!selectedJob) return;
    setRunning(true);
    try {
      const result = await runCoverLetterAgent(selectedJob);
      await load(result.cover_letter_id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cover letter run failed");
    } finally {
      setRunning(false);
    }
  };

  // Full agent re-run for a letter's job (per-card Regenerate).
  const regenerate = async (letter: CoverLetter) => {
    setRegenerating(letter.id);
    try {
      const result = await runCoverLetterAgent(letter.jobId);
      await load(result.cover_letter_id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regenerate failed");
    } finally {
      setRegenerating(null);
    }
  };

  // Slider-steered redraft of the selected letter (rail Regenerate).
  const regenerateSelected = async () => {
    if (!selected) return;
    setRegenerating(selected.id);
    try {
      const result = await refineCoverLetter(selected.id, { tone, formality });
      await load(result.cover_letter_id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regenerate failed");
    } finally {
      setRegenerating(null);
    }
  };

  const requestChanges = async (instructions: string): Promise<boolean> => {
    if (!selected) return false;
    setRefining(true);
    try {
      const result = await refineCoverLetter(selected.id, { instructions, tone, formality });
      await load(result.cover_letter_id);
      setError(null);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Change request failed");
      return false;
    } finally {
      setRefining(false);
    }
  };

  const exportPdf = async () => {
    if (!selected) return;
    setExporting(true);
    try {
      const job = jobFor(selected.jobId);
      const hint = (job?.company ?? "letter").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      await downloadCoverLetterPdf(selected.id, hint);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const jobFor = (jobId: string) => jobs.find((j) => j.id === jobId);
  const selected = letters?.find((l) => l.id === expanded) ?? null;
  const selectedInsights = insights && insights.letterId === expanded ? insights : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[11px] text-aether-muted-dim">
            <Link href="/dashboard/resume" className="transition hover:text-white">
              Resume Studio
            </Link>
            <i className="fa-solid fa-chevron-right text-[8px]" aria-hidden="true" />
            <span className="text-aether-muted">Cover Letter</span>
          </nav>
          <h1 className="text-2xl font-bold">Cover Letter Studio</h1>
          <p className="text-sm text-aether-muted">
            Drafts pass a fabrication guard — every claim traces to your resume.
          </p>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-4 sm:w-auto">
          <div className="flex items-center gap-2" data-testid="voice-authenticity-indicator">
            <i className="fa-solid fa-shield-halved text-aether-green" aria-hidden="true" />
            <div className="leading-tight">
              <div className="text-[11px] text-aether-muted-dim">Voice DNA</div>
              <div className="mono text-xs font-medium text-aether-green">
                {selectedInsights ? `${selectedInsights.voice.authenticity}% authentic` : "—"}
              </div>
            </div>
          </div>
          <div
            className="flex items-center gap-2 border-l border-white/10 pl-4"
            data-testid="ai-detection-indicator"
          >
            <i className="fa-solid fa-robot text-aether-violet" aria-hidden="true" />
            <div className="leading-tight">
              <div className="text-[11px] text-aether-muted-dim">AI Detection</div>
              <div className="mono text-xs font-medium text-aether-green">
                {selectedInsights
                  ? `${selectedInsights.voice.aiDetectionRisk}% · ${selectedInsights.voice.aiDetectionLabel}`
                  : "—"}
              </div>
            </div>
          </div>
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              className="glass min-h-[44px] w-full min-w-0 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm sm:w-auto"
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
              className="min-h-[44px] rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {running ? "Drafting..." : "Generate Draft"}
            </button>
          </div>
        </div>
      </header>

      {error ? (
        <p
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
        >
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
        <div
          className="glass rounded-2xl border border-white/10 p-10 text-center"
          data-testid="cover-letters-empty-state"
        >
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
              const jobLabel = job
                ? `${job.title} · ${job.company}`
                : `Job ${letter.jobId.slice(0, 8)}`;
              const segments =
                isOpen && letter.coverLetter
                  ? highlightSegments(letter.coverLetter, selectedInsights?.evidence ?? [])
                  : [];
              return (
                <article
                  key={letter.id}
                  data-testid="cover-letter-card"
                  className="glass rounded-2xl border border-white/10 p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">{jobLabel}</h2>
                      <p className="mt-0.5 text-xs text-aether-muted-dim">
                        {letter.status} · {parseApiDate(letter.createdAt).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        data-testid="regenerate-letter-btn"
                        aria-label={`Regenerate letter for ${jobLabel}`}
                        onClick={() => void regenerate(letter)}
                        disabled={regenerating !== null}
                        className="min-h-[44px] rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30 disabled:opacity-50"
                      >
                        {regenerating === letter.id ? "Redrafting…" : "Regenerate"}
                      </button>
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? "Collapse" : "Read"} draft for ${jobLabel}`}
                        onClick={() => setExpanded(isOpen ? null : letter.id)}
                        className="min-h-[44px] rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30"
                      >
                        {isOpen ? "Collapse" : "Read draft"}
                      </button>
                    </div>
                  </div>
                  {isOpen && letter.coverLetter ? (
                    <div className="mt-4" data-testid="letter-preview">
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <i
                            className="fa-solid fa-file-lines text-sm text-aether-coral"
                            aria-hidden="true"
                          />
                          <h3 className="text-sm font-semibold">Cover Letter — Draft</h3>
                          <span className="rounded-md border border-aether-indigo/25 bg-aether-indigo/15 px-2 py-0.5 text-[10px] text-aether-violet">
                            AI-generated · editable
                          </span>
                        </div>
                        <span className="mono text-[11px] text-aether-muted-dim" data-testid="word-count">
                          {selectedInsights?.wordCount ?? wordCount(letter.coverLetter)} words · 1
                          page
                        </span>
                      </div>
                      <div className="mx-auto max-w-[720px] whitespace-pre-line rounded-xl bg-[#F7F7FB] p-8 text-sm leading-relaxed text-[#1A1A24] shadow-lg">
                        {segments.map((seg, i) =>
                          seg.kind === "plain" ? (
                            <span key={i}>{seg.text}</span>
                          ) : (
                            <mark
                              key={i}
                              data-testid={`highlight-${seg.kind}`}
                              className={`${SEGMENT_CLASS[seg.kind]} text-[#1A1A24]`}
                            >
                              {seg.text}
                            </mark>
                          ),
                        )}
                      </div>
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>

          {/* Studio control panel (wireframe cl06–cl16) — driven by the selected letter */}
          <aside className="space-y-4">
            <EvidenceTracePanel
              evidence={selectedInsights?.evidence ?? null}
              loading={insightsLoading}
            />
            <VoiceDnaPanel
              tone={tone}
              formality={formality}
              onToneChange={setTone}
              onFormalityChange={setFormality}
            />
            <KeywordCoveragePanel
              keywords={selectedInsights?.keywords ?? null}
              loading={insightsLoading}
            />
            <ActionsPanel
              disabled={!selected}
              regenerating={regenerating !== null}
              refining={refining}
              exporting={exporting}
              emailHref={selected ? `/dashboard/email?letter=${selected.id}` : "/dashboard/email"}
              onRegenerate={() => void regenerateSelected()}
              onRequestChanges={requestChanges}
              onExport={() => void exportPdf()}
            />
            <VersionsPanel
              versions={selectedInsights?.versions ?? null}
              selectedId={expanded}
              loading={insightsLoading}
              onSelect={(id) => setExpanded(id)}
            />
          </aside>
        </div>
      )}
    </div>
  );
}
