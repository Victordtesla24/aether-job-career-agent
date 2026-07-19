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
import { fetchApprovals, type Approval } from "../../../lib/api/approvals";
import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";
import SankeyFlow from "../../../components/applications/SankeyFlow";
import {
  fetchAgentConfig,
  fetchSankey,
  fetchTrackerApplication,
  fetchTrackerApplications,
  type AgentConfig,
  type SankeyData,
  type TrackerApplication,
} from "../../../components/applications/tracker-api";
import {
  FILTER_OPTIONS,
  SORT_OPTIONS,
  buildStages,
  fitClass,
  initials,
  shortDate,
  timeAgo,
  viewStages,
  type FilterKey,
  type SortKey,
  type StageCard,
  type StageKey,
} from "../../../components/applications/tracker-lib";

type ViewMode = "board" | "sankey" | "timeline";

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

/** Stage-specific card footer line/badge (wireframe card-at13..at25). */
function CardMeta({ card, stageKey }: { card: StageCard; stageKey: StageKey }) {
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
      return (
        <span className="mt-2 inline-block rounded-md bg-aether-yellow/15 px-2 py-0.5 text-[10px] text-aether-yellow">
          needs approval
        </span>
      );
    case "submitted":
      return meta.followUpSentAt ? (
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-aether-green">
          <i className="fa-solid fa-clock text-[9px]" aria-hidden="true" />
          Follow-up sent ✓
        </div>
      ) : null;
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
  const [detail, setDetail] = useState<TrackerApplication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<ViewMode>("board");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("recent");
  const [sankey, setSankey] = useState<SankeyData | null>(null);
  const [sankeyError, setSankeyError] = useState<string | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);

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

  const stages = viewStages(buildStages(apps ?? [], jobs), filter, sort, pendingApprovalIds);
  const closed = (apps ?? []).filter((a) => a.status === "rejected" || a.status === "withdrawn");
  const activeCount = stages.reduce((n, s) => n + s.cards.length, 0);
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
                {new Date(detail.updatedAt).toLocaleString()}
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
                            {...(clickable
                              ? {
                                  role: "button" as const,
                                  tabIndex: 0,
                                  "aria-label": `${card.title} at ${card.company}, open details`,
                                }
                              : {})}
                            onClick={clickable ? () => void openDetail(card.app!.id) : undefined}
                            onKeyDown={
                              clickable
                                ? (e) => {
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault();
                                      void openDetail(card.app!.id);
                                    }
                                  }
                                : undefined
                            }
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
                                  <span className={`mono text-[11px] font-semibold ${fitClass(card.fit)}`}>
                                    {card.fit}
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
                              {card.title}
                            </h3>
                            <p className="text-[11px] text-aether-muted-dim">{card.company}</p>
                            <CardMeta card={card} stageKey={stage.key} />
                            <CardLink stageKey={stage.key} />
                            <p className="mono mt-2 text-[10px] text-aether-muted-dim">
                              {timeAgo(card.updatedAt)}
                            </p>
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
    </div>
  );
}
