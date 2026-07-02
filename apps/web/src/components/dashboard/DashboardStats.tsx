"use client";

/**
 * Live dashboard stat cards fed by GET /analytics/funnel — no hardcoded
 * placeholder numbers. Exposes buildStatCards for unit testing.
 */
import { useEffect, useState } from "react";

import { fetchFunnel, type Funnel } from "../../lib/api/analytics";

export interface StatCard {
  label: string;
  value: string;
  unit?: string;
  icon: string;
  iconColor: string;
  note: string;
  noteColor: string;
}

/** Pure mapping from live funnel data to stat cards (unit tested). */
export function buildStatCards(funnel: Funnel): StatCard[] {
  const interviewRate =
    funnel.applied > 0 ? Math.round((funnel.interviewed / funnel.applied) * 100) : 0;
  return [
    {
      label: "Jobs Found",
      value: String(funnel.jobs_found),
      icon: "fa-solid fa-magnifying-glass",
      iconColor: "text-aether-indigo",
      note: "discovered by Scout",
      noteColor: "text-aether-muted",
    },
    {
      label: "Applications",
      value: String(funnel.applied),
      icon: "fa-solid fa-paper-plane",
      iconColor: "text-aether-coral",
      note: `${funnel.screened} in screening`,
      noteColor: "text-aether-green",
    },
    {
      label: "Interviews",
      value: String(funnel.interviewed),
      icon: "fa-solid fa-comments",
      iconColor: "text-aether-indigo",
      note: `${interviewRate}% of applied`,
      noteColor: "text-aether-muted",
    },
    {
      label: "Offers",
      value: String(funnel.offers),
      icon: "fa-solid fa-award",
      iconColor: "text-aether-amber",
      note: "pending decision",
      noteColor: "text-aether-muted",
    },
  ];
}

export default function DashboardStats() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFunnel("all")
      .then(setFunnel)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Failed to load stats"),
      );
  }, []);

  if (error) {
    return (
      <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
        {error}
      </p>
    );
  }

  if (funnel === null) {
    return (
      <section
        className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5"
        aria-busy="true"
        data-testid="stats-skeleton"
      >
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="glass h-32 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </section>
    );
  }

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5" data-testid="live-stats">
      {buildStatCards(funnel).map((stat) => (
        <div
          key={stat.label}
          className="glass rounded-2xl border border-white/10 p-5 hover:border-white/20 transition"
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] uppercase tracking-wide text-aether-muted-dim font-medium">
              {stat.label}
            </span>
            <i className={`${stat.icon} ${stat.iconColor} text-sm`} aria-hidden="true" />
          </div>
          <div className="mono text-3xl font-bold">
            {stat.value}
            {stat.unit ? <span className="text-lg text-aether-muted-dim">{stat.unit}</span> : null}
          </div>
          <div className={`text-xs ${stat.noteColor} mt-2`}>{stat.note}</div>
        </div>
      ))}
    </section>
  );
}
