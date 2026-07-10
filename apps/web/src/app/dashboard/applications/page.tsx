"use client";

/**
 * Application Tracker — canonical 8-stage pipeline (wireframe
 * application-tracker.html): Discovered / Evaluating / Tailoring / Ready /
 * Submitted / In Review / Interview / Offer.
 *
 * The first three stages are fed by the jobs pipeline (Job.status), the last
 * five by Application.status (draft→Ready, submitted→Submitted,
 * screening→In Review, interview→Interview, offer→Offer). Rejected /
 * withdrawn applications collapse into a compact "Closed" strip so drop-off
 * stays visible without cluttering the board. Backed by GET /applications
 * and GET /jobs. Views: Board / Sankey Flow / Timeline.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  fetchApplication,
  fetchApplications,
  submitApplication,
  type Application,
  type ApplicationStatus,
} from "../../../lib/api/applications";
import { fetchApprovals } from "../../../lib/api/approvals";
import { apiRequest } from "../../../lib/api/client";
import type { Job } from "../../../lib/api/jobs";

/** Company initials chip (wireframe card-at17). */
function initials(company: string) {
  return company
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

const STATUS_ICON: Record<ApplicationStatus, { icon: string; cls: string }> = {
  draft: { icon: "fa-file-pen", cls: "text-aether-coral bg-aether-coral/20" },
  submitted: { icon: "fa-check", cls: "text-aether-violet bg-aether-violet/20" },
  screening: { icon: "fa-clock", cls: "text-aether-amber bg-aether-amber/20" },
  interview: { icon: "fa-comments", cls: "text-aether-violet bg-aether-violet/20" },
  offer: { icon: "fa-award", cls: "text-aether-green bg-aether-green/20" },
  rejected: { icon: "fa-xmark", cls: "text-red-300 bg-red-500/20" },
  withdrawn: { icon: "fa-ban", cls: "text-aether-muted-dim bg-white/10" },
};

/** One card on the board — either a live application or a pipeline job. */
type StageCard = {
  id: string;
  title: string;
  company: string;
  updatedAt: string;
  fit?: number;
  app?: Application;
};

type Stage = { key: string; label: string; accent: string; cards: StageCard[] };

const STAGE_DEFS: Array<{ key: string; label: string; accent: string }> = [
  { key: "discovered", label: "Discovered", accent: "border-white/20" },
  { key: "evaluating", label: "Evaluating", accent: "border-aether-indigo/40" },
  { key: "tailoring", label: "Tailoring", accent: "border-aether-amber/40" },
  { key: "ready", label: "Ready", accent: "border-aether-coral/40" },
  { key: "submitted", label: "Submitted", accent: "border-aether-violet/40" },
  { key: "in-review", label: "In Review", accent: "border-aether-amber/40" },
  { key: "interview", label: "Interview", accent: "border-aether-violet/40" },
  { key: "offer", label: "Offer", accent: "border-aether-green/40" },
];

/** Application.status → canonical stage key. */
const APP_STAGE: Partial<Record<ApplicationStatus, string>> = {
  draft: "ready",
  submitted: "submitted",
  screening: "in-review",
  interview: "interview",
  offer: "offer",
};

/** Job.status → canonical stage key (pre-application pipeline stages). */
const JOB_STAGE: Record<string, string> = {
  discovered: "discovered",
  screening: "evaluating",
  matched: "evaluating",
  tailoring: "tailoring",
};

type ViewMode = "board" | "sankey" | "timeline";

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [detail, setDetail] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<ViewMode>("board");

  const load = useCallback(async () => {
    try {
      setApps(await fetchApplications());
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
    // Pending-approvals banner (audit defect D7) — non-fatal if it fails.
    try {
      setPendingCount((await fetchApprovals("pending")).length);
    } catch {
      // Keep the last known count.
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (id: string) => {
    try {
      setDetail(await fetchApplication(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load application");
    }
  };

  const markSubmitted = async (app: Application) => {
    setSubmitting(true);
    try {
      const updated = await submitApplication(app.id, app.applyUrl ?? null);
      setDetail(updated);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to mark as submitted");
    } finally {
      setSubmitting(false);
    }
  };

  // ---- Stage assembly -----------------------------------------------------
  const jobFit: Record<string, number> = Object.fromEntries(
    jobs.filter((j) => j.fitScore != null).map((j) => [j.id, Math.round(Number(j.fitScore))]),
  );
  const appJobIds = new Set((apps ?? []).map((a) => a.jobId));
  const stages: Stage[] = STAGE_DEFS.map((d) => ({ ...d, cards: [] }));
  const stageByKey = Object.fromEntries(stages.map((s) => [s.key, s]));

  for (const j of jobs) {
    const key = JOB_STAGE[j.status];
    if (key && !appJobIds.has(j.id)) {
      stageByKey[key].cards.push({
        id: `job-${j.id}`,
        title: j.title,
        company: j.company,
        updatedAt: j.updatedAt ?? j.createdAt ?? "",
        fit: j.fitScore != null ? Math.round(Number(j.fitScore)) : undefined,
      });
    }
  }
  for (const a of apps ?? []) {
    const key = APP_STAGE[a.status];
    if (key) {
      stageByKey[key].cards.push({
        id: a.id,
        title: a.jobTitle,
        company: a.company,
        updatedAt: a.updatedAt,
        fit: jobFit[a.jobId],
        app: a,
      });
    }
  }
  const closed = (apps ?? []).filter((a) => a.status === "rejected" || a.status === "withdrawn");
  const activeCount = stages.reduce((n, s) => n + s.cards.length, 0);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Application Tracker</h1>
          <p className="text-sm text-aether-muted">
            {activeCount} active application{activeCount === 1 ? "" : "s"} across 8 stages — every
            submission passed through human approval.
          </p>
          <p className="mt-1 text-xs text-aether-muted-dim">
            <span className="rounded-md bg-aether-amber/15 px-1.5 py-0.5 text-aether-amber">needs approval</span>{" "}
            drafts wait in Ready for your go-ahead before anything is sent.
          </p>
        </div>
        <div className="flex rounded-xl border border-white/10 bg-white/5 p-1" role="tablist" aria-label="Tracker views">
          {(
            [
              { key: "board", label: "Board View" },
              { key: "sankey", label: "Sankey Flow" },
              { key: "timeline", label: "Timeline" },
            ] as Array<{ key: ViewMode; label: string }>
          ).map((v) => (
            <button
              key={v.key}
              type="button"
              role="tab"
              aria-selected={view === v.key}
              data-testid={`view-${v.key}`}
              onClick={() => setView(v.key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                view === v.key ? "bg-aether-coral text-white" : "text-aether-muted hover:text-white"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </header>

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
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
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
              className="text-xs text-aether-muted-dim hover:text-white"
              title="Close detail"
            >
              ✕
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
        <div className="grid gap-4 md:grid-cols-4" aria-busy="true">
          {STAGE_DEFS.slice(0, 4).map((c) => (
            <div key={c.key} className="glass h-64 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : view === "board" ? (
        <>
          <div className="overflow-x-auto pb-2" data-testid="applications-kanban">
            <div className="grid min-w-[1100px] grid-cols-8 gap-3">
              {stages.map((stage) => (
                <section
                  key={stage.key}
                  data-testid={`kanban-column-${stage.key}`}
                  className={`glass rounded-2xl border ${stage.accent} p-3`}
                >
                  <header className="flex items-center justify-between px-1 pb-2">
                    <h2 className="text-sm font-semibold">{stage.label}</h2>
                    <span className="mono text-xs text-aether-muted-dim">{stage.cards.length}</span>
                  </header>
                  <div className="space-y-2">
                    {stage.cards.length === 0 ? (
                      <p className="px-1 py-4 text-center text-xs text-aether-muted-dim">Empty</p>
                    ) : (
                      stage.cards.slice(0, 25).map((card) => (
                        <article
                          key={card.id}
                          data-testid="application-card"
                          role="button"
                          tabIndex={0}
                          onClick={() => (card.app ? void openDetail(card.app.id) : undefined)}
                          onKeyDown={(e) => {
                            if (card.app && (e.key === "Enter" || e.key === " ")) void openDetail(card.app.id);
                          }}
                          className={`rounded-xl border border-white/10 bg-white/5 p-3 transition hover:border-aether-violet/50 ${
                            card.app ? "cursor-pointer" : ""
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                                {initials(card.company)}
                              </span>
                              {card.fit != null ? (
                                <span className="mono text-[11px] font-semibold text-aether-green">{card.fit}</span>
                              ) : null}
                            </div>
                            {card.app ? (
                              <span
                                className={`flex h-5 w-5 items-center justify-center rounded-full ${STATUS_ICON[card.app.status].cls}`}
                                title={card.app.status}
                              >
                                <i
                                  className={`fa-solid ${STATUS_ICON[card.app.status].icon} text-[9px]`}
                                  aria-hidden="true"
                                />
                              </span>
                            ) : (
                              <span
                                className="flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-aether-muted-dim"
                                title="agent pipeline"
                              >
                                <i className="fa-solid fa-robot text-[9px]" aria-hidden="true" />
                              </span>
                            )}
                          </div>
                          <h3 className="mt-2.5 text-sm font-semibold leading-tight">{card.title}</h3>
                          <p className="mt-0.5 text-xs text-aether-muted">{card.company}</p>
                          {card.app?.status === "draft" ? (
                            <span className="mt-2 inline-block rounded-md bg-aether-amber/15 px-2 py-0.5 text-[10px] text-aether-amber">
                              needs approval
                            </span>
                          ) : null}
                          <p className="mono mt-1 text-[10px] text-aether-muted-dim">
                            {new Date(card.updatedAt).toLocaleDateString()}
                          </p>
                        </article>
                      ))
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
                    className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-aether-muted-dim hover:border-white/25 hover:text-white"
                  >
                    {a.jobTitle} · {a.company} · {a.status}
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : view === "sankey" ? (
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="sankey-view">
          <h2 className="text-[15px] font-semibold">Sankey Flow</h2>
          <p className="mb-4 text-xs text-aether-muted-dim">
            Application flow &amp; drop-off across stages
          </p>
          <div className="space-y-3">
            {stages.map((stage) => {
              const max = Math.max(...stages.map((s) => s.cards.length), 1);
              return (
                <div key={stage.key} className="flex items-center gap-3">
                  <span className="w-24 shrink-0 text-xs text-aether-muted">{stage.label}</span>
                  <div className="h-5 flex-1 rounded-full bg-white/5">
                    <div
                      className="h-5 rounded-full bg-gradient-to-r from-aether-indigo to-aether-coral"
                      style={{ width: `${Math.max((stage.cards.length / max) * 100, stage.cards.length > 0 ? 6 : 0)}%` }}
                    />
                  </div>
                  <span className="mono w-8 shrink-0 text-right text-xs">{stage.cards.length}</span>
                </div>
              );
            })}
            <div className="flex items-center gap-3">
              <span className="w-24 shrink-0 text-xs text-red-300">Dropped</span>
              <div className="h-5 flex-1 rounded-full bg-white/5">
                <div
                  className="h-5 rounded-full bg-red-500/40"
                  style={{
                    width: `${Math.max(
                      (closed.length / Math.max(...stages.map((s) => s.cards.length), 1)) * 100,
                      closed.length > 0 ? 6 : 0,
                    )}%`,
                  }}
                />
              </div>
              <span className="mono w-8 shrink-0 text-right text-xs">{closed.length}</span>
            </div>
          </div>
        </section>
      ) : (
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="timeline-view">
          <h2 className="mb-4 text-[15px] font-semibold">Timeline</h2>
          <ol className="space-y-3 border-l border-white/10 pl-4">
            {[...(apps ?? [])]
              .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
              .map((a) => (
                <li key={a.id} className="relative">
                  <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-aether-coral" />
                  <button
                    type="button"
                    onClick={() => void openDetail(a.id)}
                    className="text-left text-sm hover:text-aether-coral"
                  >
                    <span className="font-semibold">{a.jobTitle}</span>{" "}
                    <span className="text-aether-muted">@ {a.company}</span>
                  </button>
                  <p className="mono text-[11px] text-aether-muted-dim">
                    {a.status} · {new Date(a.updatedAt).toLocaleString()}
                  </p>
                </li>
              ))}
          </ol>
        </section>
      )}
    </div>
  );
}
