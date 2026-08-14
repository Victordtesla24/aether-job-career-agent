"use client";

/**
 * Analytics — funnel, ATS score distribution and agent ROI, backed by
 * GET /analytics/funnel, /analytics/ats-distribution and /analytics/agent-roi.
 */
import { useCallback, useEffect, useState } from "react";

import MarketPulse from "../../../components/analytics/MarketPulse";
import ExecutiveSummary from "../../../components/analytics/ExecutiveSummary";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import { useUrlTab } from "../../../hooks/useUrlTab";
import MetricTooltip from "../../../components/MetricTooltip";
import StatBlock from "../../../components/ui/StatBlock";
import SegmentedControl from "../../../components/ui/SegmentedControl";
import Section from "../../../components/ui/Section";
import {
  BulletChart,
  Funnel as FunnelChart,
  Histogram,
  Radar10,
} from "../../../components/charts";
import { atsBuckets, fitDimensions, funnelSteps } from "../../../lib/analytics/chart-adapters";
import {
  executiveSummary,
  normaliseTarget,
  numberFrom,
  INTERVIEW_TARGET_PCT,
} from "../../../lib/analytics/executive-summary";
import type { RealtimeResource } from "../../../lib/realtime/transport-types";
import AgentPolicyPanel from "../../../components/agents/AgentPolicyPanel";
import {
  PolicyCohortProgress,
  PolicyTierHistory,
} from "../../../components/agents/PolicyProgress";
import {
  fetchAgentRoi,
  fetchAtsDistribution,
  fetchConversion,
  fetchDashboard,
  fetchFunnel,
  type AgentRoi,
  type AtsDistribution,
  type Conversion,
  type Dashboard,
  type Funnel,
  type Period,
} from "../../../lib/api/analytics";
import {
  fetchAgentPolicy,
  fetchPolicyCohorts,
  fetchPolicyHistory,
  type AgentPolicy,
  type PolicyCohorts,
  type PolicyHistory,
} from "../../../lib/api/agentPolicy";

const PERIODS: Period[] = ["7d", "30d", "90d", "all"];

/**
 * FOUR LINKABLE VIEWS, ONE ROUTE — the B1 re-review's remaining aesthetics
 * finding, closed structurally rather than by re-tiling.
 *
 * The page measured 3,737px at 1600w (`b1/close/before-notes.json`) and put
 * twelve distinct blocks in one continuous scroll: current policy, two policy
 * progress panels, a 7-card KPI band, funnel + stage conversion, ATS
 * histogram + fit radar, three ROI tiles + two cost-per tiles, then the whole
 * of MarketPulse. No reference capture in the pack (Linear / Mercury /
 * Stripe) shows more than 2-3 compositional blocks in a single view.
 *
 * This is PRESENTATION ONLY, and deliberately the pattern the Agents console
 * already ships (`app/dashboard/agents/page.tsx` + `useUrlTab`) rather than a
 * second navigation paradigm:
 *   · every block keeps its exact data, copy, honesty captions and testid —
 *     blocks MOVE, nothing is deleted, reworded or re-scoped;
 *   · EVERY panel stays MOUNTED and is hidden with the `hidden` attribute, so
 *     a view switch issues no request at all, no chart re-animates, and every
 *     control stays keyboard-reachable and readable by assistive tech that
 *     walks the DOM;
 *   · all four views are fed by the one `load()` above — no fetch moved, no
 *     fetch was added, and the network profile of a page load is byte-for-byte
 *     what it was (`close/netdiff-*`).
 *
 * VIEW MEMBERSHIP IS CONSTRAINED BY AN HONESTY CONTRACT, not only by theme:
 * `interview-conversion-gap` tells the reader to see the Agent Performance
 * Policy panel "above" it, and R-05 (`__tests__/policy-progress.test.tsx`)
 * pins that the words match the real DOM order. So the policy panel stays in
 * the SAME view as stage conversion, above it — moving it behind another tab
 * would turn a true direction into a false one. The policy's HISTORY and
 * per-tier cohort outcomes carry no such pointer and sit under Quality, where
 * the question they answer ("is the rigor policy working?") belongs.
 *
 * WHY THREE VIEWS AND NOT FOUR. Agent ROI was drafted as its own tab. Measured
 * at 1600x1100 it rendered one 280px panel above ~600px of empty ground —
 * five numerals alone on a screen, which reads as an unfinished view, not a
 * focused one. It joins Quality as the third row of that view: ATS spread and
 * fit radar (how good are these matches), the policy's history and cohorts (is
 * the rigor loop working), then what all of it cost. Every panel keeps its own
 * heading, so nothing about what the reader is looking at becomes ambiguous.
 */
const TABS = ["overview", "quality", "market"] as const;
type AnalyticsTab = (typeof TABS)[number];

const TAB_ITEMS: ReadonlyArray<{ value: AnalyticsTab; label: string; icon: string }> = [
  { value: "overview", label: "Overview", icon: "fa-gauge-high" },
  { value: "quality", label: "Quality & ROI", icon: "fa-bullseye" },
  { value: "market", label: "Market", icon: "fa-globe" },
];

/**
 * The 12-column spans that make the 7-card summary strip divide exactly:
 * 3+3+3+3 on row one, 4+4+4 on row two. This is what removes the empty eighth
 * cell a `lg:grid-cols-4` grid left behind.
 */
const SUMMARY_SPANS = [
  "lg:col-span-3",
  "lg:col-span-3",
  "lg:col-span-3",
  "lg:col-span-3",
  "lg:col-span-4",
  "lg:col-span-4",
  "lg:col-span-4",
] as const;

/**
 * The summary strip's cards. Labels are UNCHANGED — `SUMMARY_TIP` is keyed by
 * them and each one carries a tested honesty contract about what is counted.
 *
 * `resource` drives the §3.4 T-B live delta chip and is set only where the
 * displayed value IS a row count of that stream resource. "Avg Fit Score" is a
 * mean and "Agent Spend" is a sum of costs, so neither may wear a row-count
 * delta — they are deliberately absent rather than approximated.
 */
function SUMMARY_CARDS(
  dashboard: Dashboard,
): Array<{ label: string; value: string; unit?: string; resource?: RealtimeResource }> {
  return [
    {
      label: "Applications (all stages)",
      value: String(dashboard.totalApplications),
      resource: "applications",
    },
    { label: "Interviews", value: String(dashboard.interviews), resource: "interviews" },
    { label: "Offers", value: String(dashboard.offers), resource: "offers" },
    { label: "Jobs Found", value: String(dashboard.jobsFound), resource: "jobs" },
    { label: "Avg Fit Score", value: String(dashboard.avgFitScore), unit: "%" },
    { label: "Agent Runs", value: String(dashboard.agentRuns), resource: "agentRuns" },
    { label: "Agent Spend (USD)", value: `$${dashboard.agentCostUsd.toFixed(2)}` },
  ];
}

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>("all");
  const [tab, setTab] = useUrlTab<AnalyticsTab>(TABS, "overview");
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [ats, setAts] = useState<AtsDistribution | null>(null);
  const [roi, setRoi] = useState<AgentRoi | null>(null);
  const [conversion, setConversion] = useState<Conversion | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  // U-AX item 2(a): the self-improvement loop's current tier — loaded
  // independently so a failure here never blanks the rest of the page (same
  // degrade pattern the dashboard summary already uses below).
  const [policy, setPolicy] = useState<AgentPolicy | null>(null);
  // U-AX item 2(c) / item 3 (R-06): the tier's history and the per-tier cohort
  // outcomes. Independent of `policy` so one endpoint failing cannot blank the
  // other two panels — each degrades to absent, never to a fabricated default.
  const [policyHistory, setPolicyHistory] = useState<PolicyHistory | null>(null);
  const [policyCohorts, setPolicyCohorts] = useState<PolicyCohorts | null>(null);

  const load = useCallback(async () => {
    try {
      // Fetch from working sub-endpoints first — these must not block the page.
      const [funnelData, atsData, roiData, conversionData] = await Promise.all([
        fetchFunnel(period),
        fetchAtsDistribution(),
        fetchAgentRoi(),
        fetchConversion(period),
      ]);
      setFunnel(funnelData);
      setAts(atsData);
      setRoi(roiData);
      setConversion(conversionData);
      setError(null);

      // Dashboard summary is fetched separately so a 404 on the dashboard
      // endpoint does not take down the entire page (GAP-P4-005 / P4-016).
      // Forwards the selected period (MV-analytics-004) — the backend has
      // always supported it; only the panels below (ATS distribution,
      // Agent ROI) have no period support server-side, so they carry an
      // explicit "all time" label instead of silently ignoring the selector.
      try {
        const dashboardData = await fetchDashboard(period);
        setDashboard(dashboardData);
      } catch {
        // Dashboard endpoint not yet deployed — degrade gracefully.
        setDashboard(null);
      }

      try {
        setPolicy(await fetchAgentPolicy());
      } catch {
        // U-AX policy panel is additive — its own failure must not take down
        // the funnel/conversion/ATS panels above.
        setPolicy(null);
      }

      try {
        setPolicyHistory(await fetchPolicyHistory());
      } catch {
        setPolicyHistory(null);
      }

      try {
        setPolicyCohorts(await fetchPolicyCohorts());
      } catch {
        setPolicyCohorts(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  // W-RT — the shared realtime channel. Every figure on this screen is derived
  // from Jobs, Applications, Résumés and Agent runs, and none of them was
  // refreshed after mount: the funnel could sit at yesterday's numbers all day.
  // Subscribing to the four source resources keeps the derived views honest.
  useRealtimeResources(["applications", "jobs", "resumes", "agentRuns"], () => {
    void load();
  });



  const SUMMARY_TIP: Record<string, string> = {
    // Honest about what's counted (data-consistency ruling,
    // MV-analytics-005): this is the canonical, unqualified "Applications"
    // figure — every Application record you have, including drafts you
    // haven't submitted yet — not the narrower "Applied"/submitted count
    // shown in the funnel below. It respects the period selector above
    // (GET /analytics/dashboard?period=..., MV-analytics-004) — the copy
    // must say so instead of claiming "all time periods" while the number
    // visibly changes when the selector is used.
    // QA-2026-08-13 C-10: the visible label now says "(all stages)" so the
    // difference vs the funnel's narrower "Applied" (submitted-only) count is
    // self-explanatory without hovering — 460 here vs 134 in the funnel is
    // intentional, not a bug, and the copy must make that obvious.
    "Applications (all stages)":
      "Every application record created in the selected period — draft through offer or rejection. The funnel's \"Applied\" stage below counts only submitted applications, so it is expected to be smaller.",
    Interviews: "Applications that have progressed to at least one interview stage.",
    Offers: "Applications where an employer has extended a formal offer.",
    "Jobs Found": "Roles discovered by the Scout agent and matched against your profile.",
    "Avg Fit Score": "Average ATS/AI fit score (0–100) across all scored jobs — how well your resume matches each posting.",
    "Agent Runs": "Total number of agent executions (discovery, tailoring, scoring, etc.) in this period.",
    "Agent Spend (USD)": "Total agent cost incurred by agent runs in this period, shown in US dollars — LLM providers bill in USD and no currency conversion is applied.",
  };

  const CONVERSION_TIP: Record<string, string> = {
    "Found → Applied": "Share of discovered jobs you went on to apply for.",
    "Applied → Screened": "Share of applications that advanced to a recruiter screen.",
    "Screened → Interview": "Share of screened applications that reached an interview.",
    "Interview → Offer": "Share of interviews that resulted in a formal offer.",
  };

  // GOLD-MASTER V4 §6 / G-C: whether applications exist at all — used only
  // to decide the HONESTY FRAMING (badge) around interview_conversion_rate,
  // never to recompute the rate itself (that stays 100% API-derived). A
  // brand-new account with zero submitted applications hasn't had a chance
  // to convert anything, so a red "needs improvement" badge there would be
  // misleading; once there is at least one submitted application, the
  // API's own >=1:5 floor (interview_conversion_healthy) is real signal and
  // is shown honestly, good or bad.
  const hasApplications = funnel !== null && funnel.applied > 0;

  /**
   * Inactive views stay MOUNTED and are removed from the layout with the
   * `hidden` attribute (never unmounted) — the same contract the Agents
   * console ships. Tailwind's `space-y-*` is authored as
   * `> :not([hidden]) ~ :not([hidden])`, so a hidden panel also drops out of
   * the page's vertical rhythm instead of leaving a gap behind it.
   */
  const panelProps = (value: AnalyticsTab) => ({
    id: `analytics-panel-${value}`,
    role: "tabpanel" as const,
    "aria-labelledby": `analytics-tabs-${value}`,
    hidden: tab !== value,
    "data-testid": `analytics-panel-${value}`,
  });

  /**
   * ANALYTICS-VIZ — the executive summary band, derived DETERMINISTICALLY from
   * the five payloads already in state above. It sits ABOVE the view switcher,
   * so it is on screen on every tab: "what's what in one glance" is not a
   * property of one view.
   */
  const execTiles = executiveSummary({
    period,
    funnel,
    conversion,
    ats,
    roi,
    policy,
    policyHistory,
  });

  /** The 1-in-5 interview-conversion target, sourced from the policy payload
   *  when it carried one so the page and the backend can never state two
   *  different targets. */
  const conversionTargetPct = (() => {
    const declared = numberFrom(policy?.thresholds, "interviewConversionTarget");
    return declared === null ? INTERVIEW_TARGET_PCT : normaliseTarget(declared);
  })();

  return (
    <div className="space-y-7">
      {/* BAND 1 — the hero moment: this screen's ONE saturated brand gesture
          (reference rule 3) inside the atmospheric glow.

          The page's old sub-title ("Funnel conversion, ATS score quality and
          agent spend.") is GONE: it was a standalone prose line that named the
          three views the switcher below it already names, and the executive
          band now answers the same question with measurements instead of a
          list of nouns. */}
      <section className="atmos-hero">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="type-page">
              <span className="text-gradient-brand">Analytics</span>
            </h1>
          </div>
          <div
            className="elev-1 flex gap-1 rounded-xl p-1"
            role="group"
            aria-label="Reporting period"
            data-testid="period-selector"
          >
            {PERIODS.map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={period === p}
                onClick={() => setPeriod(p)}
                className={`rounded-lg px-3 py-1 text-sm transition-colors duration-[--dur] ${
                  period === p
                    ? "bg-aether-coral font-semibold text-white"
                    : "text-aether-muted hover:text-white"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </header>

        {/* THE EXECUTIVE SUMMARY BAND — inside the lit band, above the view
            switcher, so it is present on every tab. Five measured tiles; the
            selectors that produce them are pure and unit-pinned. */}
        <div className="mt-5">
          <ExecutiveSummary tiles={execTiles} />
        </div>

        {/* The view switcher lives INSIDE the lit band, under the title and
            beside nothing — so the light rig frames the page's whole chrome
            (title, period, summary, view) the way the Dashboard's hero frames
            its KPI strip, and the first panel begins on unlit ground. */}
        <div className="mt-5">
          <SegmentedControl
            items={TAB_ITEMS}
            value={tab}
            onChange={setTab}
            ariaLabel="Analytics views"
            idPrefix="analytics-tabs"
            panelIdPrefix="analytics-panel"
            testId="analytics-tabs"
          />
        </div>
      </section>

      {error ? (
        <p
          data-prose="status"
          data-prose-source="server"
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
        >
          {error}
        </p>
      ) : null}

      {/* ══ VIEW 1 — OVERVIEW (default) ══════════════════════════════════
          Where the search stands: the period-scoped KPI band, the policy the
          agents are obeying right now, and the funnel those numbers came
          from, with its conversion column beside it. */}
      <div {...panelProps("overview")} className="space-y-7">

      {dashboard === null && !error ? (
        /* Space reservation while the summary loads — rendering nothing and
           then inserting the 7-card grid shifted every section below it
           (CLS 0.67 on prod load, W-E quality sweep). */
        <section aria-busy="true" data-testid="dashboard-summary-loading">
          <div className="mb-3 h-5 w-56 animate-pulse rounded bg-white/5" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-12">
            {SUMMARY_SPANS.map((span, i) => (
              <div key={i} className={`elev-1 h-[116px] rounded-2xl p-5 ${span}`}>
                <div className="h-2.5 w-24 animate-pulse rounded bg-white/10" />
                <div className="mt-4 h-7 w-16 animate-pulse rounded bg-white/5" />
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {dashboard ? (
        <section data-testid="dashboard-summary">
          {/* Every field on this card is period-scoped server-side (GET
              /analytics/dashboard?period=..., MV-analytics-004) — say so
              the same way the sibling funnel/conversion sections do,
              instead of leaving this the only section with no period
              indicator. */}
          <h2 className="type-section mb-3">Dashboard summary ({period})</h2>
          {/*
            THE DEAD 4-COL SLOT, KILLED. Seven cards in a `lg:grid-cols-4` grid
            occupy 7 of 8 cells and leave one visibly empty box on the second
            row — an empty card is an implicit claim that content exists (the
            same defect class as X-10). A 12-column grid divides exactly: four
            cards at `col-span-3` fill row one, three at `col-span-4` fill row
            two, with no orphan cell at any breakpoint.
          */}
          <dl className="grid grid-cols-2 gap-4 lg:grid-cols-12">
          {SUMMARY_CARDS(dashboard).map(({ label, value, unit, resource }, i) => (
            <StatBlock
              key={label}
              label={label}
              value={value}
              unit={unit}
              resource={resource}
              className={SUMMARY_SPANS[i]}
              testId={`summary-${label.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "")}`}
            >
              <MetricTooltip
                value={value}
                tooltip={SUMMARY_TIP[label] ?? "See the analytics glossary for how this metric is calculated."}
              />
            </StatBlock>
          ))}
          </dl>
        </section>
      ) : null}

      {/* U-AX item 2(a): the self-improvement loop's live state — the exact
          tier every real agent is currently obeying, why, and what it
          changes. Additive to the page; a load failure leaves it absent
          rather than blocking anything above.

          It stays in THIS view, above stage conversion, because the
          conversion gap sentence below points the reader at it by name and
          by direction (R-05). */}
      {policy ? <AgentPolicyPanel policy={policy} /> : null}

      {/*
        §5.2 — the funnel and the stage-conversion figures it implies now sit
        side by side instead of stacking as two full-width sections saying
        overlapping things about the same five stages.
      */}
      <div className="grid gap-6 xl:grid-cols-12 xl:items-start">
      <section className="elev-1 rounded-2xl p-5 xl:col-span-7" data-testid="funnel-chart">
        {/*
          The PERIOD-scoped heading lives here, on the section, and the chart
          carries a complementary title ("Volume by stage") rather than
          repeating it. That is deliberate: `<ChartFrame>` mirrors its `title`
          into the sr-only data table's `<caption>`, so a title containing
          "(7d)" would put that exact string on screen twice and make an
          unqualified text query ambiguous.
        */}
        <h2 className="type-section">Application funnel ({period})</h2>
        {funnel === null ? (
          <div className="mt-4 space-y-3" aria-busy="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-lg bg-white/5" />
            ))}
          </div>
        ) : (
          /*
           * On the chart kit. The bars above used `Math.max(4, …)`, so a stage
           * with 0 rows drew a 4%-wide COLOURED bar — a measured nothing that
           * looked like a small something (Rule D-3 / law C-1, and the exact
           * defect X-8 filed). `<Funnel>` draws a zero as a hairline tick with
           * the numeral in `state-neutral`, and states its own window (C-3).
           */
          <div className="mt-4">
            <FunnelChart
              title="Volume by stage"
              windowLabel={
                period === "all"
                  ? "all time — every stage counted since your first discovery run"
                  : `the selected period (${period}) — stages are counted within it`
              }
              steps={funnelSteps(funnel)}
              mode="share-of-previous"
              /* The superset qualifier was reachable only by hovering a bar
                 (it rides on the step's `note`, into the hidden data table and
                 the row title). A qualifier of a VISIBLE number may not be
                 hover-only — U-AX law — so it is also stated here, in the
                 frame's reserved caption slot, beside the chart it qualifies. */
              footnote="“Jobs found” is cumulative all-time discovery; the Jobs board lists only currently-open postings, so its count is usually lower."
            />
          </div>
        )}
      </section>

      <section className="elev-1 rounded-2xl p-5 xl:col-span-5" data-testid="conversion-rates">
        <h2 className="type-section">Stage conversion ({period})</h2>
        {conversion === null ? (
          <div className="mt-4 h-24 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
        ) : (
          <>
            <dl className="mt-4 grid grid-cols-2 gap-3">
              {(
                [
                  ["Found → Applied", conversion.found_to_applied],
                  ["Applied → Screened", conversion.applied_to_screened],
                  ["Screened → Interview", conversion.screened_to_interview],
                  ["Interview → Offer", conversion.interview_to_offer],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="rounded-xl border border-white/10 p-4 text-center">
                  <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-violet">
                    <MetricTooltip value={`${value}%`} tooltip={CONVERSION_TIP[label] ?? "Conversion rate between two consecutive funnel stages."} />
                  </dd>
                  <dt className="mt-1 text-xs text-aether-muted">{label}</dt>
                </div>
              ))}
            </dl>
            {/* GOLD-MASTER V4 §6 / G-C: interview_conversion_rate — real,
                correct on the backend (interviews / submitted applications)
                but previously stripped client-side because ConversionSchema
                never declared the field. Rendered exactly as the API
                returns it; the badge only changes FRAMING (color/label),
                never the rate.

                ANALYTICS-VIZ: the rate and the target it is judged by were a
                numeral and a SENTENCE that asked the reader to subtract one
                from the other. They are now a bullet row and a labelled target
                tick — the same two numbers, with the comparison drawn instead
                of described. The denominator ("N interviews from M submitted")
                rides on the row, so a percentage is never shown without the
                count it came from. */}
            <div className="mt-4" data-testid="interview-conversion-rate">
              <BulletChart
                title="Interview conversion vs the 1-in-5 target"
                windowLabel={
                  period === "all"
                    ? "all time — interviews per application submitted"
                    : `the selected period (${period}) — interviews per application submitted`
                }
                rows={[
                  {
                    label: "Interview conversion",
                    value: conversion.interview_conversion_rate,
                    display: `${conversion.interview_conversion_rate}%`,
                    basis:
                      funnel === null
                        ? undefined
                        : `${funnel.interviewed} interview${
                            funnel.interviewed === 1 ? "" : "s"
                          } from ${funnel.applied} submitted`,
                    trailing: !hasApplications ? (
                      <span
                        className="rounded-full border border-white/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-aether-muted"
                        data-testid="interview-conversion-badge"
                      >
                        No applications yet
                      </span>
                    ) : conversion.interview_conversion_healthy ? (
                      <span
                        className="rounded-full border border-aether-green/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-aether-green"
                        data-testid="interview-conversion-badge"
                      >
                        On track (≥1:5)
                      </span>
                    ) : (
                      <span
                        className="rounded-full border border-aether-amber/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-aether-amber"
                        data-testid="interview-conversion-badge"
                      >
                        Needs improvement (&lt;1:5)
                      </span>
                    ),
                  },
                ]}
                target={{
                  value: conversionTargetPct,
                  label: `${conversionTargetPct}% (1-in-5) target`,
                }}
                axisMax={Math.max(
                  conversionTargetPct * 1.5,
                  conversion.interview_conversion_rate * 1.15,
                )}
              />
            </div>
            {/* U-AX item 1/2 — the gap, and what the policy is DOING about it,
                as the ONE-LINE caption attached to the chart above.

                F-UAX-04: this figure honours the selected period, while the
                Agent Performance Policy tier is computed ALL-TIME
                (quality_policy.resolve_policy_for_user) — the two can
                legitimately disagree, so the claim about what the policy is
                doing is sourced from the policy's OWN tier, never asserted
                unconditionally. `heightened` is the only tier that actually
                escalates rigor; `insufficient_data` explicitly does not
                (quality_policy.py rule 2) and must say so.
                R-05: `AgentPolicyPanel` renders ABOVE this section, so the
                pointer says "above" and the test pins that against the real
                DOM order. */}
            {hasApplications ? (
              <p
                data-prose="caption"
                className="mt-2 text-[11px] leading-[1.45] text-aether-muted-dim"
                data-testid="interview-conversion-gap"
              >
                {conversion.interview_conversion_rate >= conversionTargetPct
                  ? `At or above the 1-in-5 (${conversionTargetPct}%) target — Agent Performance Policy, above.`
                  : policy?.tier === "heightened"
                    ? `${(conversionTargetPct - conversion.interview_conversion_rate).toFixed(1)} points to target — rigor escalated to heightened (Agent Performance Policy, above).`
                    : policy?.tier === "insufficient_data"
                      ? `${(conversionTargetPct - conversion.interview_conversion_rate).toFixed(1)} points to target — too few submissions all-time to escalate (Agent Performance Policy, above).`
                      : `${(conversionTargetPct - conversion.interview_conversion_rate).toFixed(1)} points to target — rigor escalates automatically at the policy's own threshold (Agent Performance Policy, above).`}
              </p>
            ) : null}
          </>
        )}
      </section>

      </div>
      </div>

      {/* ══ VIEW 2 — QUALITY & ROI ═══════════════════════════════════════
          How good the matches actually are, whether the rigor policy that
          governs them is working, and what the whole thing cost: the ATS
          spread and the fit radar on one row, the policy's own history and
          per-tier cohort outcomes on the next, agent ROI closing the view. */}
      <div {...panelProps("quality")} className="space-y-7">

      {/*
        THE QUALITY BAND — recomposed (doctrine D-δ; §8 leaves per-page layout
        to the batch team inside the doctrine).

        It was `lg:grid-cols-2` holding ATS distribution + Agent ROI, with the
        Fit profile radar dropped full-width beneath. A radar's mark is
        `min(plotWidth, plotHeight) / 2` — so at a 1300px card and a 300px
        height it drew a ~116px figure marooned in ~1150px of empty card,
        while ATS and ROI were both squeezed into half a page. Three panels,
        none of them the shape its content wanted.

        ATS distribution and Fit profile are the same question asked twice —
        how well do these roles actually fit — so they pair, 7/5, with the
        histogram taking the width its ten buckets need and the radar taking a
        column it can fill. Agent ROI is the other question (what this cost)
        and gets the full measure below, where its two stat rows read as a
        panel rather than a squeeze. `items-start` so nothing stretches.
      */}
      <div className="grid gap-6 xl:grid-cols-12 xl:items-start">
        <section
          className={`elev-1 rounded-2xl p-5 ${policy ? "xl:col-span-7" : "xl:col-span-12"}`}
          data-testid="ats-distribution"
        >
          <h2 className="flex items-center gap-1.5">
            <MetricTooltip
              label="ATS score distribution"
              value=""
              tooltip="How your scored jobs are spread across ATS/AI fit-score bands (0–100) — higher bands mean stronger keyword and experience matches."
            />
            {/* This panel has no period support server-side (MV-analytics-004)
                — say so honestly instead of silently ignoring the selector
                above like it applies here too. */}
            <span className="type-meta font-normal normal-case">
              (all time — not affected by the period selector)
            </span>
          </h2>
          {ats === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            /*
             * On the chart kit — three defects closed at once:
             *  - `Math.max(2, …)` drew a 2px VIOLET bar for an empty bucket, so
             *    "no résumés scored 0-19" looked like "a couple did" (C-1/X-8);
             *  - the axis label was `range.split("-")[0]`, i.e. the band "0-19"
             *    printed as the single value "0" (X-9);
             *  - there were no gridlines and no y-axis at all, which is the
             *    reference pack's rule-5 violation the audit filed by name.
             */
            <div className="mt-4">
              <Histogram
                title="ATS score distribution"
                windowLabel={`all time — ${ats.total} scored ${ats.total === 1 ? "job" : "jobs"}, not affected by the period selector`}
                buckets={atsBuckets(ats)}
                itemNoun="jobs"
              />
            </div>
          )}
        </section>

        {/*
          §5.2 NEW — the 10-dimension fit profile. Its data is
          `AgentPolicy.metricSnapshot.dimensionScores`, which this page ALREADY
          fetches via `GET /analytics/agent-policy`: no new endpoint, no new
          request. `<Radar10>` is the chart the spec calls "the single most
          dangerous in the product" — a dimension the scorer never evaluated
          gets a hollow marker on the outer ring and a struck-through label,
          never a vertex at the centre, because a centre vertex is a specific
          false claim about the candidate rather than an absence of one.

          `height` is raised from the 300px default because the radar's radius
          is `min(plotWidth, plotHeight) / 2 - 34`: in a five-column card the
          height is what binds, and 300 drew a figure far smaller than the
          frame around it.
        */}
        {policy ? (
          <Section
            testId="fit-profile"
            className="xl:col-span-5"
            footnote={
              policy.metricSnapshot.dimensionSampleSize
                ? `Scored across ${policy.metricSnapshot.dimensionSampleSize} evaluated ${
                    policy.metricSnapshot.dimensionSampleSize === 1 ? "application" : "applications"
                  }.`
                : "No application has been scored on these dimensions yet — every axis is shown as unmeasured rather than as a zero."
            }
          >
            <Radar10
              title="Fit profile"
              windowLabel="all time — the dimensions the scorer has actually evaluated for you"
              dimensions={fitDimensions(policy.metricSnapshot.dimensionScores)}
              expectedDimensions={10}
              height={360}
            />
          </Section>
        ) : null}
      </div>

      {/* U-AX item 2(c) + item 3 (R-06): the tier's own history against the
          metrics it responds to, and the outcome of the applications actually
          submitted under each tier. Round 2 claimed 2(c) in a comment and
          shipped neither surface. */}
      {/* `lg:items-start`, matching every other paired row on this page. A
          bare `lg:grid-cols-2` stretches both cards to the taller one's
          height: the cohort panel has three short rows against the tier
          history's four tall ones, so it was drawing ~340px of empty card
          interior below its last line — the same dead-space defect the
          closing band was recomposed to remove, just further down the page
          where the old 3,737px scroll hid it. */}
      {policyHistory || policyCohorts ? (
        <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
          {policyHistory ? <PolicyTierHistory history={policyHistory} /> : null}
          {policyCohorts ? <PolicyCohortProgress cohorts={policyCohorts} /> : null}
        </div>
      ) : null}

        {/* What the agents cost, and what each outcome cost — including the
            two places the honest answer is "—" rather than a number. */}
        <section className="elev-1 rounded-2xl p-5" data-testid="agent-roi">
          <h2 className="type-section flex items-center gap-1.5">
            Agent ROI
            {/* No period support server-side (MV-analytics-004) — honest
                label instead of silently ignoring the selector above. */}
            <span className="type-meta font-normal normal-case">
              (all time — not affected by the period selector)
            </span>
          </h2>
          {roi === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            /* U-UI ANALYTICS-STAT-TILE-OVERFLOW: a hard `grid-cols-3` at a
             * 390px mobile viewport left each tile ~61px wide — too narrow
             * for `text-2xl` values ("$8.16", "166.0s"), which measured
             * 22–59% wider than their box. Stack to one column below the
             * `sm` breakpoint (matching the responsive `dl` grids used
             * elsewhere on this page) so every tile keeps its full-width
             * value on screen; unchanged from `sm` up. */
            <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-green">
                  <MetricTooltip
                    value={`$${roi.total_cost_usd.toFixed(2)}`}
                    tooltip="Cumulative LLM API cost across all agent runs in this period."
                  />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Total spend</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold">
                  <MetricTooltip value={roi.total_runs} tooltip="Total number of agent executions recorded in this period." />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Agent runs</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-amber">
                  <MetricTooltip
                    value={`${(roi.avg_duration_ms / 1000).toFixed(1)}s`}
                    tooltip="Average wall-clock time per agent run in this period."
                  />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Avg duration</dt>
              </div>
            </dl>
          )}

          {/*
            §5.2 — cost per application / per interview, "computed only when
            denominator > 0 else —".

            There is a SECOND precondition the spec's one-liner does not state
            and that this panel must not quietly ignore: `roi` is ALL-TIME
            (no period support server-side) while `funnel` is period-scoped.
            Dividing an all-time cost by a 7-day application count would
            produce a confident number that describes nothing real. So the
            ratio is computed only when the selector is on `all`, and otherwise
            says which two windows failed to line up.
          */}
          {roi ? (
            <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2" data-testid="agent-roi-derived">
              {(
                [
                  [
                    "Cost per application",
                    funnel?.applied ?? 0,
                    "Total agent spend divided by applications submitted. Both figures are all-time.",
                  ],
                  [
                    "Cost per interview",
                    funnel?.interviewed ?? 0,
                    "Total agent spend divided by applications that reached an interview. Both figures are all-time.",
                  ],
                ] as const
              ).map(([label, denominator, tip]) => {
                const comparable = period === "all" && funnel !== null;
                const measurable = comparable && denominator > 0;
                return (
                  <div key={label} className="rounded-xl border border-white/10 p-4 text-center">
                    <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-green">
                      {measurable ? (
                        <MetricTooltip
                          value={`$${(roi.total_cost_usd / denominator).toFixed(2)}`}
                          tooltip={tip}
                        />
                      ) : (
                        <span className="text-aether-muted-dim">—</span>
                      )}
                    </dd>
                    <dt className="mt-1 text-xs text-aether-muted">{label}</dt>
                    {/* ANALYTICS-VIZ: the reason a ratio is “—” stays on the
                        tile, at the same size, demoted from a free-standing
                        block to the CAPTION of the tile it qualifies. The
                        wording is tightened to one line; the two facts it
                        carries (which windows failed to line up / which
                        denominator is empty) are unchanged. */}
                    {!measurable ? (
                      <p data-prose="caption" className="type-meta mt-1">
                        {!comparable
                          ? `Spend is all-time, funnel is ${period} — select “all” to divide like with like.`
                          : "No application has reached this stage yet — nothing to divide by."}
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </dl>
          ) : null}
        </section>
      </div>

      {/* ══ VIEW 3 — MARKET ══════════════════════════════════════════════
          The outside world: MarketPulse keeps its own composition, its own
          freshness stamps and its own retry affordance, whole and unedited —
          it simply stops competing for attention with the two views before
          it. It mounts with the page (never on tab switch), so its 8-15s
          request starts at the same instant it always did. */}
      <div {...panelProps("market")} className="space-y-7">
        <MarketPulse />
      </div>
    </div>
  );
}
