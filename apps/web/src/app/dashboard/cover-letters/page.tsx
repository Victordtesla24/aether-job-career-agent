"use client";

/**
 * Cover Letter Studio (wireframe cover-letter-studio.html) — evidence-guarded
 * drafts backed by GET /cover-letters + POST /agents/cover-letter/run, with a
 * real intelligence rail (GET /cover-letters/{id}/insights): evidence trace,
 * Voice DNA, JD keyword coverage, versions, refine and PDF export.
 *
 * S-UI B3 — MASTER/DETAIL (presentation only).
 * -------------------------------------------
 * Measured on production 2026-08-14 (b3/before/before-notes.json): this screen
 * rendered 639 letter cards in one column and the document was **66,846 px**
 * tall at 1600 and **112,046 px** at 390 — the worst D-ε violation left in the
 * product after Jobs was fixed in B2. The cause was structural: every letter
 * got a full card, and the open one additionally rendered a full-page letter
 * preview inside that same flow.
 *
 * The fix is a layout, not a behaviour: the letters become a scroll-contained
 * rail (filterable, paged), and the ONE selected letter owns a reading column
 * at `max-w-[70ch]` with the insight panels in a single right rail (§5.7).
 * Same fetches, same order, same `expanded` semantics, same honesty strings.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ActionsPanel } from "../../../components/cover-letters/ActionsPanel";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import { EvidenceTracePanel } from "../../../components/cover-letters/EvidenceTracePanel";
import { KeywordCoveragePanel } from "../../../components/cover-letters/KeywordCoveragePanel";
import { RejectionPanel } from "../../../components/cover-letters/RejectionPanel";
import { VersionsPanel } from "../../../components/cover-letters/VersionsPanel";
import { LetterQualityPanel } from "../../../components/cover-letters/LetterQualityPanel";
import { VoiceDnaPanel } from "../../../components/cover-letters/VoiceDnaPanel";
import PageHeader from "../../../components/shell/PageHeader";
import { button, chip, listCard } from "../../../components/ui/recipes";
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
import {
  parseCoverLetterRejection,
  type CoverLetterRejection,
} from "../../../components/cover-letters/rejection";
import { apiRequest } from "../../../lib/api/client";
import {
  fetchCoverLetters,
  runCoverLetterAgent,
  type CoverLetter,
  type CoverLetterRunResult,
} from "../../../lib/api/coverLetters";
import type { Job } from "../../../lib/api/jobs";

const SEGMENT_CLASS = {
  plain: "",
  grounded: "rounded bg-[#34D399]/25 px-0.5",
  ungrounded: "rounded bg-[#FBBF24]/30 px-0.5",
} as const;

/**
 * Cover-letter brand palette — mirrors the uploaded/tailored resume format
 * (resume_pdf.py branded template) so the cover letter reads as the same
 * visual identity across the product.
 *   peach panel  #FCD9CF  — letterhead band behind the candidate's name
 *   coral accent #F4715C  — 3pt rule at the panel foot
 *   coral wash   #FF6B35  — changed-line highlight (matches resume swap wash)
 *   ink          #2B2B2B  — body / heading text
 *   muted ink    #2B2B2B  — bold lead-in weight
 *   muted grey   #4D4D4D  — sub-text / contact lines
 */
const CL_PANEL = "#FCD9CF";
const CL_ACCENT = "#F4715C";
const CL_INK = "#2B2B2B";
const CL_MUTED = "#4D4D4D";

/** How many letter rows the rail opens with before "Show more". */
const LETTERS_PAGE_SIZE = 12;

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
  /** Presentation-only rail controls over the ALREADY-fetched list. */
  const [letterFilter, setLetterFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(LETTERS_PAGE_SIZE);
  // 422 fabrication/structural rejections get their own dedicated panel
  // (GAP-E4) instead of the generic top-of-page alert; `retry` re-runs
  // whichever action produced the rejection.
  const [rejection, setRejection] = useState<{
    model: CoverLetterRejection;
    retry: () => void;
  } | null>(null);
  // AUD-COV-2: the backend's low-fit disclosure for the letter this screen
  // just generated on the user's explicit request. Autopilot refuses to
  // auto-generate for a job below her own matchThreshold; when SHE asks, the
  // letter is written and this sentence must travel with it, because the
  // letter's own opener reads as a confident match. Null for every letter
  // that clears her bar. Bound to the letter id it describes so it is shown
  // ONLY while that letter is the open one — a warning about letter A hanging
  // over letter B would be its own dishonesty.
  const [fitDisclosure, setFitDisclosure] = useState<{
    letterId: string;
    text: string;
  } | null>(null);

  /** Route a caught agent-run/refine error to the rejection panel or the generic alert. */
  const handleAgentError = (e: unknown, fallbackMessage: string, retry: () => void) => {
    const model = parseCoverLetterRejection(e);
    if (model) {
      setRejection({ model, retry });
      setError(null);
    } else {
      setRejection(null);
      setError(e instanceof Error ? e.message : fallbackMessage);
    }
  };

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

  /**
   * Apply a completed `/agents/cover-letter/run` result — either a drafted
   * letter or an honest DEGRADE. The async job completes successfully either
   * way (never "failed"), so this can't be told apart in the try/catch's
   * `catch` branch — it has to be checked on the resolved value:
   *  - a no-résumé refusal carries `missingResume: true` (backend
   *    apps/api/app/workers/tasks.py's `except MissingResumeError` handler);
   *  - a guard rejection or a first-draft LLM-unavailable degrade carries
   *    `coverLetterUnavailable: true` (ML-cover-002/003) — the async job now
   *    COMPLETES with this shape instead of failing with a raw 502, so it is
   *    surfaced HERE off the resolved result, not via `parseCoverLetterRejection`
   *    in the catch branch.
   * All three carry no `cover_letter_id` (no letter was generated); treating
   * that like a success used to call `load(undefined)`/`setError(null)`,
   * silently swallowing the honest message. Surface it through the page's
   * existing alert instead, and skip the pointless reload.
   */
  const applyCoverLetterResult = async (result: CoverLetterRunResult) => {
    if (result.missingResume || result.coverLetterUnavailable || !result.cover_letter_id) {
      setRejection(null);
      // AUD-COV-2: no letter exists to disclose anything about.
      setFitDisclosure(null);
      setError(result.message ?? "Add your resume before generating a cover letter.");
      return;
    }
    await load(result.cover_letter_id);
    setError(null);
    setRejection(null);
    // AUD-COV-2: set from THIS run's result every time (not only when
    // non-empty), so a good-fit regenerate clears a previous letter's warning
    // instead of leaving it attached to a letter it does not describe.
    const disclosure = result.fit_disclosure ?? "";
    setFitDisclosure(
      disclosure ? { letterId: result.cover_letter_id, text: disclosure } : null,
    );
  };

  useEffect(() => {
    void load();
  }, [load]);

  // W-RT — the shared realtime channel. This screen used to fetch ONCE on
  // mount, so a letter drafted by the cover-letter agent never appeared until
  // the user reloaded. `coverLetters` watches exactly the rows this list is
  // built from (Applications carrying a letter).
  useRealtimeResources(["coverLetters"], () => {
    void load();
  });

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
      await applyCoverLetterResult(result);
    } catch (e) {
      handleAgentError(e, "Cover letter run failed", () => void generate());
    } finally {
      setRunning(false);
    }
  };

  // Full agent re-run for a letter's job (per-card Regenerate).
  const regenerate = async (letter: CoverLetter) => {
    setRegenerating(letter.id);
    try {
      const result = await runCoverLetterAgent(letter.jobId);
      await applyCoverLetterResult(result);
    } catch (e) {
      handleAgentError(e, "Regenerate failed", () => void regenerate(letter));
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
      setRejection(null);
    } catch (e) {
      handleAgentError(e, "Regenerate failed", () => void regenerateSelected());
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
      setRejection(null);
      return true;
    } catch (e) {
      // The refine form stays open with the typed instructions on failure, so
      // the rejection panel's own "Regenerate" re-runs a plain redraft
      // (tone/formality only) rather than resubmitting the flagged text.
      handleAgentError(e, "Change request failed", () => void regenerateSelected());
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

  /** The label a row (and the reading column header) shows for a letter. */
  const labelFor = useCallback(
    (letter: CoverLetter) => {
      const job = jobs.find((j) => j.id === letter.jobId);
      // P1-10b: fall back to the server-joined title/company when the job is no
      // longer in the /jobs list (applied/archived).
      return job
        ? `${job.title} · ${job.company}`
        : letter.jobTitle
          ? `${letter.jobTitle}${letter.jobCompany ? ` · ${letter.jobCompany}` : ""}`
          : `Job ${letter.jobId.slice(0, 8)}`;
    },
    [jobs],
  );

  const filteredLetters = useMemo(() => {
    const list = letters ?? [];
    const q = letterFilter.trim().toLowerCase();
    if (!q) return list;
    return list.filter((l) => labelFor(l).toLowerCase().includes(q));
  }, [letters, letterFilter, labelFor]);

  const segments =
    selected && selected.coverLetter
      ? highlightSegments(selected.coverLetter, selectedInsights?.evidence ?? [])
      : [];
  const selectedLabel = selected ? labelFor(selected) : "";
  const selectedJobRecord = selected ? jobFor(selected.jobId) : undefined;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Cover Letter Studio"
        subtitle="Drafts pass a fabrication guard — every claim traces to your resume."
        action={
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              className="elev-1 h-10 w-full min-w-0 rounded-lg border-hairline px-3 text-sm text-aether-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50 sm:w-[260px]"
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
              className={button({ tone: "primary", size: "md", class: "h-10 text-aether-bg" })}
            >
              {running ? "Drafting..." : "Generate Draft"}
            </button>
          </div>
        }
      />

      <nav aria-label="Breadcrumb" className="-mt-2 flex items-center gap-2 type-meta">
        <Link href="/dashboard/resume" className="transition-colors duration-[--dur-fast] hover:text-aether-text">
          Resume Studio
        </Link>
        <i className="fa-solid fa-chevron-right text-[8px]" aria-hidden="true" />
        <span className="text-aether-muted">Cover Letter</span>
      </nav>

      {/* THE TWO CERTIFICATIONS. Both read from the SELECTED letter's insights
          and show "—" when there is no measurement — never a reassuring
          default. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:max-w-[640px]">
        <div
          className="elev-1 flex items-center gap-3 rounded-xl px-4 py-3"
          data-testid="voice-authenticity-indicator"
        >
          <i className="fa-solid fa-shield-halved text-state-ok" aria-hidden="true" />
          <div className="min-w-0 leading-tight">
            <div className="type-section">Evidence Grounding</div>
            <div className="mono mt-1 text-[15px] font-semibold text-state-ok">
              {selectedInsights ? `${selectedInsights.voice.authenticity}% grounded` : "—"}
            </div>
          </div>
        </div>
        <div
          className="elev-1 flex items-center gap-3 rounded-xl px-4 py-3"
          data-testid="ai-detection-indicator"
        >
          <i className="fa-solid fa-shield text-state-info" aria-hidden="true" />
          <div className="min-w-0 leading-tight">
            <div className="type-section">Fabrication Guard</div>
            <div className="mono mt-1 text-[15px] font-semibold text-state-ok">
              {selectedInsights ? selectedInsights.voice.aiDetectionLabel : "—"}
            </div>
          </div>
        </div>
      </div>

      {rejection ? (
        <RejectionPanel
          rejection={rejection.model}
          regenerating={regenerating !== null}
          onRegenerate={() => {
            const { retry } = rejection;
            setRejection(null);
            retry();
          }}
        />
      ) : error ? (
        <p
          role="alert"
          className="rounded-xl border border-state-danger/30 bg-state-danger/10 p-3 text-sm text-state-danger"
        >
          {error}
        </p>
      ) : null}

      {/* AUD-COV-2: the letter WAS generated (the user asked for it explicitly),
          so this is a warning beside a real artefact — never a refusal, and
          never spliced into the letter body an employer reads. Rendered only
          while the letter it describes is the open one. */}
      {fitDisclosure && expanded === fitDisclosure.letterId ? (
        <p
          role="status"
          data-testid="cover-letter-fit-disclosure"
          className="rounded-xl border border-state-warn/30 bg-state-warn/10 p-3 text-sm text-state-warn"
        >
          {fitDisclosure.text}
        </p>
      ) : null}

      {letters === null ? (
        <div className="grid gap-5 lg:grid-cols-[264px,minmax(0,1fr)]" aria-busy="true">
          <div className="space-y-2">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="elev-1 h-[62px] animate-pulse rounded-xl" />
            ))}
          </div>
          <div className="elev-1 h-[520px] animate-pulse rounded-[14px]" />
        </div>
      ) : letters.length === 0 ? (
        <div
          className="elev-1 rounded-[14px] p-10 text-center"
          data-testid="cover-letters-empty-state"
        >
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-[10px] border border-aether-coral/25 bg-aether-coral/[0.12]">
            <i className="fa-solid fa-envelope-open-text text-aether-coral" aria-hidden="true" />
          </div>
          <p className="text-[17px] font-semibold">No cover letters yet</p>
          <p className="mt-1.5 text-sm text-aether-muted">
            Select a job and generate a draft — it will land in the approval queue.
          </p>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[264px,minmax(0,1fr)] lg:items-start">
          {/* ------------------------------------------------------------
              LETTERS RAIL — scroll-contained, filterable, paged (D-ε).
              639 letters used to render in full here; the rail renders the
              rows and ONE reading column renders the open letter.
          ------------------------------------------------------------- */}
          <section aria-label="Cover letters" className="min-w-0 lg:sticky lg:top-20">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h2 className="type-section">Drafts</h2>
              <span className="mono text-[11px] text-aether-muted-dim">{letters.length}</span>
            </div>
            {letters.length > LETTERS_PAGE_SIZE ? (
              <input
                type="search"
                value={letterFilter}
                onChange={(e) => setLetterFilter(e.target.value)}
                placeholder="Filter by role or company…"
                aria-label="Filter cover letters"
                data-testid="letter-filter"
                className="elev-1 mb-2 h-9 w-full rounded-lg border-hairline px-3 text-[13px] text-aether-text placeholder:text-aether-muted-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
              />
            ) : null}
            <ul
              role="listbox"
              aria-label="Cover letters"
              className="max-h-[600px] space-y-1.5 overflow-y-auto overscroll-contain pr-1"
            >
              {filteredLetters.slice(0, visibleCount).map((letter) => {
                const isOpen = expanded === letter.id;
                return (
                  <li key={letter.id} role="option" aria-selected={isOpen}>
                    <button
                      type="button"
                      data-testid="cover-letter-card"
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Collapse" : "Read"} draft for ${labelFor(letter)}`}
                      onClick={() => setExpanded(isOpen ? null : letter.id)}
                      className={listCard({ selected: isOpen, class: "block" })}
                    >
                      {isOpen ? (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-0 left-0 w-[3px] bg-aether-coral"
                        />
                      ) : null}
                      <p className="line-clamp-2 text-[12.5px] font-medium leading-[1.4]">
                        {labelFor(letter)}
                      </p>
                      <p className="mono mt-1 text-[10px] text-aether-muted-dim">
                        {letter.status} · {parseApiDate(letter.createdAt).toLocaleDateString("en-AU")}
                      </p>
                    </button>
                  </li>
                );
              })}
              {filteredLetters.length > visibleCount ? (
                <li>
                  <button
                    type="button"
                    data-testid="letters-show-more"
                    onClick={() => setVisibleCount((n) => n + LETTERS_PAGE_SIZE)}
                    className={button({ tone: "quiet", size: "sm", class: "w-full" })}
                  >
                    Show more ({filteredLetters.length - visibleCount} older)
                  </button>
                </li>
              ) : null}
              {filteredLetters.length === 0 ? (
                <li
                  className="rounded-xl border border-dashed border-hairline p-4 text-center text-[12px] text-aether-muted-dim"
                  data-testid="letter-filter-empty"
                >
                  No draft matches “{letterFilter}”.
                </li>
              ) : null}
            </ul>
          </section>

          {/* ------------------------------------------------------------
              THE OPEN LETTER + its single intelligence rail (§5.7).
          ------------------------------------------------------------- */}
          <div className="grid min-w-0 gap-5 2xl:grid-cols-[minmax(0,1fr),300px] 2xl:items-start">
            <div className="min-w-0">
              {selected ? (
                <article className="elev-1 min-w-0 rounded-[14px] p-5" data-testid="letter-detail">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
                        {selectedLabel}
                      </h2>
                      <p className="mono mt-1 text-[11px] text-aether-muted-dim">
                        {selected.status} ·{" "}
                        {parseApiDate(selected.createdAt).toLocaleString("en-AU")}
                      </p>
                    </div>
                    <button
                      type="button"
                      data-testid="regenerate-letter-btn"
                      aria-label={`Regenerate letter for ${selectedLabel}`}
                      onClick={() => void regenerate(selected)}
                      disabled={regenerating !== null}
                      className={button({ tone: "neutral", size: "sm" })}
                    >
                      {regenerating === selected.id ? "Redrafting…" : "Regenerate"}
                    </button>
                  </div>

                  {selected.coverLetter ? (
                    <div className="mt-4" data-testid="letter-preview">
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <i
                            className="fa-solid fa-file-lines text-sm text-aether-coral"
                            aria-hidden="true"
                          />
                          <h3 className="type-section">Cover Letter — Draft</h3>
                          <span className={chip({ tone: "info" })}>AI-generated · editable</span>
                        </div>
                        <span
                          className="mono text-[11px] text-aether-muted-dim"
                          data-testid="word-count"
                        >
                          {selectedInsights?.wordCount ?? wordCount(selected.coverLetter)} words · 1
                          page
                        </span>
                      </div>
                      {/*
                        Brand-matched preview (resume_pdf.py branded template):
                        peach #FCD9CF letterhead panel with a coral #F4715C
                        accent rule at its foot, ink #2B2B2B body on white —
                        the same visual identity as the uploaded/tailored
                        resume, so the cover letter reads as one product.
                      */}
                      <div
                        className="mx-auto max-w-[70ch] overflow-hidden rounded-xl bg-white shadow-lg"
                        style={{ border: `1px solid ${CL_PANEL}` }}
                      >
                        <div className="px-8 py-5" style={{ backgroundColor: CL_PANEL }}>
                          <p className="text-lg font-bold leading-tight" style={{ color: CL_INK }}>
                            {selectedJobRecord
                              ? `${selectedJobRecord.title} · Cover Letter`
                              : "Cover Letter"}
                          </p>
                          <p className="mt-0.5 text-xs" style={{ color: CL_MUTED }}>
                            {selectedLabel}
                          </p>
                        </div>
                        <div style={{ height: 3, backgroundColor: CL_ACCENT }} />
                        <div
                          className="whitespace-pre-line px-8 py-6 text-sm leading-relaxed"
                          style={{ color: CL_INK }}
                        >
                          {segments.map((seg, i) =>
                            seg.kind === "plain" ? (
                              <span key={i}>{seg.text}</span>
                            ) : (
                              <mark
                                key={i}
                                data-testid={`highlight-${seg.kind}`}
                                className={`${SEGMENT_CLASS[seg.kind]}`}
                                style={{ color: CL_INK }}
                              >
                                {seg.text}
                              </mark>
                            ),
                          )}
                        </div>
                      </div>
                      <p className="type-meta mt-3">
                        Green marks a sentence traced to a Story Bank entry; amber marks one the
                        guard could not trace. Both are shown — the studio never hides an
                        ungrounded line.
                      </p>
                    </div>
                  ) : (
                    <p className="mt-4 text-[13px] text-aether-muted-dim" data-testid="letter-no-body">
                      This draft has no letter body stored — regenerate it to produce one.
                    </p>
                  )}
                </article>
              ) : (
                <div
                  className="elev-1 flex min-h-[260px] items-center justify-center rounded-[14px] p-8 text-center"
                  data-testid="letter-none-selected"
                >
                  <div className="max-w-[44ch]">
                    <p className="text-[15px] font-semibold">Select a draft to read it.</p>
                    <p className="type-meta mt-1.5">
                      Every draft keeps its own evidence trace, keyword coverage and quality
                      history — open one to see them.
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Studio control panel (wireframe cl06–cl16) — driven by the selected letter */}
            <aside className="min-w-0 space-y-4 2xl:sticky 2xl:top-20">
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
              {/* W-TAILOR-CONVERGE item 4/5: the persisted, deterministic quality
                  score of THIS letter (first draft vs shipped), served from
                  Application.coverLetterQuality — so it survives a reload
                  instead of living only in the run response. */}
              <LetterQualityPanel
                quality={selectedInsights?.quality ?? null}
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
        </div>
      )}
    </div>
  );
}
