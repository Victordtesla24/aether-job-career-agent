"use client";

/**
 * Applications kanban — pipeline view grouped by status, backed by
 * GET /applications.
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

const COLUMNS: Array<{ status: ApplicationStatus; label: string; accent: string }> = [
  { status: "draft", label: "Draft", accent: "border-white/20" },
  { status: "submitted", label: "Submitted", accent: "border-aether-coral/40" },
  { status: "screening", label: "Screening", accent: "border-aether-amber/40" },
  { status: "interview", label: "Interview", accent: "border-aether-violet/40" },
  { status: "offer", label: "Offer", accent: "border-aether-green/40" },
  { status: "rejected", label: "Rejected", accent: "border-red-500/30" },
];

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[] | null>(null);
  const [jobFit, setJobFit] = useState<Record<string, number>>({});
  const [pendingCount, setPendingCount] = useState(0);
  const [detail, setDetail] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      setApps(await fetchApplications());
      setError(null);
      // Fit scores come from the underlying job (wireframe card-at17 chip).
      try {
        const jobs = await apiRequest<Job[]>("/jobs");
        setJobFit(
          Object.fromEntries(
            jobs.filter((j) => j.fitScore != null).map((j) => [j.id, Math.round(Number(j.fitScore))]),
          ),
        );
      } catch {
        /* fit chips are progressive enhancement */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load applications");
      setApps([]);
    }
    // Pending-approvals banner (audit defect D7) — non-fatal if it fails.
    try {
      setPendingCount((await fetchApprovals("pending")).length);
    } catch {
      // Keep the last known count: zeroing it here is indistinguishable from
      // an empty queue and would hide the banner while approvals still exist.
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

  const byStatus = (status: ApplicationStatus) =>
    (apps ?? []).filter((a) => a.status === status);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Applications</h1>
        <p className="text-sm text-aether-muted">
          Pipeline tracker — every submission passed through human approval.
        </p>
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
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6" aria-busy="true">
          {COLUMNS.map((c) => (
            <div key={c.status} className="glass h-64 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6" data-testid="applications-kanban">
          {COLUMNS.map((column) => {
            const cards = byStatus(column.status);
            return (
              <section
                key={column.status}
                data-testid={`kanban-column-${column.status}`}
                className={`glass rounded-2xl border ${column.accent} p-3`}
              >
                <header className="flex items-center justify-between px-1 pb-2">
                  <h2 className="text-sm font-semibold">{column.label}</h2>
                  <span className="mono text-xs text-aether-muted-dim">{cards.length}</span>
                </header>
                <div className="space-y-2">
                  {cards.length === 0 ? (
                    <p className="px-1 py-4 text-center text-xs text-aether-muted-dim">Empty</p>
                  ) : (
                    cards.slice(0, 25).map((app) => (
                      <article
                        key={app.id}
                        data-testid="application-card"
                        role="button"
                        tabIndex={0}
                        onClick={() => void openDetail(app.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") void openDetail(app.id);
                        }}
                        className="cursor-pointer rounded-xl border border-white/10 bg-white/5 p-3 transition hover:border-aether-violet/50"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                              {initials(app.company)}
                            </span>
                            {jobFit[app.jobId] != null ? (
                              <span className="mono text-[11px] font-semibold text-aether-green">
                                {jobFit[app.jobId]}
                              </span>
                            ) : null}
                          </div>
                          <span
                            className={`flex h-5 w-5 items-center justify-center rounded-full ${STATUS_ICON[app.status].cls}`}
                            title={app.status}
                          >
                            <i className={`fa-solid ${STATUS_ICON[app.status].icon} text-[9px]`} aria-hidden="true" />
                          </span>
                        </div>
                        <h3 className="mt-2.5 text-sm font-semibold leading-tight">{app.jobTitle}</h3>
                        <p className="mt-0.5 text-xs text-aether-muted">{app.company}</p>
                        {app.status === "draft" ? (
                          <span className="mt-2 inline-block rounded-md bg-aether-amber/15 px-2 py-0.5 text-[10px] text-aether-amber">
                            needs approval
                          </span>
                        ) : null}
                        <p className="mono mt-1 text-[10px] text-aether-muted-dim">
                          {new Date(app.updatedAt).toLocaleDateString()}
                        </p>
                      </article>
                    ))
                  )}
                  {cards.length > 25 ? (
                    <p className="px-1 text-center text-xs text-aether-muted-dim">
                      +{cards.length - 25} more
                    </p>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
