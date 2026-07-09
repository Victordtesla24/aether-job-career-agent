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
  type Application,
  type ApplicationStatus,
} from "../../../lib/api/applications";
import { fetchApprovals } from "../../../lib/api/approvals";

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
  const [pendingCount, setPendingCount] = useState(0);
  const [detail, setDetail] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setApps(await fetchApplications());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load applications");
      setApps([]);
    }
    // Pending-approvals banner (audit defect D7) — non-fatal if it fails.
    try {
      setPendingCount((await fetchApprovals("pending")).length);
    } catch {
      setPendingCount(0);
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
                        <h3 className="text-sm font-semibold leading-tight">{app.jobTitle}</h3>
                        <p className="mt-0.5 text-xs text-aether-muted">{app.company}</p>
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
