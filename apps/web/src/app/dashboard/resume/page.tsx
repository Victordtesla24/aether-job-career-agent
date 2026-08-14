"use client";

/**
 * Resume workspace — version list, tailoring runs and evidence-linked diffs
 * backed by GET /resumes, GET /resumes/{id}/diff and POST /agents/tailor/run.
 */
import { useCallback, useEffect, useState } from "react";

import MetricTooltip from "../../../components/MetricTooltip";
import { QualityFloorNotice } from "../../../components/quality/QualityFloorNotice";
import { type QualityGate, qualityGateFrom } from "../../../lib/quality-gate";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import { conversionImpactFrom, type ConversionImpact } from "../../../lib/scoring/provenance";
import TailoringImpact from "../../../components/analytics/TailoringImpact";
import {
  downloadResume,
  fetchResumeDiff,
  fetchResumes,
  fetchTailoringImpact,
  runTailorAgent,
  type ConversionMetrics,
  type Resume,
  type ResumeDiff,
  type TailoringImpact as TailoringImpactPair,
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
  /** GMV4-ats-002: which path produced semantic_similarity — "local"/"hf_api"
   *  (genuine) or "degraded" (neutral placeholder, not a measurement). */
  semantic_path?: string | null;
  /** Unambiguous, client-branchable twin of semantic_path — true iff the
   *  semantic component above is a placeholder, not a real measurement. */
  semantic_degraded?: boolean;
};

/**
 * R-03 (round 3). `JobInsights`, `DIMENSION_ORDER` and `deriveTailoredDimensions`
 * used to live here: a browser-side re-implementation of
 * `routers/jobs.py::_build_insights`'s blend, applied to the wire's
 * already-1-decimal subscores, to produce the "after" half of the Resume
 * Studio before/after panel while the "before" half arrived pre-rounded to
 * integers from a different endpoint.
 *
 * Two defect classes came out of that duplication and neither was fixable
 * where it stood: a mixed-granularity delta (up to ±0.5 of pure rounding
 * artefact against a product lift that averages ~2 ATS points) and a second,
 * hand-maintained copy of the provenance rules, which is how a
 * placeholder-contaminated baseline reached the screen flagged as measured.
 *
 * Both halves now come from `GET /resumes/{id}/tailoring-impact`
 * (`fetchTailoringImpact`), blended and rounded by ONE authority
 * (`routers/jobs.py::build_fit_dimensions` + `_round`). The parity this file's
 * deleted test asserted by re-implementing the formulas is now structural, and
 * is pinned server-side by
 * `apps/api/tests/test_uax_r3_provenance.py::test_before_half_is_byte_identical_to_the_jobs_insights_panel`.
 */

/**
 * The VERIFIED fidelity report for one version (`GET /resumes/{id}/fidelity`).
 *
 * U2b truth round: the listing cannot re-render every version, so its
 * `formatFidelity` row states the mechanism and marks the per-change check
 * pending. This report is produced by rendering the version and re-reading the
 * document that came out, so it can say how many tailored changes are really
 * in the file the user downloads — and name the ones that are not. Live
 * production shipped the opposite: an unconditional "every other element is
 * identical to the source document" for a PDF splice that had silently skipped
 * a rewrite (uat/reports/evidence/agents-uplift/u2b/verify/, 2026-08-14).
 */
type FormatFidelityReport = {
  method: string;
  confidence: string;
  note: string;
  verification?: string | null;
  changesRequested?: number | null;
  changesApplied?: number | null;
  changesDropped?: number | null;
};

/** Accept the report ONLY when it really is one — an unrelated payload (or an
 *  older API with no such route) must fall back to the listing's own honest
 *  row, never render as a blank/garbled claim. */
function asFidelityReport(value: unknown): FormatFidelityReport | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.method === "string" &&
    typeof candidate.confidence === "string" &&
    typeof candidate.note === "string"
    ? (candidate as FormatFidelityReport)
    : null;
}

/** How many version cards to show before "Show more" (MV-resume-studio-005). */
const VERSIONS_PAGE_SIZE = 8;

/** Substring of the honest no-op message the tailor run returns / a failed async
 *  job surfaces, so the UI can render it as an informational notice rather than a
 *  scary error (MV-resume-studio-003). */
const NO_OP_HINT = "no verifiable changes";

/** A resume's real identity, derived from its own stored data — never a
 *  hardcoded third party (MV-adv-resume-studio-006). */
type ResumeIdentity = { name: string; title: string };

/**
 * Derive the real signed-in user's name/title from a resume's own `sections`
 * payload — the same data the version list/diff already render from. Prefers
 * an explicit `contact.name`/`contact.title` (set on ingest), falls back to
 * the resume's first extracted text line (a resume's own first line is
 * conventionally the candidate's name) and finally the version label. Returns
 * `null` only when no resume exists at all, so the caller can show an honest
 * empty-state instead of fabricating an identity.
 */
function deriveIdentity(resume: Resume | null | undefined): ResumeIdentity | null {
  if (!resume) return null;
  const sections = (resume.sections ?? {}) as {
    contact?: { name?: unknown; title?: unknown; headline?: unknown };
    raw_text?: unknown;
  };
  const contact = sections.contact ?? {};
  const rawText = typeof sections.raw_text === "string" ? sections.raw_text : "";
  const firstLine = rawText
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  const name =
    (typeof contact.name === "string" && contact.name.trim()) || firstLine || resume.label || "—";
  const title =
    (typeof contact.title === "string" && contact.title.trim()) ||
    (typeof contact.headline === "string" && contact.headline.trim()) ||
    "—";
  return { name, title };
}

export default function ResumePage() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [selected, setSelected] = useState<Resume | null>(null);
  const [diff, setDiff] = useState<ResumeDiff | null>(null);
  const [ats, setAts] = useState<AtsScore | null>(null);
  // U-AX item 3: honest before(baseline)/after(tailored) ATS + all 10
  // fit-radar dimensions for the SELECTED tailored version, served whole by
  // GET /resumes/{id}/tailoring-impact. R-03: the browser no longer derives
  // the "after" half — one server-side blend, one rounding authority, so the
  // two sides of a delta can never carry different granularities.
  const [tailoringImpact, setTailoringImpact] = useState<TailoringImpactPair | null>(null);
  const [fidelity, setFidelity] = useState<FormatFidelityReport | null>(null);
  const [conversion, setConversion] = useState<ConversionImpact | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** Honest sub-85 warning from the score-aware TailoringLoop (§5.3.1 pt 5) —
   *  null whenever the run reached the 85 ATS target. */
  const [tailorWarning, setTailorWarning] = useState<string | null>(null);
  const [qualityGate, setQualityGate] = useState<QualityGate | null>(null);
  const [downloadNote, setDownloadNote] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(VERSIONS_PAGE_SIZE);

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

  // W-RT — the shared realtime channel. Before this, the Résumé screen fetched
  // ONCE on mount and never again: a résumé tailored by an agent (or by the
  // Jobs board in another tab) was invisible here until a manual reload. It
  // also renders the Jobs list in the tailor picker, so both are subscribed.
  useRealtimeResources(["resumes", "jobs"], () => {
    void load();
  });

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
    setError(null);
    setNotice(null);
    setTailorWarning(null);
    try {
      const result = await runTailorAgent(selectedJob);
      if (result.noChangesApplied) {
        // Honest no-op — the guards rejected every edit; nothing was created or
        // billed. Surface it as an informational notice (MV-resume-studio-003).
        setConversion(null);
        setNotice(
          result.message ??
            "No changes could be applied — your résumé is unchanged and you were not charged.",
        );
      } else {
        // GMV4-ats-002 round 4: normalise at the boundary. The union's
        // degraded arm carries no numbers, so the panel below physically
        // cannot render one without ruling that arm out first.
        setConversion(conversionImpactFrom(result.conversionMetrics));
        // §5.3.1 pt 5: surface the TailoringLoop's own honest sub-85 message
        // verbatim when the loop stopped short of the 85 target — never when
        // the run actually reached it (warning is null on a clean run).
        setTailorWarning(result.warning ?? null);
      }
      await load();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Tailoring run failed";
      // The async path surfaces the honest no-op as a failed-job error; render it
      // as an informational notice, not a red error (MV-resume-studio-003).
      if (message.toLowerCase().includes(NO_OP_HINT)) {
        setNotice(message);
      } else {
        setError(message);
      }
    } finally {
      setRunning(false);
    }
  };

  const download = async (resume: Resume) => {
    setDownloadNote(null);
    try {
      await downloadResume(resume.id);
      // MON-011 (MONITORING-LEDGER.md, mon-batch-1-fe-opus-review-verdict.json
      // FE-MON011-A): the completion note used to claim format preservation
      // unconditionally. Branch it on this exact resume's own authoritative
      // `formatPreserved` flag (mirrors download's own resolve_original_pdf
      // match) instead — explicit false gets an honest not-preserved note,
      // and a missing flag (older cached payload) reads as unknown, never as
      // an affirmative claim (same "missing must read as unknown" rule as
      // the integrity strip below).
      // U2b coherence round: the VERIFIED report for the open version outranks
      // the listing flag, which describes the mechanism and cannot know whether
      // every rewrite landed. A file measured to be missing tailored wording is
      // not a "format-preserving PDF" whatever the mechanism row says.
      const droppedHere =
        fidelity && resume.id === selected?.id ? (fidelity.changesDropped ?? 0) : 0;
      setDownloadNote(
        droppedHere > 0
          ? `Downloaded — ${droppedHere} tailored change${droppedHere === 1 ? "" : "s"} could not be applied to this file; the full tailored wording is in the change summary.`
          : resume.formatPreserved === false
            ? "Downloaded — format not preserved: this PDF uses the Aether standard template, not your original layout."
            : resume.formatPreserved === true
              ? "Downloaded — format-preserving PDF saved."
              : "Downloaded — format preservation for this version is unknown; check the layout before relying on it.",
      );
    } catch (e) {
      setDownloadNote(e instanceof Error ? e.message : "Download failed");
    }
  };

  const openResume = async (resume: Resume) => {
    setSelected(resume);
    setDiff(null);
    setAts(null);
    setTailoringImpact(null);
    setFidelity(null);
    setDownloadNote(null);
    // W-TAILOR-CONVERGE item 5: the before/after ATS panel used to exist only
    // in transient state populated by the tailor RUN response, so a reload (or
    // simply opening an older version) showed nothing. The tailoring agent now
    // persists the same `conversionMetrics` + `tailoringSummary` onto the
    // Resume row, so re-hydrate both from the record itself. Strictly
    // API-derived — nothing is recomputed in the browser, and a version with
    // no stored metrics (any version tailored before this landed) clears the
    // panel rather than showing a neighbouring version's numbers.
    const stored = resume.sections as {
      conversionMetrics?: unknown;
      tailoringSummary?: {
        warning?: string | null;
        qualityGate?: unknown;
      } | null;
    };
    setConversion(
      stored.conversionMetrics
        ? conversionImpactFrom(stored.conversionMetrics as ConversionMetrics)
        : null,
    );
    setTailorWarning(stored.tailoringSummary?.warning ?? null);
    // U2c: the version's OWN 80%-across-all-dimensions verdict, re-hydrated
    // from the row rather than from the transient run response, so the Studio
    // tells the same story on a reload as it did the moment the run finished.
    // `null` for every version tailored before the gate existed — nothing
    // judged them, so the Studio claims nothing about them.
    setQualityGate(qualityGateFrom(stored.tailoringSummary?.qualityGate));
    try {
      setDiff(await fetchResumeDiff(resume.id));
    } catch {
      setDiff(null);
    }
    if (resume.sourceJobId) {
      let tailoredAts: AtsScore | null = null;
      try {
        tailoredAts = await apiRequest<AtsScore>(`/resumes/${resume.id}/ats`);
        setAts(tailoredAts);
      } catch {
        setAts(null);
      }
      // U-AX item 3 / R-03: BOTH halves come from one endpoint, blended and
      // rounded by one server-side authority (routers/jobs.py::
      // build_fit_dimensions + _round) against one JD corpus. Nothing is
      // re-derived here, so there is no second formula to drift and no second
      // rounding hop to invent a delta the engine never measured.
      try {
        setTailoringImpact(await fetchTailoringImpact(resume.id));
      } catch {
        setTailoringImpact(null);
      }
    }
    // U2b truth round: the VERIFIED fidelity report for this exact version —
    // the API renders it and re-reads the produced document, so the panel can
    // say how many tailored changes are genuinely in the downloadable file.
    // If the call fails the panel falls back to the listing's own row, which
    // states the mechanism and marks the per-change check pending — a weaker
    // claim, never a stronger one.
    try {
      setFidelity(
        asFidelityReport(await apiRequest<unknown>(`/resumes/${resume.id}/fidelity`)),
      );
    } catch {
      setFidelity(null);
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

  // Real per-version format-integrity signal (MV-resume-studio-004): the base is
  // the immutable root (no parent); a tailored version preserves layout iff its
  // formatHash still matches the base's (the source PDF is never re-rendered). The
  // panel below reflects THIS comparison instead of an unconditional claim.
  const baseResume = (resumes ?? []).find((r) => !r.parentId) ?? (resumes ?? [])[0];
  const baseHash = baseResume?.formatHash ?? null;
  // MON-011 (MONITORING-LEDGER.md): the hash comparison above is a self-
  // comparison for a base résumé (its own hash always equals itself) and says
  // nothing about whether GET /resumes/{id}/download can actually reproduce
  // the original document. When the API's `formatPreserved` flag is
  // EXPLICITLY false (it mirrors download's own resolve_original_pdf match),
  // that is authoritative and overrides the hash comparison with an honest
  // "not preserved" disclosure. A genuinely bundled-backed (explicit true)
  // flag falls back to the existing hash-comparison signal, unchanged.
  //
  // mon-batch-1-fe-opus-review-verdict.json FE-MON011-C: a MISSING flag
  // (older cached payload, or the API omitting it) used to fall through to
  // that same hash comparison too — a trivial self-match for a base résumé —
  // and rendered the affirmative claim for a real upload with no evidence
  // either way. WHITELIST the known cases instead (same precedent as
  // `semanticTrusted` below, GMV4-ats-002 round 3): a missing flag reads as
  // UNKNOWN, never as preserved.
  // U2b: the API's own fidelity report for the SELECTED version — {method,
  // confidence, note}. Rendered verbatim below the status line so the panel
  // states the real mechanism (native Word editing vs an Aether-template
  // re-render) instead of one generic sentence for every unpreserved case.
  // U2b truth round: prefer the VERIFIED report for the opened version over
  // the listing's row, which describes the mechanism but cannot know whether
  // every rewrite really landed in the produced document.
  const formatFidelity = fidelity ?? selected?.formatFidelity ?? null;
  const fidelityCounts =
    fidelity && typeof fidelity.changesRequested === "number" && fidelity.changesRequested > 0
      ? fidelity
      : null;
  // U2b coherence round: the headline below is derived from the LISTING row,
  // which by design cannot know whether a rewrite really landed in the produced
  // document (it never re-renders one). The verified report can — and when the
  // two disagree, the one that measured the artifact wins. Live production
  // rendered the green "…margins preserved" claim directly above "1 could not
  // be applied to this layout" for the same version (verify-truthround/,
  // 2026-08-14); a paying subscriber must never be told their layout is intact
  // over a notice that part of their tailoring is missing from the file.
  const verifiedChangesDropped =
    fidelityCounts && (fidelityCounts.changesDropped ?? 0) > 0
      ? (fidelityCounts.changesDropped as number)
      : 0;
  const formatPreservationKnown = selected != null && selected.formatPreserved != null;
  const formatExplicitlyUnpreserved = selected != null && selected.formatPreserved === false;
  const formatIntact = selected
    ? formatPreservationKnown
      ? formatExplicitlyUnpreserved || verifiedChangesDropped > 0
        ? false
        : selected.formatHash === baseHash
      : null
    : null;
  // Latest tailored version — `resumes` is ordered newest-first, so the first
  // match is the latest (MV-adv-resume-studio-006).
  const tailoredResume = (resumes ?? []).find((r) => r.label?.startsWith("Tailored"));
  const originalIdentity = deriveIdentity(baseResume);
  const tailoredIdentity = deriveIdentity(tailoredResume);

  // GMV4-ats-002 round 3: WHITELIST, computed from `semantic_path` itself
  // rather than the boolean twin — an older cached `ats` payload that
  // predates this field (or simply omits it) must read as NOT measured,
  // never as "not degraded" (round-2 fail-open truthy-read bug).
  const semanticTrusted = ats?.semantic_path === "local" || ats?.semantic_path === "hf_api";
  // ADR-GMV4-001: the ATS Conversion Impact panel's before/after/lift are
  // each derived from two fresh re-scores 40% built from semantic
  // similarity (tailor_agent.py `_compute_conversion_metrics`) — when
  // either endpoint was degraded, the panel must withhold/badge these
  // numbers instead of presenting a delta computed off a placeholder.
  const conversionDegraded = conversion?.provenance === "degraded";

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

      {notice ? (
        <p
          data-testid="tailor-notice"
          className="rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber"
        >
          {notice}
        </p>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-2" data-design-id="panes-rs0405">
        <div className="glass min-h-[240px] min-w-0 rounded-2xl border border-white/10 p-5" data-design-id="pane-original-rs04">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-aether-muted-dim" aria-hidden="true" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Original — Base Resume</h2>
          </div>
          {originalIdentity ? (
            <>
              <p className="mt-3 break-words text-lg font-bold tracking-wide" data-testid="hero-original-name">
                {originalIdentity.name}
              </p>
              <p className="break-words text-xs text-aether-muted-dim" data-testid="hero-original-title">
                {originalIdentity.title}
              </p>
            </>
          ) : (
            <p className="mt-3 text-sm text-aether-muted-dim" data-testid="hero-original-empty">
              No base resume yet.
            </p>
          )}
          <p className="mt-3 text-sm text-aether-muted">
            Base resume is immutable — every tailored version derives from this source of truth.
          </p>
        </div>
        <div className="glass min-h-[240px] min-w-0 rounded-2xl border border-aether-coral/30 p-5" data-design-id="pane-tailored-rs05">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-aether-green" aria-hidden="true" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Tailored — Latest Version</h2>
          </div>
          {tailoredIdentity ? (
            <>
              <p className="mt-3 break-words text-lg font-bold tracking-wide" data-testid="hero-tailored-name">
                {tailoredIdentity.name}
              </p>
              <p className="text-xs text-aether-muted-dim">Keyword-aligned for the selected role</p>
            </>
          ) : (
            <p className="mt-3 text-sm text-aether-muted-dim" data-testid="hero-tailored-empty">
              No tailored version yet.
            </p>
          )}
          <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-xs">
            {tailoredResume ? (
              <span className="min-w-0 max-w-full break-words rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">
                {tailoredResume.label}
              </span>
            ) : (
              <span className="rounded-full border border-white/10 px-2 py-0.5 text-aether-muted-dim">
                No tailored version yet — run tailoring against a job
              </span>
            )}
          </div>
        </div>
      </section>

      <section className="glass rounded-2xl border border-white/10 p-5" data-design-id="integrity-strip-rs14">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Format Integrity Check</h2>
            {!selected ? (
              <p className="mt-1 text-sm text-aether-muted-dim" data-testid="integrity-status">
                Select a version to verify its layout against the immutable base.
              </p>
            ) : verifiedChangesDropped > 0 ? (
              // Derived from the VERIFIED report for this exact version, and
              // stated FIRST: it is the only measured fact in this panel, so it
              // outranks both the listing's mechanism flag and the hash
              // comparison — neither of which can see a missing rewrite.
              <p className="mt-1 text-sm text-aether-amber" data-testid="integrity-status">
                {verifiedChangesDropped} of {fidelityCounts?.changesRequested} tailored changes
                could not be applied to the file you download — this version is not a complete
                tailored resume. The full wording is in the change summary below.
              </p>
            ) : !formatPreservationKnown ? (
              <p className="mt-1 text-sm text-aether-muted-dim" data-testid="integrity-status">
                Format preservation status is unknown for this version — we can&apos;t yet
                confirm whether download will match your original layout.
              </p>
            ) : formatExplicitlyUnpreserved ? (
              <p className="mt-1 text-sm text-aether-amber" data-testid="integrity-status">
                Format not preserved for this upload — download renders in the Aether standard
                template, not your original layout.
              </p>
            ) : formatIntact ? (
              <p className="mt-1 text-sm text-aether-green" data-testid="integrity-status">
                Layout hash matches the base — typography, spacing, columns &amp; margins preserved.
              </p>
            ) : (
              <p className="mt-1 text-sm text-aether-amber" data-testid="integrity-status">
                Layout hash differs from the base — review formatting before using this version.
              </p>
            )}
            {formatFidelity ? (
              // U2b (R-F2/R-F4): the API's OWN per-version report, not a
              // hard-coded string. A genuine docx-native preservation and a
              // low-confidence PDF re-flow used to render identical copy here,
              // which is exactly the silent claim R-F4 forbids.
              <p
                className="mt-1 text-xs text-aether-muted-dim"
                data-testid="format-fidelity-detail"
              >
                <span className="mono uppercase tracking-wide">
                  {formatFidelity.method}
                </span>
                {" · "}
                {formatFidelity.confidence} confidence — {formatFidelity.note}
              </p>
            ) : null}
            {fidelityCounts ? (
              // The counts come from re-reading the file this version renders
              // to — not from what the tailoring run believed it changed.
              <p
                className={`mt-1 text-xs ${
                  (fidelityCounts.changesDropped ?? 0) > 0
                    ? "text-aether-amber"
                    : "text-aether-green"
                }`}
                data-testid="format-fidelity-counts"
              >
                {(fidelityCounts.changesDropped ?? 0) > 0
                  ? `Verified on the produced file: ${fidelityCounts.changesApplied ?? 0} of ${fidelityCounts.changesRequested} tailored changes applied — ${fidelityCounts.changesDropped} could not be applied to this layout (the full wording is in the change summary below).`
                  : `Verified on the produced file: all ${fidelityCounts.changesRequested} tailored changes are present in the document you download.`}
              </p>
            ) : null}
            <p className="mt-1 text-xs text-aether-muted-dim">
              {diff
                ? `Changes Summary: ${diff.changes.filter((c) => c.before).length} rewrites · ${diff.changes.filter((c) => !c.before).length} additions${formatIntact ? " · formatHash carried from base" : ""}`
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

      {conversion ? (
        <section
          className="glass rounded-2xl border border-white/10 p-5"
          data-design-id="conversion-metrics-rs16"
          data-testid="conversion-metrics"
        >
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
            ATS Conversion Impact
            {conversionDegraded ? (
              <span
                className="ml-1.5 rounded-full border border-white/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-aether-muted-dim"
                data-testid="conversion-not-measured-badge"
              >
                not measured
              </span>
            ) : null}
          </h2>
          <p className="mt-2 text-sm text-aether-muted" data-testid="conversion-before-after">
            Before:{" "}
            <span className="mono font-semibold text-white">
              {conversion.provenance === "degraded" ? "—" : `${conversion.baselineATSScore}%`}
            </span>{" "}
            → After:{" "}
            <span className="mono font-semibold text-aether-green">
              {conversion.provenance === "degraded" ? "—" : `${conversion.tailoredATSScore}%`}
            </span>
          </p>
          <p className="mt-1 text-sm" data-testid="conversion-lift">
            <MetricTooltip
              label="Estimated interview conversion improvement"
              value={
                <span className="mono font-semibold text-aether-green">
                  {conversion.provenance === "degraded" ? "—" : conversion.estimatedConversionLift}
                </span>
              }
              tooltip={`${conversion.methodology} This is an illustrative estimate, not a measured outcome.`}
            />
          </p>
          {conversionDegraded ? (
            <p className="mt-3 text-xs text-aether-muted-dim" data-testid="conversion-degraded-note">
              Semantic similarity could not be measured for the before/after re-score
              — a neutral placeholder stood in instead, so this delta and the
              conversion lift above should be treated as directional until scoring is
              available again.
            </p>
          ) : null}
        </section>
      ) : null}

      {/* U2c — the failing dimensions, verbatim from this version's real
          scores. Rendered ABOVE the loop's prose warning because a user
          scanning the page needs the checkable numbers first. */}
      <QualityFloorNotice gate={qualityGate} testId="tailor-quality-floor" />

      {tailorWarning ? (
        <p
          data-testid="tailor-score-warning"
          className="rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber"
        >
          {tailorWarning}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[320px,1fr]">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
            Versions
          </h2>
          {resumes === null ? (
            <div className="space-y-3" aria-busy="true">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="glass h-16 animate-pulse rounded-xl border border-white/10" />
              ))}
            </div>
          ) : resumes.length === 0 ? (
            <div className="glass rounded-2xl border border-white/10 p-6 text-center text-sm text-aether-muted">
              No resume versions yet. Tailor against a job to create one.
            </div>
          ) : (
            <>
              {resumes.slice(0, visibleCount).map((resume) => (
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
                      {new Date(resume.createdAt).toLocaleDateString("en-AU")}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-aether-muted">
                    {resume.label ?? (resume.version === 1 ? "Base resume" : "Tailored version")}
                  </p>
                  {resume.approvalStatus === "pending" ? (
                    <span
                      data-testid="version-pending-badge"
                      className="mt-2 inline-block rounded-full border border-aether-amber/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-aether-amber"
                    >
                      Pending approval
                    </span>
                  ) : resume.approvalStatus === "rejected" ? (
                    <span
                      data-testid="version-rejected-badge"
                      className="mt-2 inline-block rounded-full border border-red-500/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-300"
                    >
                      Changes requested
                    </span>
                  ) : null}
                </button>
              ))}
              {resumes.length > visibleCount ? (
                <button
                  type="button"
                  data-testid="versions-show-more"
                  onClick={() => setVisibleCount((n) => n + VERSIONS_PAGE_SIZE)}
                  className="w-full rounded-xl border border-white/10 px-4 py-2 text-xs font-semibold text-aether-muted transition hover:border-white/20 hover:text-white"
                >
                  Show more ({resumes.length - visibleCount} older)
                </button>
              ) : null}
            </>
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
                    onClick={() => void download(selected)}
                    className="shrink-0 rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted transition hover:border-white/30 hover:text-white"
                  >
                    Download
                  </button>
                </div>
                {selected.approvalStatus === "pending" ? (
                  <p
                    data-testid="version-approval-hint"
                    className="mt-2 rounded-lg border border-aether-amber/30 bg-aether-amber/10 p-2 text-xs text-aether-amber"
                  >
                    Pending your review —{" "}
                    <a href="/dashboard/approvals" className="font-semibold underline">
                      approve or request changes
                    </a>{" "}
                    to make this your authoritative tailored version.
                  </p>
                ) : selected.approvalStatus === "rejected" ? (
                  <p
                    data-testid="version-approval-hint"
                    className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300"
                  >
                    You requested changes on this version — re-run tailoring to try again.
                  </p>
                ) : null}
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
            {/* R-01 (round 3): `overall` is 0.4*keyword + 0.4*semantic +
                0.2*experience, so a degraded semantic half makes this headline
                40% neutral placeholder — the same value the "Semantic
                similarity (40%)" row directly below already refuses to print.
                A "treat as directional" footnote under a bold, colour-coded
                number is not a caveat a reader acts on; the number itself has
                to go. */}
            <span
              className={`font-mono text-2xl font-bold ${
                !semanticTrusted
                  ? "text-aether-muted-dim"
                  : ats.overall >= 60
                    ? "text-aether-green"
                    : "text-aether-amber"
              }`}
              data-testid="ats-overall"
            >
              {semanticTrusted ? ats.overall : "—"}
            </span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Keyword match (40%)", value: ats.keyword_match, degraded: false },
              {
                label: "Semantic similarity (40%)",
                value: ats.semantic_similarity,
                degraded: !semanticTrusted,
              },
              { label: "Experience fit (20%)", value: ats.experience_gap, degraded: false },
            ].map((row) => (
              <div key={row.label}>
                <div className="flex items-center justify-between text-xs text-aether-muted">
                  <span>
                    {row.label}
                    {row.degraded ? (
                      <span
                        className="ml-1.5 rounded-full border border-white/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-aether-muted-dim"
                        data-testid="semantic-not-measured-badge"
                      >
                        not measured
                      </span>
                    ) : null}
                  </span>
                  <span className="mono">{row.degraded ? "—" : row.value}</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-white/10">
                  <div
                    className={`h-1.5 rounded-full ${row.degraded ? "bg-white/20" : "bg-aether-indigo"}`}
                    style={{ width: `${row.degraded ? 0 : Math.min(100, Math.max(0, row.value))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          {!semanticTrusted ? (
            <p className="mt-3 text-xs text-aether-muted-dim" data-testid="semantic-degraded-note">
              Semantic similarity could not be measured for this score — a neutral
              placeholder stood in instead. The overall ATS score is 40% built
              from it, so it is shown as “—” rather than as a measurement until
              semantic scoring is available again.
            </p>
          ) : null}
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

      {/* U-AX item 3: honest before(baseline)/after(tailored) ATS + all 10
          fit-radar dimensions for this version, threshold line marked,
          deltas never clamped or hidden. */}
      {tailoringImpact ? (
        <TailoringImpact
          beforeAts={tailoringImpact.before.ats}
          afterAts={tailoringImpact.after.ats}
          beforeDimensions={tailoringImpact.before.dimensions}
          afterDimensions={tailoringImpact.after.dimensions}
          atsUnmeasuredReason={
            tailoringImpact.before.ats === null
              ? tailoringImpact.before.unmeasuredReason
              : tailoringImpact.after.unmeasuredReason
          }
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2" data-design-id="evidence-voice-rs15">
        <section className="glass min-w-0 rounded-2xl border border-white/10 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">Evidence Trace</h2>
          <p className="mt-1 text-xs text-aether-muted-dim">
            Every rewritten line links back to evidence in the base resume.
          </p>
          {diff && diff.changes.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm text-aether-muted">
              {diff.changes.slice(0, 4).map((change, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="truncate">
                    {(() => {
                      const t = change.after || change.before;
                      return t.length > 60 ? `${t.slice(0, 60)}…` : t;
                    })()}
                  </span>
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
        <section
          className="glass min-w-0 rounded-2xl border border-white/10 p-5"
          data-design-id="version-compare-rs18"
        >
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
