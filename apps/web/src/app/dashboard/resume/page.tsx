"use client";

/**
 * Resume workspace — version list, tailoring runs and evidence-linked diffs
 * backed by GET /resumes, GET /resumes/{id}/diff and POST /agents/tailor/run.
 *
 * S-UI B3 — THE AHA MOMENT (presentation only).
 * -------------------------------------------
 * Every fetch, every hook call, every piece of derived state below is the same
 * as it was before this batch: same endpoints, same order, same conditions,
 * same honesty branches. What changed is the SHAPE of the screen. The old page
 * opened with two near-empty 240px identity panels, a `— / —` integrity strip
 * and a 1,000px void beside eight identically-titled version cards; the first
 * thing a subscriber saw after their first tailoring run was nothing at all.
 *
 * It now opens with the measured transformation — baseline ATS -> this
 * version's ATS with the exact delta, the changed lines with the words that
 * are genuinely new marked in the SAME coral the PDF renderer washes them in
 * (`components/resume/diff-semantics.ts` mirrors `services/resume_pdf.py`),
 * the file-level verification verdict exactly as `GET /resumes/{id}/fidelity`
 * reports it, and the 10-dimension scorecard with `—` wherever a dimension was
 * not measured. Nothing here renders a number the machinery did not measure,
 * and every honesty branch that existed before still exists, word for word.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import MetricTooltip from "../../../components/MetricTooltip";
import AhaHero from "../../../components/resume/AhaHero";
import ChangeList from "../../../components/resume/ChangeList";
import { changeCounts, renderBullets } from "../../../components/resume/diff-semantics";
import PageHeader from "../../../components/shell/PageHeader";
import Section from "../../../components/ui/Section";
import { button, chip, listCard } from "../../../components/ui/recipes";
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

/** How many change cards the studio opens with before "Show all". */
const CHANGES_PREVIEW = 4;

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
  const [downloadNote, setDownloadNote] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(VERSIONS_PAGE_SIZE);
  /** Presentation-only rail filter — 486 identically-titled versions are
   *  unusable without one (§4.4). Filters the ALREADY-fetched list; it makes
   *  no request and changes no query. */
  const [versionFilter, setVersionFilter] = useState("");
  const [allChanges, setAllChanges] = useState(false);
  /**
   * True while the four per-version reads (`/diff`, `/ats`, `/tailoring-impact`,
   * `/fidelity`) for the OPEN version are in flight.
   *
   * This is an honesty flag, not a spinner. Without it the aha hero mounted
   * with every measurement still `null` and therefore printed "not measured"
   * and a neutral verification chip for a beat before the real numbers
   * arrived — a false negative claim about the user's own resume. M7: the
   * skeleton stands at the FINAL geometry instead, so nothing is claimed and
   * nothing shifts when the data lands.
   */
  const [detailLoading, setDetailLoading] = useState(false);

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
    setDetailLoading(true);
    setDiff(null);
    setAts(null);
    setTailoringImpact(null);
    setFidelity(null);
    setDownloadNote(null);
    setAllChanges(false);
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
      tailoringSummary?: { warning?: string | null } | null;
    };
    setConversion(
      stored.conversionMetrics
        ? conversionImpactFrom(stored.conversionMetrics as ConversionMetrics)
        : null,
    );
    setTailorWarning(stored.tailoringSummary?.warning ?? null);
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
    } finally {
      setDetailLoading(false);
    }
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

  const changes = useMemo(() => diff?.changes ?? [], [diff]);
  const counts = useMemo(() => changeCounts(changes), [changes]);
  const evidenceCovered = useMemo(
    () => changes.filter((c) => c.evidenceRef).length,
    [changes],
  );
  /** The bullets the DOWNLOAD would draw, resolved through the renderer's own
   *  swap/wash rules — so the studio and the produced file agree. */
  const renderedBullets = useMemo(() => {
    if (!selected) return [];
    const sections = selected.sections as { bullets?: unknown };
    const stored = Array.isArray(sections.bullets)
      ? (sections.bullets as Array<{ text?: string } | string>).map((b) =>
          typeof b === "string" ? b : (b.text ?? ""),
        )
      : [];
    return renderBullets(stored, changes);
  }, [selected, changes]);
  const changedBulletCount = renderedBullets.filter((b) => b.changed).length;

  /** Rail filter — pure client-side narrowing of the fetched list. */
  const filteredResumes = useMemo(() => {
    const list = resumes ?? [];
    const q = versionFilter.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (r) =>
        `v${r.version}`.includes(q) ||
        (r.label ?? "").toLowerCase().includes(q),
    );
  }, [resumes, versionFilter]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Resume Studio"
        subtitle="Versioned, evidence-linked tailoring. Base resume is immutable."
        action={
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              className="elev-1 h-10 w-full min-w-0 rounded-lg border-hairline px-3 text-sm text-aether-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50 sm:w-[280px]"
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
              className={button({ tone: "primary", size: "md", class: "h-10 text-aether-bg" })}
            >
              {running ? "Tailoring..." : "Tailor Resume"}
            </button>
          </div>
        }
      />

      {error ? (
        <p className="rounded-xl border border-state-danger/30 bg-state-danger/10 p-3 text-sm text-state-danger">
          {error}
        </p>
      ) : null}

      {notice ? (
        <p
          data-testid="tailor-notice"
          className="rounded-xl border border-state-warn/30 bg-state-warn/10 p-3 text-sm text-state-warn"
        >
          {notice}
        </p>
      ) : null}

      {tailorWarning ? (
        <div className="rounded-xl border border-state-warn/30 bg-state-warn/[0.07] p-4">
          <p className="type-section text-state-warn">
            <i className="fa-solid fa-triangle-exclamation mr-1.5" aria-hidden="true" />
            Tailoring run — review before you send
          </p>
          <p
            data-testid="tailor-score-warning"
            className="mt-2 max-w-[110ch] text-[12.5px] leading-[1.6] text-state-warn"
          >
            {tailorWarning}
          </p>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[260px,minmax(0,1fr)] lg:items-start">
        {/* ---------------------------------------------------------------
            VERSION RAIL — dense, filterable, scroll-contained (§4.4 / D-ε).
            The filter narrows the ALREADY-fetched list; no request changes.
        ---------------------------------------------------------------- */}
        <section
          aria-label="Resume versions"
          className="min-w-0 lg:sticky lg:top-20"
          data-design-id="version-rail-rs20"
        >
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <h2 className="type-section">Versions</h2>
            {resumes ? (
              <span className="mono text-[11px] text-aether-muted-dim">{resumes.length}</span>
            ) : null}
          </div>
          {resumes && resumes.length > VERSIONS_PAGE_SIZE ? (
            <input
              type="search"
              value={versionFilter}
              onChange={(e) => setVersionFilter(e.target.value)}
              placeholder="Filter versions…"
              aria-label="Filter versions"
              data-testid="version-filter"
              className="elev-1 mb-2 h-9 w-full rounded-lg border-hairline px-3 text-[13px] text-aether-text placeholder:text-aether-muted-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
            />
          ) : null}

          {resumes === null ? (
            <div className="space-y-2" aria-busy="true">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="elev-1 h-[68px] animate-pulse rounded-xl" />
              ))}
            </div>
          ) : resumes.length === 0 ? (
            <div className="elev-1 rounded-xl p-5 text-center text-[13px] text-aether-muted">
              No resume versions yet. Tailor against a job to create one.
            </div>
          ) : (
            <ul
              role="listbox"
              aria-label="Resume versions"
              className="max-h-[560px] space-y-1.5 overflow-y-auto overscroll-contain pr-1"
            >
              {filteredResumes.slice(0, visibleCount).map((resume) => {
                const isSelected = selected?.id === resume.id;
                return (
                  <li key={resume.id} role="option" aria-selected={isSelected}>
                    <button
                      type="button"
                      data-testid="resume-version-card"
                      onClick={() => void openResume(resume)}
                      className={listCard({ selected: isSelected, class: "block" })}
                    >
                      {isSelected ? (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-0 left-0 w-[3px] bg-aether-coral"
                        />
                      ) : null}
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="mono text-[13px] font-semibold">v{resume.version}</span>
                        <span className="mono text-[10px] text-aether-muted-dim">
                          {new Date(resume.createdAt).toLocaleDateString("en-AU")}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-[1.45] text-aether-muted">
                        {resume.label ?? (resume.version === 1 ? "Base resume" : "Tailored version")}
                      </p>
                      {resume.approvalStatus === "pending" ? (
                        <span
                          data-testid="version-pending-badge"
                          className={chip({ tone: "warn", class: "mt-1.5" })}
                        >
                          Pending approval
                        </span>
                      ) : resume.approvalStatus === "rejected" ? (
                        <span
                          data-testid="version-rejected-badge"
                          className={chip({ tone: "danger", class: "mt-1.5" })}
                        >
                          Changes requested
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
              {filteredResumes.length > visibleCount ? (
                <li>
                  <button
                    type="button"
                    data-testid="versions-show-more"
                    onClick={() => setVisibleCount((n) => n + VERSIONS_PAGE_SIZE)}
                    className={button({ tone: "quiet", size: "sm", class: "w-full" })}
                  >
                    Show more ({filteredResumes.length - visibleCount} older)
                  </button>
                </li>
              ) : null}
              {filteredResumes.length === 0 ? (
                <li
                  className="rounded-xl border border-dashed border-hairline p-4 text-center text-[12px] text-aether-muted-dim"
                  data-testid="version-filter-empty"
                >
                  No version matches “{versionFilter}”.
                </li>
              ) : null}
            </ul>
          )}
        </section>

        {/* ---------------------------------------------------------------
            THE STUDIO COLUMN
        ---------------------------------------------------------------- */}
        <div className="min-w-0 space-y-5">
          <div className="grid min-w-0 gap-5 2xl:grid-cols-[minmax(0,1fr),360px] 2xl:items-start">
            {/* LEFT — the transformation itself: the hero, the changed
                lines, and the version as the download draws it. */}
            <div className="min-w-0 space-y-5">
            {/* THE AHA MOMENT. Rendered for a version that was tailored against
                a job — a base résumé has no before/after to state. */}
            {selected && selected.sourceJobId ? (
              <AhaHero
                loading={detailLoading}
                jobTitle={tailoringImpact?.jobTitle ?? ats?.job_title ?? null}
                company={tailoringImpact?.company ?? ats?.company ?? null}
                beforeAts={tailoringImpact?.before.ats ?? null}
                afterAts={tailoringImpact?.after.ats ?? null}
                unmeasuredReason={
                  tailoringImpact
                    ? tailoringImpact.before.ats === null
                      ? tailoringImpact.before.unmeasuredReason
                      : tailoringImpact.after.unmeasuredReason
                    : null
                }
                changesRequested={fidelityCounts?.changesRequested ?? null}
                changesApplied={fidelityCounts?.changesApplied ?? null}
                changesDropped={fidelityCounts?.changesDropped ?? null}
                evidenceCovered={evidenceCovered}
                evidenceTotal={changes.length}
                versionLabel={
                  selected.label ?? `Version ${selected.version}`
                }
              />
            ) : null}

            {/* WHAT CHANGED — the diff, the page's centre of gravity. */}
            {selected ? (
              diff && changes.length > 0 ? (
                <Section
                  eyebrow="What changed"
                  title="Every rewritten line, and the evidence behind it"
                  testId="resume-diff"
                  footnote="Highlighted words are the ones absent from your baseline sentence. The same lines are washed in coral in the document you download."
                  action={
                    <span className="mono text-[11px] text-aether-muted-dim">
                      {counts.rewrites} rewritten · {counts.additions} added
                    </span>
                  }
                >
                  <ChangeList
                    changes={changes}
                    limit={CHANGES_PREVIEW}
                    showingAll={allChanges}
                    onShowAll={() => setAllChanges(true)}
                  />
                </Section>
              ) : diff ? (
                <Section eyebrow="What changed" testId="resume-diff-empty">
                  <p className="text-[13px] text-aether-muted-dim">
                    This version records no changes against its parent.
                  </p>
                </Section>
              ) : null
            ) : (
              <Section
                eyebrow="Before / after"
                testId="studio-empty"
                className="flex min-h-[220px] items-center justify-center text-center"
              >
                <div className="max-w-[42ch]">
                  <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-aether-coral/25 bg-aether-coral/[0.12]">
                    <i className="fa-solid fa-file-lines text-aether-coral" aria-hidden="true" />
                  </div>
                  <p className="text-[15px] font-semibold">
                    Select a version to preview its bullets and diff.
                  </p>
                  <p className="type-meta mt-1.5">
                    Every tailored version keeps its own before/after score, its change list and the
                    evidence behind each line.
                  </p>
                </div>
              </Section>
            )}

            {/* THE VERSION ITSELF — bullets as the download draws them. */}
            {selected ? (
              <Section
                eyebrow={`Version ${selected.version}`}
                title={selected.label ?? undefined}
                testId="version-detail"
                action={
                  <button
                    type="button"
                    data-testid="download-resume-btn"
                    onClick={() => void download(selected)}
                    className={button({ tone: "neutral", size: "sm" })}
                  >
                    <i className="fa-solid fa-arrow-down-to-line" aria-hidden="true" />
                    Download
                  </button>
                }
                footnote={
                  renderedBullets.length > 0
                    ? `${changedBulletCount} of ${renderedBullets.length} bullets carry tailored wording — the same lines the download washes in coral.`
                    : undefined
                }
              >
                {selected.approvalStatus === "pending" ? (
                  <p
                    data-testid="version-approval-hint"
                    className="mb-3 rounded-lg border border-state-warn/30 bg-state-warn/10 p-2.5 text-[12px] text-state-warn"
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
                    className="mb-3 rounded-lg border border-state-danger/30 bg-state-danger/10 p-2.5 text-[12px] text-state-danger"
                  >
                    You requested changes on this version — re-run tailoring to try again.
                  </p>
                ) : null}
                {downloadNote ? (
                  <p
                    data-testid="download-note"
                    className="mb-3 rounded-lg border border-state-warn/30 bg-state-warn/10 p-2.5 text-[12px] text-state-warn"
                  >
                    {downloadNote}
                  </p>
                ) : null}
                <ul className="max-h-[300px] space-y-1.5 overflow-y-auto overscroll-contain pr-1">
                  {renderedBullets.map((bullet, i) => (
                    <li
                      key={i}
                      data-testid={bullet.changed ? "version-bullet-changed" : "version-bullet"}
                      className={`flex gap-2.5 rounded-lg px-2 py-1.5 text-[12.5px] leading-[1.6] ${
                        bullet.changed
                          ? "bg-aether-coral/[0.10] text-aether-text"
                          : "text-aether-muted"
                      }`}
                    >
                      <span
                        className={bullet.changed ? "text-aether-coral" : "text-aether-muted-dim"}
                        aria-hidden="true"
                      >
                        •
                      </span>
                      <span className="min-w-0">
                        {bullet.changed ? <span className="sr-only">tailored: </span> : null}
                        {bullet.text}
                      </span>
                    </li>
                  ))}
                  {renderedBullets.length === 0 ? (
                    <li className="text-[13px] text-aether-muted-dim">No bullet sections stored.</li>
                  ) : null}
                </ul>
              </Section>
            ) : null}

            </div>

            {/* RIGHT — the verdicts: what was verified, what was scored,
                and where every line came from. Same content, same order of
                claim, moved out of the reading column so the page ends
                (D-ε: 3,832px -> the budget) instead of stacking to the
                bottom of the scrollbar. */}
            <div className="min-w-0 space-y-5">
            {/* FORMAT INTEGRITY — always mounted: its neutral prompt is itself
                an honesty contract when no version is open. */}
            <Section
              eyebrow="Format integrity check"
              testId="integrity-strip"
              className="min-w-0"
              action={
                <div className="flex items-end gap-6 text-right">
                  <div>
                    <p className="type-section">Modifications</p>
                    <p className="mono mt-0.5 text-xl font-bold text-state-warn">
                      {diff ? counts.rewrites : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="type-section">Additions</p>
                    <p className="mono mt-0.5 text-xl font-bold text-state-ok">
                      {diff ? counts.additions : "—"}
                    </p>
                  </div>
                </div>
              }
              footnote={
                diff
                  ? `Changes Summary: ${counts.rewrites} rewrites · ${counts.additions} additions${formatIntact ? " · formatHash carried from base" : ""}`
                  : "Select a tailored version to see its change summary."
              }
            >
              {!selected ? (
                <p className="text-[13px] text-aether-muted-dim" data-testid="integrity-status">
                  Select a version to verify its layout against the immutable base.
                </p>
              ) : detailLoading ? (
                // Never print an "unknown"/"not preserved" verdict while the
                // verification call is still open — that is a claim, and we have
                // not asked yet.
                <p className="text-[13px] text-aether-muted-dim" data-testid="integrity-status">
                  Verifying this version against the immutable base…
                </p>
              ) : verifiedChangesDropped > 0 ? (
                // Derived from the VERIFIED report for this exact version, and
                // stated FIRST: it is the only measured fact in this panel, so it
                // outranks both the listing's mechanism flag and the hash
                // comparison — neither of which can see a missing rewrite.
                <p className="text-[13px] text-state-warn" data-testid="integrity-status">
                  {verifiedChangesDropped} of {fidelityCounts?.changesRequested} tailored changes
                  could not be applied to the file you download — this version is not a complete
                  tailored resume. The full wording is in the change summary below.
                </p>
              ) : !formatPreservationKnown ? (
                <p className="text-[13px] text-aether-muted-dim" data-testid="integrity-status">
                  Format preservation status is unknown for this version — we can&apos;t yet
                  confirm whether download will match your original layout.
                </p>
              ) : formatExplicitlyUnpreserved ? (
                <p className="text-[13px] text-state-warn" data-testid="integrity-status">
                  Format not preserved for this upload — download renders in the Aether standard
                  template, not your original layout.
                </p>
              ) : formatIntact ? (
                <p className="text-[13px] text-state-ok" data-testid="integrity-status">
                  Layout hash matches the base — typography, spacing, columns &amp; margins preserved.
                </p>
              ) : (
                <p className="text-[13px] text-state-warn" data-testid="integrity-status">
                  Layout hash differs from the base — review formatting before using this version.
                </p>
              )}
              {formatFidelity ? (
                // U2b (R-F2/R-F4): the API's OWN per-version report, not a
                // hard-coded string. A genuine docx-native preservation and a
                // low-confidence PDF re-flow used to render identical copy here,
                // which is exactly the silent claim R-F4 forbids.
                <p className="mt-2 text-[11px] leading-[1.5] text-aether-muted-dim" data-testid="format-fidelity-detail">
                  <span className="mono uppercase tracking-wide">{formatFidelity.method}</span>
                  {" · "}
                  {formatFidelity.confidence} confidence — {formatFidelity.note}
                </p>
              ) : null}
              {fidelityCounts ? (
                // The counts come from re-reading the file this version renders
                // to — not from what the tailoring run believed it changed.
                <p
                  className={`mt-2 text-[11px] leading-[1.5] ${
                    (fidelityCounts.changesDropped ?? 0) > 0 ? "text-state-warn" : "text-state-ok"
                  }`}
                  data-testid="format-fidelity-counts"
                >
                  {(fidelityCounts.changesDropped ?? 0) > 0
                    ? `Verified on the produced file: ${fidelityCounts.changesApplied ?? 0} of ${fidelityCounts.changesRequested} tailored changes applied — ${fidelityCounts.changesDropped} could not be applied to this layout (the full wording is in the change summary below).`
                    : `Verified on the produced file: all ${fidelityCounts.changesRequested} tailored changes are present in the document you download.`}
                </p>
              ) : null}
            </Section>

            {/* THE HONEST SCORECARD — 10 dimensions, before vs after. */}
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

            {ats ? (
              <Section
                eyebrow="ATS score"
                subtitle={`Deterministic keyword + semantic + experience evaluation vs ${ats.job_title ?? "target job"}${ats.company ? ` @ ${ats.company}` : ""}`}
                testId="ats-score-panel"
                action={
                  /* R-01 (round 3): `overall` is 0.4*keyword + 0.4*semantic +
                     0.2*experience, so a degraded semantic half makes this headline
                     40% neutral placeholder — the same value the "Semantic
                     similarity (40%)" row directly below already refuses to print. */
                  <span
                    className={`mono text-2xl font-bold ${
                      !semanticTrusted
                        ? "text-state-neutral"
                        : ats.overall >= 60
                          ? "text-state-ok"
                          : "text-state-warn"
                    }`}
                    data-testid="ats-overall"
                  >
                    {semanticTrusted ? ats.overall : "—"}
                  </span>
                }
                footnote={
                  ats.missing_keywords.length > 0 ? (
                    <>
                      Missing JD keywords:{" "}
                      <span className="mono text-state-warn">
                        {ats.missing_keywords.slice(0, 8).join(", ")}
                      </span>
                    </>
                  ) : undefined
                }
              >
                <div className="grid gap-3">
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
                      <div className="flex items-center justify-between gap-2 text-[11px] text-aether-muted">
                        <span>
                          {row.label}
                          {row.degraded ? (
                            <span
                              className={chip({ tone: "degraded", class: "ml-1.5" })}
                              data-testid="semantic-not-measured-badge"
                            >
                              not measured
                            </span>
                          ) : null}
                        </span>
                        <span className="mono">{row.degraded ? "—" : row.value}</span>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full bg-white/[0.07]">
                        <div
                          className={`h-1.5 rounded-full ${row.degraded ? "bg-state-neutral/40" : "bg-state-info"}`}
                          style={{
                            width: `${row.degraded ? 0 : Math.min(100, Math.max(0, row.value))}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                {!semanticTrusted ? (
                  <p className="mt-3 text-[11px] leading-[1.5] text-aether-muted-dim" data-testid="semantic-degraded-note">
                    Semantic similarity could not be measured for this score — a neutral
                    placeholder stood in instead. The overall ATS score is 40% built
                    from it, so it is shown as “—” rather than as a measurement until
                    semantic scoring is available again.
                  </p>
                ) : null}
              </Section>
            ) : null}

            {conversion ? (
              <Section
                eyebrow={
                  <span className="inline-flex items-center gap-1.5">
                    ATS Conversion Impact
                    {conversionDegraded ? (
                      <span
                        className={chip({ tone: "degraded" })}
                        data-testid="conversion-not-measured-badge"
                      >
                        not measured
                      </span>
                    ) : null}
                  </span>
                }
                testId="conversion-metrics"
                footnote={
                  conversionDegraded ? (
                    <span data-testid="conversion-degraded-note">
                      Semantic similarity could not be measured for the before/after re-score
                      — a neutral placeholder stood in instead, so this delta and the
                      conversion lift above should be treated as directional until scoring is
                      available again.
                    </span>
                  ) : undefined
                }
              >
                <p className="text-[13px] text-aether-muted" data-testid="conversion-before-after">
                  Before:{" "}
                  <span className="mono font-semibold text-aether-text">
                    {conversion.provenance === "degraded" ? "—" : `${conversion.baselineATSScore}%`}
                  </span>{" "}
                  → After:{" "}
                  <span className="mono font-semibold text-state-ok">
                    {conversion.provenance === "degraded" ? "—" : `${conversion.tailoredATSScore}%`}
                  </span>
                </p>
                <p className="mt-1.5 text-[13px]" data-testid="conversion-lift">
                  <MetricTooltip
                    label="Estimated interview conversion improvement"
                    value={
                      <span className="mono font-semibold text-state-ok">
                        {conversion.provenance === "degraded" ? "—" : conversion.estimatedConversionLift}
                      </span>
                    }
                    tooltip={`${conversion.methodology} This is an illustrative estimate, not a measured outcome.`}
                  />
                </p>
              </Section>
            ) : null}
            </div>
          </div>

          {/* PROVENANCE + TRACE — a full-width band under the two columns.
              It sat inside the right column and pushed the page to 2,649px
              at 1600 (D-ε budget ~2,500); nothing about the content or its
              wording changed, only which column it lives in. */}
          {/* PROVENANCE — base vs latest tailored identity, and the immutability
              contract. Always mounted: these are honesty rows, not decoration. */}
          <div
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
            data-design-id="panes-rs0405"
          >
            <Section
              eyebrow="Original — base resume"
              testId="pane-original"
              className="min-w-0"
              footnote="Base resume is immutable — every tailored version derives from this source of truth."
            >
              {originalIdentity ? (
                <>
                  <p
                    className="break-words text-[15px] font-semibold tracking-[-0.01em]"
                    data-testid="hero-original-name"
                  >
                    {originalIdentity.name}
                  </p>
                  <p className="break-words type-meta mt-0.5" data-testid="hero-original-title">
                    {originalIdentity.title}
                  </p>
                </>
              ) : (
                <p className="text-[13px] text-aether-muted-dim" data-testid="hero-original-empty">
                  No base resume yet.
                </p>
              )}
            </Section>
            <Section
              eyebrow="Tailored — latest version"
              testId="pane-tailored"
              accent
              className="min-w-0"
            >
              {tailoredIdentity ? (
                <>
                  <p
                    className="break-words text-[15px] font-semibold tracking-[-0.01em]"
                    data-testid="hero-tailored-name"
                  >
                    {tailoredIdentity.name}
                  </p>
                  <p className="type-meta mt-0.5">Keyword-aligned for the selected role</p>
                </>
              ) : (
                <p className="text-[13px] text-aether-muted-dim" data-testid="hero-tailored-empty">
                  No tailored version yet.
                </p>
              )}
              <div className="mt-2.5 flex min-w-0 flex-wrap gap-2">
                {tailoredResume ? (
                  <span className={chip({ tone: "ok", class: "max-w-full break-words" })}>
                    {tailoredResume.label}
                  </span>
                ) : (
                  <span className={chip({ tone: "neutral" })}>
                    No tailored version yet — run tailoring against a job
                  </span>
                )}
              </div>
            </Section>
            <Section
                eyebrow="Evidence trace"
                testId="evidence-trace"
                className="min-w-0"
                footnote="Every rewritten line links back to evidence in the base resume."
              >
                {diff && changes.length > 0 ? (
                  <ul className="space-y-2 text-[13px] text-aether-muted">
                    {changes.slice(0, 4).map((change, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 truncate">
                          {(() => {
                            const t = change.after || change.before;
                            return t.length > 60 ? `${t.slice(0, 60)}…` : t;
                          })()}
                        </span>
                        {change.evidenceRef ? (
                          <span className={chip({ tone: "info", mono: true })}>
                            {change.evidenceRef}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-aether-muted-dim">
                    Select a tailored version to trace its changes to evidence.
                  </p>
                )}
              </Section>
              <Section
                eyebrow="Version history"
                testId="version-history"
                className="min-w-0"
              >
                {resumes && resumes.length > 0 ? (
                  <ul className="space-y-2 text-[13px] text-aether-muted">
                    {resumes.slice(0, 4).map((r) => (
                      <li key={r.id} className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate">{r.label ?? `Version ${r.version}`}</span>
                        <span className="mono shrink-0 text-[11px] text-aether-muted-dim">
                          v{r.version}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-aether-muted-dim">No versions yet.</p>
                )}
              </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
