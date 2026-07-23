"use client";

/**
 * Dashboard stat cards (wireframe stats-row-p7q8r9): Active Applications,
 * Interview Rate, Offers, AI Confidence — every value derived from live API
 * data passed in by the page (single funnel fetch, REQ-TM-10). Exposes
 * buildStatCards for unit testing.
 */
import MetricTooltip from "../MetricTooltip";
import type { Funnel } from "../../lib/api/analytics";

interface StatCard {
  label: string;
  value: string;
  unit?: string;
  icon: string;
  iconColor: string;
  note: string;
  noteColor: string;
  trendUp?: boolean;
  tooltip: string;
}

interface StatExtras {
  /** Applications created in the last 7 days (funnel period=7d). */
  weeklyApplied?: number | null;
  /** Average job fitScore (0–100) across discovered jobs. */
  avgFit?: number | null;
}

/** Pure mapping from live funnel + job data to the four wireframe cards. */
export function buildStatCards(funnel: Funnel, extras: StatExtras = {}): StatCard[] {
  const { weeklyApplied = null, avgFit = null } = extras;
  const interviewRate =
    funnel.applied > 0 ? Math.round((funnel.interviewed / funnel.applied) * 100) : 0;
  return [
    {
      label: "Active Applications",
      value: String(funnel.applied),
      icon: "fa-solid fa-paper-plane",
      iconColor: "text-aether-coral",
      note:
        weeklyApplied != null && weeklyApplied > 0
          ? `+${weeklyApplied} this week`
          : "no new this week",
      noteColor:
        weeklyApplied != null && weeklyApplied > 0 ? "text-aether-green" : "text-aether-muted",
      trendUp: weeklyApplied != null && weeklyApplied > 0,
      // Honest about what's actually counted (data-consistency ruling,
      // MV-mobile-dashboard-005): funnel.applied is every Application that
      // has left "draft" — i.e. actually submitted — not a narrower
      // "still active" subset, so the tooltip must not claim otherwise.
      tooltip: "Applications you've submitted to an employer — every status past draft (screening, interview, offer, or rejected).",
    },
    {
      label: "Interview Rate",
      value: String(interviewRate),
      unit: "%",
      icon: "fa-solid fa-comments",
      iconColor: "text-aether-indigo",
      note:
        funnel.applied > 0
          ? `${funnel.interviewed} of ${funnel.applied} applied`
          : "no applications yet",
      noteColor: "text-aether-muted",
      tooltip: "Share of your applications that progressed to at least one interview (Application → Interview %).",
    },
    {
      label: "Offers",
      value: String(funnel.offers),
      icon: "fa-solid fa-award",
      iconColor: "text-aether-amber",
      note: funnel.offers > 0 ? `${funnel.offers} pending decision` : "none yet — agents hunting",
      noteColor: "text-aether-muted",
      tooltip: "Applications where an employer has extended a formal offer.",
    },
    {
      label: "AI Confidence",
      value: avgFit != null ? String(Math.round(avgFit)) : "—",
      unit: avgFit != null ? "%" : undefined,
      icon: "fa-solid fa-brain",
      iconColor: "text-aether-coral",
      note: avgFit != null ? "avg match quality" : "no scored jobs yet",
      noteColor: "text-aether-muted",
      tooltip: "Average ATS/AI fit score across all scored jobs — a 0–100 estimate of resume-to-role match quality.",
    },
  ];
}

export default function DashboardStats({
  funnel,
  extras,
  error,
}: {
  funnel: Funnel | null;
  extras?: StatExtras;
  error?: string | null;
}) {
  if (error) {
    return (
      <p
        role="alert"
        className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
      >
        Couldn&apos;t load your stats — {error}
      </p>
    );
  }

  if (funnel === null) {
    return (
      <section
        className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4"
        aria-busy="true"
        aria-label="Loading stats"
        data-testid="stats-skeleton"
      >
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="glass h-32 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </section>
    );
  }

  return (
    <section
      className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4"
      data-testid="live-stats"
      aria-label="Key stats"
    >
      {buildStatCards(funnel, extras).map((stat) => (
        <div
          key={stat.label}
          className="glass rounded-2xl border border-white/10 p-5 transition hover:border-white/20"
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
              {stat.label}
            </span>
            <i className={`${stat.icon} ${stat.iconColor} text-sm`} aria-hidden="true" />
          </div>
          <div className="mono text-3xl font-bold">
            <MetricTooltip
              value={
                <>
                  {stat.value}
                  {stat.unit ? <span className="text-lg text-aether-muted-dim">{stat.unit}</span> : null}
                </>
              }
              tooltip={stat.tooltip}
            />
          </div>
          <div className={`mt-2 flex items-center gap-1 text-xs ${stat.noteColor}`}>
            {stat.trendUp ? <i className="fa-solid fa-arrow-up text-[10px]" aria-hidden="true" /> : null}
            {stat.note}
          </div>
        </div>
      ))}
    </section>
  );
}
