"use client";

/**
 * Applications kanban — pipeline view grouped by status, backed by
 * GET /applications.
 */
import { useCallback, useEffect, useState } from "react";

import {
  fetchApplications,
  type Application,
  type ApplicationStatus,
} from "../../../lib/api/applications";

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
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setApps(await fetchApplications());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load applications");
      setApps([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
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
                        className="rounded-xl border border-white/10 bg-white/5 p-3"
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
