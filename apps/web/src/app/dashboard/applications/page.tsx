"use client";

/**
 * Application Tracker — canonical 8-stage pipeline (wireframe
 * application-tracker.html): Discovered / Evaluating / Tailoring / Ready to
 * Apply / Submitted / In Review / Interview / Offer.
 *
 * The first three stages are fed by the jobs pipeline (Job.status), the last
 * five by Application.status. Tracker metadata (follow-ups, interview rounds,
 * offer terms) rides in Application.answers. Rejected / withdrawn collapse
 * into a compact "Closed" strip. Views: Board / Sankey Flow (canonical
 * 847→412→156→23→4 funnel from GET /applications/funnel/sankey) / Timeline.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { submitApplication } from "../../../lib/api/applications";
import { createApproval, fetchApprovals, type Approval } from "../../../lib/api/approvals";
import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import { downloadResume } from "../../../lib/api/resumes";
import SankeyFlow from "../../../components/applications/SankeyFlow";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import {
  clearPipeline,
  fetchAgentConfig,
  fetchAppliedApplications,
  fetchSankey,
  fetchTrackerApplication,
  fetchTrackerApplications,
  moveApplication,
  movePipelineJob,
  type AgentConfig,
  type ClearPipelineResult,
  type SankeyData,
  type TrackerApplication,
} from "../../../components/applications/tracker-api";
import {
  FILTER_OPTIONS,
  SORT_OPTIONS,
  STAGE_DEFS,
  STAGE_TO_APP_STATUS,
  STAGE_TO_JOB_STATUS,
  buildStages,
  describeTransmission,
  fitClass,
  initials,
  manualStepLabel,
  moveTargetsFor,
  shortDate,
  timeAgo,
  viewStages,
  type FilterKey,
  type SortKey,
  type StageCard,
  type StageKey,
} from "../../../components/applications/tracker-lib";

type ViewMode = "board" | "sankey" | "timeline" | "applied";

/** Accessible dropdown for the header Filter / Sort controls. */
function HeaderMenu<K extends string>({
  icon,
  label,
  active,
  options,
  value,
  onSelect,
  testId,
}: {
  icon: string;
  label: string;
  active: boolean;
  options: ReadonlyArray<{ key: K; label: string }>;
  value: K;
  onSelect: (key: K) => void;
  testId: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = options.find((o) => o.key === value);
  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        data-testid={testId}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 rounded-lg border px-3.5 py-2 text-xs font-medium transition max-sm:min-h-[44px] ${
          active
            ? "border-aether-coral/30 bg-aether-coral/15 text-aether-coral"
            : "border-white/10 bg-white/5 hover:bg-white/10"
        }`}
      >
        <i className={`fa-solid ${icon} text-[10px]`} aria-hidden="true" />
        {active && current ? `${label}: ${current.label}` : label}
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={`${label} options`}
          className="absolute right-0 top-full z-20 mt-1 w-48 rounded-xl border border-white/10 bg-[#16161f] p-1 shadow-xl"
        >
          {options.map((o) => (
            <button
              key={o.key}
              type="button"
              role="menuitemradio"
              aria-checked={o.key === value}
              onClick={() => {
                onSelect(o.key);
                setOpen(false);
              }}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs transition max-sm:min-h-[44px] ${
                o.key === value
                  ? "bg-aether-coral/15 text-aether-coral"
                  : "text-aether-muted hover:bg-white/5 hover:text-white"
              }`}
            >
              {o.label}
              {o.key === value ? <i className="fa-solid fa-check text-[9px]" aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * FEAT-B2: accessible per-card "Move to…" menu — the keyboard/screen-reader
 * path for stage moves (drag-and-drop is the pointer path). Offers only the
 * legal targets for the card's half of the board (moveTargetsFor); the server
 * enforces the same matrix with 422s.
 */
function MoveMenu({
  card,
  stage,
  onMove,
}: {
  card: StageCard;
  stage: StageKey;
  onMove: (toStage: StageKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const targets = moveTargetsFor(card, stage);
  const labelOf = (key: StageKey) => STAGE_DEFS.find((d) => d.key === key)?.label ?? key;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (targets.length === 0) return null;
  return (
    <div
      className="relative"
      ref={rootRef}
      // The card itself is a click/Enter target (opens details) — keep the
      // menu's events from bubbling into it. Escape is handled here too,
      // because stopPropagation keeps it from the document listener.
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
        e.stopPropagation();
      }}
    >
      <button
        type="button"
        data-testid="move-menu-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Move ${card.title} at ${card.company} to another stage`}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-medium text-aether-muted transition hover:bg-white/10 hover:text-white max-sm:min-h-[36px]"
      >
        <i className="fa-solid fa-arrow-right-arrow-left text-[9px]" aria-hidden="true" />
        Move to…
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={`Move ${card.title} to stage`}
          className="absolute bottom-full left-0 z-20 mb-1 w-44 rounded-xl border border-white/10 bg-[#16161f] p-1 shadow-xl"
        >
          {targets.map((key) => (
            <button
              key={key}
              type="button"
              role="menuitem"
              data-testid={`move-option-${key}`}
              onClick={() => {
                setOpen(false);
                onMove(key);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-aether-muted transition hover:bg-white/5 hover:text-white max-sm:min-h-[44px]"
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${STAGE_DEFS.find((d) => d.key === key)?.dotClass ?? "bg-white/30"}`}
                aria-hidden="true"
              />
              {labelOf(key)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * W-SUB / U5 — says whether Aether actually TRANSMITTED this application, or
 * ran into an honest, actionable obstacle trying to.
 *
 * Ground truth this exists to correct: `Application.status = "submitted"`
 * records that the application was marked submitted, not that anything was
 * sent. Before W-SUB nothing in the product could send an application at all,
 * yet 86 production rows sat in the Submitted column with no qualification —
 * the product's biggest false claim. U5 added a second real transmission path
 * (a filled-out web form on the employer's own ATS, not just email) and the
 * NO-PREPARED-ONLY invariant: an approved application that could not be sent
 * must land in a visible manual-step state instead of sitting silently
 * "prepared" (U-PLAN "U5 MANDATE SHARPENED").
 *
 * History is not rewritten and the card is not moved. The badge simply states
 * which of the three happened. Any field this component reads degrades to
 * "don't claim it" when the API omits it (an older build), because inventing
 * an answer is exactly the failure mode being fixed.
 */
function SubmissionBadge({ app }: { app?: TrackerApplication }) {
  if (!app) return null;
  if (app.transmitted) {
    const t = describeTransmission(app);
    return (
      <span
        data-testid="submission-transmitted-badge"
        title={`${t.headline}${t.evidenceNote ? ` · ${t.evidenceNote}` : ""}.`}
        className="mt-2 inline-flex items-center gap-1 rounded-md bg-aether-green/15 px-2 py-0.5 text-[10px] text-aether-green"
      >
        <i className="fa-solid fa-paper-plane text-[9px]" aria-hidden="true" />
        Sent by Aether
      </span>
    );
  }
  if (app.manualStepReason) {
    return (
      <span
        data-testid="submission-manual-step-badge"
        title={
          app.manualStepDetail
            ? `${manualStepLabel(app.manualStepReason)}: "${app.manualStepDetail}"`
            : manualStepLabel(app.manualStepReason)
        }
        className="mt-2 inline-flex items-center gap-1 rounded-md bg-aether-coral/15 px-2 py-0.5 text-[10px] text-aether-coral"
      >
        <i className="fa-solid fa-triangle-exclamation text-[9px]" aria-hidden="true" />
        Manual step needed
      </span>
    );
  }
  if (app.transmitted == null) return null;
  return (
    <span
      data-testid="submission-not-transmitted-badge"
      title={
        "Aether did not send this application — it is recorded as prepared. " +
        (app.autoSubmittable
          ? "Approve it in Approvals to email it to the employer."
          : "This posting publishes no application email address. Approve it in Approvals and Aether will attempt to submit it automatically through the employer's own application form.")
      }
      className="mt-2 inline-flex items-center gap-1 rounded-md bg-aether-yellow/15 px-2 py-0.5 text-[10px] text-aether-yellow"
    >
      <i className="fa-solid fa-circle-info text-[9px]" aria-hidden="true" />
      Not sent by Aether
    </span>
  );
}

/** Stage-specific card footer line/badge (wireframe card-at13..at25). */
function CardMeta({
  card,
  stageKey,
  hasPendingApproval,
  onRequestApproval,
  requestingApproval,
}: {
  card: StageCard;
  stageKey: StageKey;
  /** P0-3: whether a LIVE pending approval exists for this draft. */
  hasPendingApproval?: boolean;
  /** P0-3: re-request handler (existing POST /approvals path). */
  onRequestApproval?: () => void;
  requestingApproval?: boolean;
}) {
  const { meta } = card;
  switch (stageKey) {
    case "evaluating":
      return card.fit != null ? (
        <div className="mt-2 h-1 rounded-full bg-white/10" aria-hidden="true">
          <div
            className="h-1 rounded-full bg-[#818CF8]"
            style={{ width: `${Math.min(card.fit, 100)}%` }}
          />
        </div>
      ) : null;
    case "tailoring":
      return <p className="mono mt-2 text-[10px] text-aether-coral">tailoring resume…</p>;
    case "ready":
      // U5: a manual-step application WAS approved and Aether DID attempt it —
      // its ApprovalRequest.status is 'approved', not 'pending', so it never
      // matches `hasPendingApproval` below. Without this branch first, the
      // card would show the misleading "no pending approval / Request
      // approval" pair, implying nothing had happened yet when Aether ran
      // into a real, honest obstacle. Checked before the pending-approval
      // branches so it always wins for a card in this state.
      if (card.app?.manualStepReason) {
        return (
          <span
            data-testid="ready-manual-step-badge"
            title={
              card.app.manualStepDetail
                ? `${manualStepLabel(card.app.manualStepReason)}: "${card.app.manualStepDetail}"`
                : manualStepLabel(card.app.manualStepReason)
            }
            className="mt-2 inline-flex items-center gap-1 rounded-md bg-aether-coral/15 px-2 py-0.5 text-[10px] text-aether-coral"
          >
            <i className="fa-solid fa-triangle-exclamation text-[9px]" aria-hidden="true" />
            {manualStepLabel(card.app.manualStepReason)}
          </span>
        );
      }
      // P0-3 deadlock fix: the old static "needs approval" badge lied when the
      // approval had expired/been purged (48h window) — the draft then had NO
      // route back into the queue. Show the badge only for a LIVE pending
      // approval; otherwise surface the EXISTING re-request path
      // (POST /approvals, idempotent per job+kind).
      return hasPendingApproval ? (
        <span
          data-testid="needs-approval-badge"
          className="mt-2 inline-block rounded-md bg-aether-yellow/15 px-2 py-0.5 text-[10px] text-aether-yellow"
        >
          needs approval
        </span>
      ) : (
        <span className="mt-2 flex flex-wrap items-center gap-1.5">
          <span
            data-testid="approval-expired-badge"
            className="inline-block rounded-md bg-aether-coral/15 px-2 py-0.5 text-[10px] text-aether-coral"
          >
            no pending approval
          </span>
          {onRequestApproval ? (
            <button
              type="button"
              data-testid="request-approval-button"
              disabled={requestingApproval}
              onClick={(e) => {
                e.stopPropagation();
                onRequestApproval();
              }}
              className="rounded-md border border-white/15 px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-white/30 hover:text-white disabled:opacity-50"
            >
              {requestingApproval ? "Requesting..." : "Request approval"}
            </button>
          ) : null}
        </span>
      );
    case "submitted":
      // W-SUB — the single most-repeated false claim in this product was the
      // Submitted column: 86 rows read "submitted" while Aether had never
      // transmitted anything anywhere. The stored status is history and is
      // NOT rewritten; what changes is that the card now states which of the
      // two very different things actually happened.
      return (
        <>
          <SubmissionBadge app={card.app} />
          {meta.followUpSentAt ? (
            <div className="mt-2 flex items-center gap-1.5 text-[10px] text-aether-green">
              <i className="fa-solid fa-clock text-[9px]" aria-hidden="true" />
              Follow-up sent ✓
            </div>
          ) : null}
        </>
      );
    case "in-review":
      return meta.autoFollowUpInDays != null ? (
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-aether-yellow">
          <i className="fa-solid fa-clock text-[9px]" aria-hidden="true" />
          Auto follow-up in {meta.autoFollowUpInDays} day{meta.autoFollowUpInDays === 1 ? "" : "s"}
        </div>
      ) : null;
    case "interview":
      return meta.interviewRound != null ? (
        <span className="mt-2 inline-block rounded-md bg-aether-amber/15 px-2 py-0.5 text-[10px] text-aether-amber">
          round {meta.interviewRound}
          {meta.interviewDate ? ` · ${shortDate(meta.interviewDate)}` : ""}
        </span>
      ) : null;
    case "offer":
      return meta.offerAmount ? (
        <p className="mono mt-2 text-[10px] text-aether-green">
          {meta.offerAmount}
          {meta.offerDeadline ? ` · decide by ${shortDate(meta.offerDeadline)}` : ""}
        </p>
      ) : null;
    default:
      return null;
  }
}

/** Cross-links: email thread (Submitted / In Review), CRM (Interview / Offer). */
function CardLink({ stageKey }: { stageKey: StageKey }) {
  if (stageKey === "submitted" || stageKey === "in-review") {
    return (
      <Link
        href="/dashboard/email"
        onClick={(e) => e.stopPropagation()}
        className="mt-2 inline-flex items-center gap-1 rounded text-[10px] text-[#818CF8] transition hover:text-white"
      >
        <i className="fa-solid fa-envelope text-[9px]" aria-hidden="true" />
        View Email Thread
        <i className="fa-solid fa-arrow-right text-[8px]" aria-hidden="true" />
      </Link>
    );
  }
  if (stageKey === "interview" || stageKey === "offer") {
    return (
      <Link
        href="/dashboard/networking"
        onClick={(e) => e.stopPropagation()}
        className="mt-2 inline-flex items-center gap-1 rounded text-[10px] text-[#818CF8] transition hover:text-white"
      >
        <i className="fa-solid fa-address-book text-[9px]" aria-hidden="true" />
        View in CRM
        <i className="fa-solid fa-arrow-right text-[8px]" aria-hidden="true" />
      </Link>
    );
  }
  return null;
}

export default function ApplicationsPage() {
  const [apps, setApps] = useState<TrackerApplication[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  // The full pending-approvals list — not just a count — so the
  // "Needs approval" filter (MV-application-tracker-002) can match the
  // EXACT same set the banner counts, instead of a status==='draft'
  // heuristic that can silently disagree with it.
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([]);
  const pendingCount = pendingApprovals.length;
  const pendingApprovalIds = new Set(
    pendingApprovals
      .map((a) => a.applicationId)
      .filter((id): id is string => Boolean(id)),
  );
  // P0-3: per-card busy flag while re-requesting an approval.
  const [requestingApprovalId, setRequestingApprovalId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TrackerApplication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<ViewMode>("board");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("recent");
  const [sankey, setSankey] = useState<SankeyData | null>(null);
  const [sankeyError, setSankeyError] = useState<string | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);
  // Phase 4: separate applied-jobs view — fetched lazily on first open.
  const [appliedApps, setAppliedApps] = useState<TrackerApplication[] | null>(null);
  const [appliedError, setAppliedError] = useState<string | null>(null);

  // Clear Pipeline confirmation gate — mirrors the bulk-apply gate pattern
  // from the Jobs page (MV-job-discovery-002): irreversible action, explicit
  // confirm required, focus trap + ESC-close.
  const [clearGateOpen, setClearGateOpen] = useState(false);
  const [clearSubmitting, setClearSubmitting] = useState(false);
  const [clearResult, setClearResult] = useState<ClearPipelineResult | null>(null);
  const clearGateTriggerRef = useRef<HTMLElement | null>(null);
  const clearGateConfirmRef = useRef<HTMLButtonElement | null>(null);

  const load = useCallback(async () => {
    try {
      setApps(await fetchTrackerApplications());
      setError(null);
      try {
        setJobs(await apiRequest<Job[]>("/jobs"));
      } catch {
        /* pipeline stages are progressive enhancement */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load applications");
      setApps([]);
    }
    // Pending-approvals banner + "Needs approval" filter (REQ-TM-04,
    // MV-application-tracker-002) — non-fatal if it fails.
    try {
      setPendingApprovals(await fetchApprovals("pending"));
    } catch {
      // Keep the last known list.
    }
    // Auto-apply guardrail state — banner falls back to generic copy.
    try {
      setAgentConfig(await fetchAgentConfig());
    } catch {
      // Keep the last known config.
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // W-RT — the shared realtime channel. The board's cards are built from Job
  // AND Application rows, and the approvals queue gates the last stages, so all
  // three are subscribed: a stage advanced by an agent (or by another tab)
  // lands here as soon as the server observes it rather than on the next poll.
  useRealtimeResources(["applications", "jobs", "approvals"], () => {
    void load();
  });

  // Real-time board sync (HOTFIX realtime-board-refresh): the pipeline's
  // first 3 stages (Discovered/Evaluating/Tailoring) are agent-driven —
  // scout, fit-scorer and the board sweep advance Job.status server-side on
  // their own schedule, with no user click in this tab to trigger a refetch.
  // Without a periodic reload those cards visibly sit in a stale stage until
  // the user manually reloads the page. Poll every 20s, paused while the tab
  // is hidden, mirroring the existing sidebar.tsx (30s) / topbar.tsx (60s)
  // idiom and the identical fix applied to the Jobs page.
  useEffect(() => {
    if (typeof document === "undefined") return;
    let cancelled = false;
    const tick = () => {
      if (document.visibilityState !== "visible" || cancelled) return;
      void load();
    };
    const timer = window.setInterval(tick, 20_000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [load]);

  // Canonical sankey loads lazily the first time the view is opened.
  useEffect(() => {
    if (view !== "sankey" || sankey !== null) return;
    fetchSankey()
      .then((d) => {
        setSankey(d);
        setSankeyError(null);
      })
      .catch((e) => {
        setSankeyError(e instanceof Error ? e.message : "Failed to load sankey data");
      });
  }, [view, sankey]);

  // Applied jobs — lazily loaded on first view (phase4).
  useEffect(() => {
    if (view !== "applied" || appliedApps !== null) return;
    fetchAppliedApplications()
      .then((d) => {
        setAppliedApps(d);
        setAppliedError(null);
      })
      .catch((e) => {
        setAppliedError(e instanceof Error ? e.message : "Failed to load applied jobs");
      });
  }, [view, appliedApps]);

  const openDetail = async (id: string) => {
    try {
      setDetail(await fetchTrackerApplication(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load application");
    }
  };

  const markSubmitted = async (app: TrackerApplication) => {
    setSubmitting(true);
    try {
      await submitApplication(app.id, app.applyUrl ?? null);
      setDetail(await fetchTrackerApplication(app.id));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to mark as submitted");
    } finally {
      setSubmitting(false);
    }
  };

  // Clear Pipeline gate — mirrored from the bulk-apply confirmation gate
  // pattern on the Jobs page (MV-job-discovery-002 § lines 562-621).
  const openClearGate = (trigger: HTMLElement | null) => {
    clearGateTriggerRef.current = trigger;
    setClearResult(null);
    setClearGateOpen(true);
  };
  const closeClearGate = useCallback(() => {
    setClearGateOpen(false);
    clearGateTriggerRef.current?.focus?.();
  }, []);

  const confirmClearPipeline = async () => {
    setClearSubmitting(true);
    setError(null);
    try {
      const result = await clearPipeline();
      setClearResult(result);
      // Reload the board immediately so it shows the empty state.
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear pipeline");
      setClearGateOpen(false);
    } finally {
      setClearSubmitting(false);
    }
  };

  // Modal a11y: focus the confirm button on open; ESC closes.
  useEffect(() => {
    if (!clearGateOpen) return;
    clearGateConfirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeClearGate();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [clearGateOpen, closeClearGate]);

  // P0-3: re-request an approval for a draft stuck in "Ready to Apply" with
  // no live pending approval (expired/purged). Uses the EXISTING
  // POST /approvals path — idempotent server-side per (job, kind, pending).
  const requestApproval = async (card: StageCard) => {
    const app = card.app;
    if (!app || requestingApprovalId) return;
    setRequestingApprovalId(app.id);
    try {
      await createApproval({
        type: "application_submit",
        application_id: app.id,
        payload: {
          job_id: app.jobId,
          job_title: card.title,
          company: card.company,
          agent: "tracker",
          action: "submit_application",
        },
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to request approval");
    } finally {
      setRequestingApprovalId(null);
    }
  };

  /**
   * FEAT-B2: move a card to another stage — optimistic local update, honest
   * rollback on failure, then a full reload so column counts, badges and the
   * closed strip reconcile against the server.
   */
  const moveCard = async (card: StageCard, fromStage: StageKey, toStage: StageKey) => {
    if (toStage === fromStage) return;
    if (!moveTargetsFor(card, fromStage).includes(toStage)) {
      // Honest client-side mirror of the server's 422 split: application
      // cards live in Ready→Offer, agent-pipeline job cards in
      // Discovered→Tailoring.
      setError(
        card.app
          ? `"${card.title}" is a live application — it can only move between Ready to Apply, Submitted, In Review, Interview and Offer.`
          : `"${card.title}" is still in the agent pipeline — it can only move between Discovered, Evaluating and Tailoring.`,
      );
      return;
    }
    const prevApps = apps;
    const prevJobs = jobs;
    try {
      if (card.app) {
        const nextStatus = STAGE_TO_APP_STATUS[toStage];
        if (!nextStatus) return;
        const appId = card.app.id;
        setApps((cur) => cur?.map((a) => (a.id === appId ? { ...a, status: nextStatus } : a)) ?? cur);
        await moveApplication(appId, toStage);
      } else {
        const nextStatus = STAGE_TO_JOB_STATUS[toStage];
        if (!nextStatus) return;
        const jobId = card.id.replace(/^job-/, "");
        setJobs((cur) => cur.map((j) => (j.id === jobId ? { ...j, status: nextStatus } : j)));
        await movePipelineJob(jobId, toStage);
      }
      setError(null);
      await load();
    } catch (e) {
      // Roll back the optimistic update — never leave the board showing a
      // move the server rejected.
      setApps(prevApps);
      setJobs(prevJobs);
      setError(e instanceof Error ? e.message : "Failed to move card");
    }
  };

  /** FEAT-B2 drag-and-drop: card → column via the HTML5 DnD API. */
  const onCardDragStart = (e: React.DragEvent, card: StageCard, stage: StageKey) => {
    e.dataTransfer.setData(
      "application/json",
      JSON.stringify({ cardId: card.id, fromStage: stage }),
    );
    e.dataTransfer.effectAllowed = "move";
  };

  const onColumnDrop = (e: React.DragEvent, toStage: StageKey) => {
    e.preventDefault();
    let payload: { cardId?: string; fromStage?: string };
    try {
      payload = JSON.parse(e.dataTransfer.getData("application/json")) as {
        cardId?: string;
        fromStage?: string;
      };
    } catch {
      return;
    }
    if (!payload.cardId || !payload.fromStage) return;
    const fromStage = payload.fromStage as StageKey;
    const card = stages
      .find((s) => s.key === fromStage)
      ?.cards.find((c) => c.id === payload.cardId);
    if (!card) return;
    void moveCard(card, fromStage, toStage);
  };

  const stages = viewStages(buildStages(apps ?? [], jobs), filter, sort, pendingApprovalIds);
  const closed = (apps ?? []).filter((a) => a.status === "rejected" || a.status === "withdrawn");
  const activeCount = stages.reduce((n, s) => n + s.cards.length, 0);
  // Pipeline job cards live in the first 3 columns (Discovered / Evaluating /
  // Tailoring) — the agent-fed half of the board. Only show the Clear Pipeline
  // button when there is at least one such card to clear; an empty pipeline
  // should not offer a destructive button with nothing to act on.
  const pipelineJobCount = stages
    .filter((s) => s.key === "discovered" || s.key === "evaluating" || s.key === "tailoring")
    .reduce((n, s) => n + s.cards.length, 0);
  const autoApplyOn = agentConfig?.autoApply ?? false;
  const threshold = agentConfig?.matchThreshold ?? 85;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">Application Tracker</h1>
          <p className="mono mt-1 text-xs text-aether-muted-dim" data-testid="tracker-subtitle">
            {/* MV-adv-A-001: this counts every board card — sourced jobs still
                pre-application PLUS non-closed applications (incl. drafts) —
                which is NOT the canonical submitted-application count the
                dashboard/mobile/analytics surfaces show. Label it honestly as
                a pipeline count so "applications" is never overloaded with
                two different numbers under the same name. */}
            {activeCount} pipeline item{activeCount === 1 ? "" : "s"} across 8 stages
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex rounded-lg border border-white/10 bg-white/5 p-0.5"
            role="tablist"
            aria-label="Tracker views"
          >
            {(
              [
                { key: "board", label: "Board View", icon: null },
                { key: "sankey", label: "Sankey Flow", icon: "fa-diagram-project" },
                { key: "timeline", label: "Timeline", icon: null },
                { key: "applied", label: "Applied", icon: "fa-check-circle" },
              ] as Array<{ key: ViewMode; label: string; icon: string | null }>
            ).map((v) => (
              <button
                key={v.key}
                type="button"
                role="tab"
                aria-selected={view === v.key}
                data-testid={`view-${v.key}`}
                onClick={() => setView(v.key)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition max-sm:min-h-[44px] ${
                  view === v.key
                    ? "bg-aether-coral/15 text-aether-coral"
                    : "text-aether-muted hover:text-white"
                }`}
              >
                {v.icon ? (
                  <i className={`fa-solid ${v.icon} mr-1.5 text-[10px]`} aria-hidden="true" />
                ) : null}
                {v.label}
              </button>
            ))}
          </div>
          <HeaderMenu
            icon="fa-filter"
            label="Filter"
            testId="filter-btn"
            active={filter !== "all"}
            options={FILTER_OPTIONS}
            value={filter}
            onSelect={setFilter}
          />
          <HeaderMenu
            icon="fa-arrow-down-wide-short"
            label="Sort"
            testId="sort-btn"
            active={sort !== "recent"}
            options={SORT_OPTIONS}
            value={sort}
            onSelect={setSort}
          />
          {view === "board" && pipelineJobCount > 0 ? (
            <button
              type="button"
              data-testid="clear-pipeline-btn"
              onClick={(e) => openClearGate(e.currentTarget)}
              aria-label={`Clear pipeline — archive ${pipelineJobCount} pipeline job${
                pipelineJobCount === 1 ? "" : "s"
              } in Discovered, Evaluating and Tailoring`}
              className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3.5 py-2 text-xs font-medium text-red-300 transition hover:bg-red-500/20 hover:text-red-200 max-sm:min-h-[44px]"
            >
              <i className="fa-solid fa-trash-can text-[10px]" aria-hidden="true" />
              Clear Pipeline
              <span className="mono text-[10px] text-red-400/70">{pipelineJobCount}</span>
            </button>
          ) : null}
        </div>
      </header>

      <div
        className="flex items-start gap-3 rounded-xl border border-aether-yellow/25 bg-aether-yellow/[0.08] px-4 py-3"
        data-testid="auto-apply-banner"
      >
        <i className="fa-solid fa-shield-halved mt-0.5 text-aether-yellow" aria-hidden="true" />
        <p className="text-xs leading-relaxed text-aether-muted">
          <span className="font-semibold text-aether-yellow">
            Auto-apply is a high-risk action.
          </span>{" "}
          Only applications with <span className="mono text-white">Match Score &gt; {threshold}%</span>{" "}
          and your explicit approval will be submitted. Auto-apply is currently{" "}
          <span className="font-medium text-white">{autoApplyOn ? "on" : "off"}</span>.
        </p>
      </div>

      {pendingCount > 0 ? (
        <Link
          href="/dashboard/approvals"
          data-testid="pending-approvals-banner"
          className="block rounded-xl border border-aether-amber/40 bg-aether-amber/10 p-3 text-sm text-aether-amber transition hover:bg-aether-amber/20"
        >
          {pendingCount} item{pendingCount === 1 ? "" : "s"} need{pendingCount === 1 ? "s" : ""} your
          review → open the Approvals queue
        </Link>
      ) : null}

      {error ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
          <p className="text-sm text-red-300">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 max-sm:min-h-[44px]"
          >
            Retry
          </button>
        </div>
      ) : null}

      {detail ? (
        <aside
          data-testid="application-detail-panel"
          className="glass rounded-2xl border border-aether-violet/40 p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">
                {detail.jobTitle} <span className="text-aether-muted">@ {detail.company}</span>
              </h2>
              <p className="mono mt-1 text-xs text-aether-muted-dim">
                status: {detail.status} · resume version: {detail.resumeId} · updated{" "}
                {new Date(detail.updatedAt).toLocaleString("en-AU")}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDetail(null)}
              aria-label="Close application details"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted-dim transition hover:bg-white/10 hover:text-white max-sm:h-11 max-sm:w-11"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
          {/* W-SUB / U5: the detail panel states, in words, whether Aether
              actually transmitted this application — the claim the "status:
              submitted" line above cannot make on its own — and, per the
              NO-PREPARED-ONLY invariant, the exact honest obstacle when it
              tried and could not. */}
          {detail.transmitted != null ? (
            <p
              data-testid="application-transmission-line"
              className={`mt-2 text-xs ${
                detail.transmitted ? "text-aether-green" : "text-aether-yellow"
              }`}
            >
              {detail.transmitted
                ? describeTransmission(detail).headline +
                  (describeTransmission(detail).evidenceNote
                    ? ` · ${describeTransmission(detail).evidenceNote}`
                    : "")
                : detail.manualStepReason
                  ? // The manual-step block below carries the full detail —
                    // this line just states the top-level fact plainly.
                    "Not sent by Aether — Aether tried and ran into an obstacle. See below."
                  : detail.autoSubmittable
                    ? "Not sent by Aether — prepared only. Approve it in Approvals to email it to the employer."
                    : "Not sent by Aether — prepared only. This posting publishes no application email address. Approve it in Approvals and Aether will attempt to submit it automatically through the employer's own application form."}
            </p>
          ) : null}
          {detail.transmitted && describeTransmission(detail).evidenceUrl ? (
            <a
              href={describeTransmission(detail).evidenceUrl ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="application-evidence-link"
              className="mt-1 inline-flex items-center gap-1 text-xs text-aether-green underline decoration-dotted"
            >
              View submission evidence ↗
            </a>
          ) : null}
          {/* U5 NO-PREPARED-ONLY: the honest actionable state — the employer's
              own verbatim question/obstacle, never a paraphrase, plus a
              one-click assist package (the same tailored artifacts Aether
              already prepared) so the user can finish it themselves. */}
          {!detail.transmitted && detail.manualStepReason ? (
            <div
              data-testid="application-manual-step-block"
              className="mt-3 rounded-xl border border-aether-coral/30 bg-aether-coral/10 p-3"
            >
              <p className="flex items-center gap-1.5 text-xs font-semibold text-aether-coral">
                <i className="fa-solid fa-triangle-exclamation text-[10px]" aria-hidden="true" />
                {manualStepLabel(detail.manualStepReason)}
              </p>
              {detail.manualStepDetail ? (
                <p
                  data-testid="application-manual-step-detail"
                  className="mt-1.5 text-xs italic leading-relaxed text-aether-muted"
                >
                  &ldquo;{detail.manualStepDetail}&rdquo;
                </p>
              ) : null}
              {detail.manualStepAt ? (
                <p className="mt-1 text-[10px] text-aether-muted-dim">
                  Aether attempted this {shortDate(detail.manualStepAt)}
                </p>
              ) : null}
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  data-testid="manual-step-download-resume-btn"
                  onClick={() => void downloadResume(detail.resumeId)}
                  className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-aether-muted transition hover:border-white/30 hover:text-white"
                >
                  <i className="fa-solid fa-download mr-1.5 text-[10px]" aria-hidden="true" />
                  Download tailored résumé
                </button>
                {detail.applyUrl && !detail.applyUrl.includes("demo.aether.dev") ? (
                  <a
                    href={detail.applyUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-aether-muted transition hover:border-white/30 hover:text-white"
                  >
                    Open posting to finish it yourself ↗
                  </a>
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {detail.applyUrl && !detail.applyUrl.includes("demo.aether.dev") ? (
              <a
                href={detail.applyUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="application-apply-link"
                className="rounded-lg border border-aether-green/40 px-3 py-1.5 text-sm font-semibold text-aether-green transition hover:bg-aether-green/10"
              >
                Apply on company site ↗
              </a>
            ) : null}
            {detail.status === "draft" ? (
              <button
                type="button"
                data-testid="mark-submitted-btn"
                onClick={() => void markSubmitted(detail)}
                disabled={submitting}
                className="rounded-lg bg-aether-coral px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? "Saving..." : "Mark as submitted"}
              </button>
            ) : null}
          </div>
          {detail.coverLetter ? (
            <div className="mt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-aether-muted">
                Cover letter
              </h3>
              <p className="mt-1 max-h-56 overflow-y-auto whitespace-pre-line rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-aether-muted">
                {detail.coverLetter}
              </p>
            </div>
          ) : (
            <p className="mt-3 text-sm text-aether-muted-dim">No cover letter attached.</p>
          )}
        </aside>
      ) : null}

      {apps === null ? (
        <div className="grid gap-4 md:grid-cols-4" aria-busy="true" data-testid="board-skeleton">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass h-64 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : view === "board" ? (
        <>
          <div className="overflow-x-auto pb-2" data-testid="applications-kanban">
            <div className="flex w-max gap-4">
              {stages.map((stage) => (
                <section
                  key={stage.key}
                  data-testid={`kanban-column-${stage.key}`}
                  aria-label={`${stage.label} stage, ${stage.cards.length} cards`}
                  className="w-[260px] shrink-0"
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                  }}
                  onDrop={(e) => onColumnDrop(e, stage.key)}
                >
                  <header className="mb-3 flex items-center justify-between px-1">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${stage.dotClass}`} aria-hidden="true" />
                      <h2 className="text-xs font-semibold">{stage.label}</h2>
                    </div>
                    <span className="mono text-[11px] text-aether-muted-dim">
                      {stage.cards.length}
                    </span>
                  </header>
                  <div className="flex flex-col gap-2.5">
                    {stage.cards.length === 0 ? (
                      <p className="glass rounded-xl border border-dashed border-white/10 px-1 py-6 text-center text-xs text-aether-muted-dim">
                        Empty
                      </p>
                    ) : (
                      stage.cards.slice(0, 25).map((card) => {
                        const clickable = Boolean(card.app);
                        return (
                          <article
                            key={card.id}
                            data-testid="application-card"
                            draggable
                            onDragStart={(e) => onCardDragStart(e, card, stage.key)}
                            onClick={clickable ? () => void openDetail(card.app!.id) : undefined}
                            className={`glass rounded-xl border p-3.5 transition ${
                              stage.key === "tailoring"
                                ? "border-aether-coral/25"
                                : stage.key === "offer"
                                  ? "border-aether-green/30 bg-white/[0.05]"
                                  : stage.key === "interview"
                                    ? "border-aether-amber/25"
                                    : "border-white/10"
                            } ${clickable ? "cursor-pointer hover:border-white/25" : "hover:border-white/15"}`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                                  {initials(card.company)}
                                </span>
                                {card.fit != null ? (
                                  <span
                                    className={`mono text-[11px] font-semibold ${fitClass(card.fit)}`}
                                    title="Match score"
                                  >
                                    {card.fit}
                                  </span>
                                ) : null}
                                {card.atsScore != null ? (
                                  <span
                                    className="mono text-[11px] font-semibold text-aether-violet"
                                    title="ATS score"
                                    data-testid="tracker-ats-score"
                                  >
                                    ATS {card.atsScore}
                                  </span>
                                ) : null}
                              </div>
                              <span
                                className={`flex h-5 w-5 items-center justify-center rounded-full ${stage.iconClass}`}
                                title={stage.label}
                              >
                                <i
                                  className={`fa-solid ${stage.icon} text-[9px]`}
                                  aria-hidden="true"
                                />
                              </span>
                            </div>
                            <h3 className="mt-2.5 text-xs font-semibold leading-tight">
                              {clickable ? (
                                /* Keyboard path for opening details — the card
                                   <article> stays a mouse-only convenience so
                                   the MoveMenu buttons are not nested inside a
                                   role="button" (axe nested-interactive, W-E). */
                                <button
                                  type="button"
                                  aria-label={`${card.title} at ${card.company}, open details`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void openDetail(card.app!.id);
                                  }}
                                  className="max-w-full text-left"
                                >
                                  {card.title}
                                </button>
                              ) : (
                                card.title
                              )}
                            </h3>
                            <p className="text-[11px] text-aether-muted-dim">{card.company}</p>
                            <CardMeta
                              card={card}
                              stageKey={stage.key}
                              hasPendingApproval={
                                card.app != null && pendingApprovalIds.has(card.app.id)
                              }
                              onRequestApproval={
                                card.app ? () => void requestApproval(card) : undefined
                              }
                              requestingApproval={
                                card.app != null && requestingApprovalId === card.app.id
                              }
                            />
                            <CardLink stageKey={stage.key} />
                            <div className="mt-2 flex items-center justify-between gap-2">
                              <p className="mono text-[10px] text-aether-muted-dim">
                                {timeAgo(card.updatedAt)}
                              </p>
                              <MoveMenu
                                card={card}
                                stage={stage.key}
                                onMove={(toStage) => void moveCard(card, stage.key, toStage)}
                              />
                            </div>
                          </article>
                        );
                      })
                    )}
                    {stage.cards.length > 25 ? (
                      <p className="px-1 text-center text-xs text-aether-muted-dim">
                        +{stage.cards.length - 25} more
                      </p>
                    ) : null}
                  </div>
                </section>
              ))}
            </div>
          </div>
          {closed.length > 0 ? (
            <section className="glass rounded-2xl border border-white/10 p-4" data-testid="closed-strip">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                Closed ({closed.length})
              </h2>
              <div className="flex flex-wrap gap-2">
                {closed.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => void openDetail(a.id)}
                    className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-aether-muted-dim transition hover:border-white/25 hover:text-white max-sm:min-h-[44px]"
                  >
                    {a.jobTitle} · {a.company} · {a.status}
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : view === "sankey" ? (
        <section data-testid="sankey-view">
          <div className="flex items-center gap-2.5">
            <i className="fa-solid fa-diagram-project text-sm text-[#818CF8]" aria-hidden="true" />
            <h2 className="text-[15px] font-semibold">Sankey Flow</h2>
            <span className="text-[11px] text-aether-muted-dim">
              application flow &amp; drop-off across stages
            </span>
          </div>
          {sankey ? (
            <SankeyFlow data={sankey} />
          ) : sankeyError ? (
            <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
              <p className="text-sm text-red-300">{sankeyError}</p>
              <button
                type="button"
                onClick={() => {
                  setSankeyError(null);
                  fetchSankey()
                    .then(setSankey)
                    .catch((e) =>
                      setSankeyError(e instanceof Error ? e.message : "Failed to load sankey data"),
                    );
                }}
                className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 max-sm:min-h-[44px]"
              >
                Retry
              </button>
            </div>
          ) : (
            <div
              className="glass mt-4 h-72 animate-pulse rounded-2xl border border-white/10"
              aria-busy="true"
            />
          )}
        </section>
      ) : view === "applied" ? (
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="applied-view">
          <div className="flex items-center gap-2.5 mb-4">
            <i className="fa-solid fa-check-circle text-sm text-aether-green" aria-hidden="true" />
            <h2 className="text-[15px] font-semibold">Applied Jobs</h2>
            <span className="text-[11px] text-aether-muted-dim">
              jobs you&apos;ve applied to — they stay here for your records
            </span>
          </div>
          {appliedApps === null ? (
            <div
              className="glass h-48 animate-pulse rounded-2xl border border-white/10"
              aria-busy="true"
            />
          ) : appliedError ? (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
              <p className="text-sm text-red-300">{appliedError}</p>
              <button
                type="button"
                onClick={() => {
                  setAppliedError(null);
                  setAppliedApps(null);
                }}
                className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 max-sm:min-h-[44px]"
              >
                Retry
              </button>
            </div>
          ) : appliedApps.length === 0 ? (
            <p className="text-sm text-aether-muted-dim">No applied jobs yet.</p>
          ) : (
            <div className="space-y-3">
              {appliedApps.map((a) => (
                <article
                  key={a.id}
                  className="glass rounded-xl border border-white/10 p-3.5 cursor-pointer hover:border-white/25 transition"
                  onClick={() => void openDetail(a.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                        {initials(a.company)}
                      </span>
                      {a.fitScore != null ? (
                        <span
                          className={`mono text-[11px] font-semibold ${fitClass(Math.round(Number(a.fitScore)))}`}
                          title="Match score"
                        >
                          {Math.round(Number(a.fitScore))}
                        </span>
                      ) : null}
                      {a.atsScore != null ? (
                        <span
                          className="mono text-[11px] font-semibold text-aether-violet"
                          title="ATS score"
                          data-testid="tracker-ats-score"
                        >
                          ATS {Math.round(Number(a.atsScore))}
                        </span>
                      ) : null}
                    </div>
                    <span className="flex items-center gap-1.5 rounded-md bg-aether-green/15 px-2 py-0.5 text-[10px] text-aether-green">
                      <i className="fa-solid fa-check text-[9px]" aria-hidden="true" />
                      applied
                    </span>
                  </div>
                  <h3 className="mt-2.5 text-xs font-semibold leading-tight">{a.jobTitle}</h3>
                  <p className="text-[11px] text-aether-muted-dim">{a.company}</p>
                  {/* U5: "applied" above only means the job moved into the
                      applied bucket — it does NOT say Aether transmitted
                      anything. This history view is exactly where that
                      distinction matters most, so the same honest badge the
                      board's Submitted column uses renders here too. */}
                  <SubmissionBadge app={a} />
                  {a.applyUrl && !a.applyUrl.includes("demo.aether.dev") ? (
                    <a
                      href={a.applyUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="mt-2 inline-flex items-center gap-1 rounded text-[10px] text-[#818CF8] transition hover:text-white"
                    >
                      View listing <i className="fa-solid fa-arrow-right text-[8px]" aria-hidden="true" />
                    </a>
                  ) : null}
                  <p className="mono mt-2 text-[10px] text-aether-muted-dim">
                    {timeAgo(a.updatedAt)}
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : (
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="timeline-view">
          <h2 className="mb-4 text-[15px] font-semibold">Timeline</h2>
          {(apps ?? []).length === 0 ? (
            <p className="text-sm text-aether-muted-dim">No applications yet.</p>
          ) : (
            <ol className="space-y-3 border-l border-white/10 pl-4">
              {[...(apps ?? [])]
                .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
                .map((a) => (
                  <li key={a.id} className="relative">
                    <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-aether-coral" />
                    <button
                      type="button"
                      onClick={() => void openDetail(a.id)}
                      className="rounded text-left text-sm transition hover:text-aether-coral"
                    >
                      <span className="font-semibold">{a.jobTitle}</span>{" "}
                      <span className="text-aether-muted">@ {a.company}</span>
                    </button>
                    <p className="mono text-[11px] text-aether-muted-dim">
                      {a.status} · {timeAgo(a.updatedAt)}
                    </p>
                  </li>
                ))}
            </ol>
          )}
        </section>
      )}

      {/* Clear Pipeline confirmation gate — mirrors the bulk-apply gate
          pattern from the Jobs page (MV-job-discovery-002): irreversible
          action, explicit confirm, focus trap + ESC-close a11y. */}
      {clearGateOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" data-testid="clear-pipeline-gate">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={closeClearGate} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="clearGateTitle"
            className="glass-raised relative w-[520px] max-w-[92vw] rounded-2xl border border-red-500/40 p-6 shadow-2xl"
          >
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-red-500/30 bg-red-500/15 text-red-400">
                ⚠️
              </span>
              <div className="flex-1">
                <h3 id="clearGateTitle" className="text-base font-semibold leading-snug">
                  Clear the entire pipeline?
                </h3>
                <p className="mt-1 text-[12px] text-aether-muted">
                  This will <span className="font-semibold text-red-300">archive</span>{" "}
                  <span className="text-[#C7C7D6]">ALL</span> jobs still sitting in the
                  agent-driven pipeline columns — Discovered, Evaluating and Tailoring.
                  Archived jobs are soft-deleted (recoverable in the history view), not
                  destroyed. Your applications, the Ready-to-Apply through Offer columns,
                  and closed items (rejected / withdrawn) are{" "}
                  <span className="text-[#C7C7D6]">left untouched</span>.
                </p>
              </div>
              <button
                type="button"
                onClick={closeClearGate}
                aria-label="Close"
                className="text-aether-muted transition hover:text-white"
              >
                ✕
              </button>
            </div>

            {clearResult ? (
              <div
                className="mt-4 flex items-center gap-2 rounded-xl border border-aether-green/25 bg-aether-green/10 px-3.5 py-2.5 text-[12px]"
                data-testid="clear-pipeline-success"
                role="status"
              >
                ✓ Archived {clearResult.archived} pipeline job
                {clearResult.archived === 1 ? "" : "s"}. The Discovered,
                Evaluating and Tailoring columns are now empty — applications
                and closed items were left untouched.
              </div>
            ) : (
              <div className="mt-5 flex items-center justify-end gap-2">
                <button
                  type="button"
                  data-testid="clear-pipeline-cancel"
                  onClick={closeClearGate}
                  className="glass-raised rounded-xl px-4 py-2.5 text-[13px] transition hover:border-white/20"
                >
                  Cancel
                </button>
                <button
                  ref={clearGateConfirmRef}
                  type="button"
                  data-testid="clear-pipeline-confirm"
                  onClick={() => void confirmClearPipeline()}
                  disabled={clearSubmitting}
                  className="flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 text-[13px] font-semibold hover:opacity-90 disabled:opacity-50"
                >
                  {clearSubmitting ? "Clearing…" : "✕ Yes, Archive Pipeline Jobs"}
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
