"use client";

/**
 * /admin — the EXECUTIVE DASHBOARD (ADMIN-2.0 FE-1).
 *
 * This screen replaces the old admin landing (a health block plus four quick
 * links). Health did not disappear: it has its own section at /admin/health,
 * which the restructured nav lists, and a compact live strip still sits at the
 * bottom of this page.
 *
 * ============================================================================
 * THE BRIEF, AND THE CONSTRAINT THAT SHAPES EVERY DECISION ON IT
 * ============================================================================
 * "Executive dashboard = scanned, not read." Summary before detail; state
 * encoded in form (pills, deltas, sparklines) rather than prose; figures in
 * tabular numerals so a column can be compared down its length; semantic
 * good/warn/critical kept separate from the brand accent.
 *
 * And the constraint: the platform has roughly TEN accounts and no external
 * paying subscribers today. So the honest-empty-state path is not an edge case
 * here — it is the DEFAULT path, and it has to look like a considered
 * executive surface rather than a broken one. Every panel has a designed empty
 * state at the panel's own size carrying the API's own reason, and nothing on
 * this page substitutes a zero for an absence.
 *
 * The board also follows BE-2's own rule about what small numbers mean: real
 * COUNTS are always shown; it is the RATE-shaped reading of them (percentages,
 * trends, conversion) that is gated behind the API's `insufficientData`. See
 * `lib/admin/executive.ts` › `rateReadable`.
 *
 * ============================================================================
 * DATA
 * ============================================================================
 * Three reads, polled together every 30 seconds with a manual refresh:
 *   · `GET /admin/metrics/executive` — the whole board's figures, one instant;
 *   · `GET /admin/users`             — the latest-signups strip;
 *   · `GET /admin/audit-log`         — the recent-actions strip.
 * The last two are endpoints /admin already ships and already authorises; the
 * metrics payload does not carry either list, and growing it was not this
 * slice's to do.
 *
 * A poll NEVER blanks the board: the last good payload stays in state while
 * the next request is in flight, so figures on screen stay put and only the
 * "updated" stamp moves. A failed poll raises a banner and leaves the previous
 * figures visible — replacing a real (if slightly stale) board with an empty
 * one on a transient blip is a downgrade, not a safety measure.
 *
 * Charts come from the repo's own kit (`components/charts`); no charting
 * dependency was added and `package.json` carries none to reuse.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AdminPageHeader } from "../../components/admin/admin-shell";
import { HealthOverview } from "../../components/admin/health-overview";
import {
  GrowthFunnelPanel,
  PlanMixPanel,
  RunVolumePanel,
  SignupTrendPanel,
} from "../../components/admin/executive/GrowthBand";
import { KpiBand } from "../../components/admin/executive/KpiBand";
import {
  LatestSignupsPanel,
  RecentAuditPanel,
  ReferrersPanel,
} from "../../components/admin/executive/OpsStrip";
import { Panel, Skeleton } from "../../components/admin/executive/panels";
import {
  buildFunnelSteps,
  buildKpiTiles,
  buildPlanMix,
  buildReferrers,
  buildRunSeries,
  buildSignupSeries,
} from "../../lib/admin/executive";
import {
  fetchAdminExecutiveMetrics,
  type AdminExecutiveMetrics,
} from "../../lib/api/adminMetrics";
import {
  fetchAdminUsers,
  fetchAuditLog,
  type AdminUser,
  type AuditEntry,
} from "../../lib/api/admin";
import { formatDateTime } from "../../lib/format";

/** 30s, per the brief. Long enough not to hammer a shared API from an admin
 *  tab left open all day; short enough that the board is never visibly stale. */
const POLL_MS = 30_000;
const LATEST_SIGNUPS = 5;
const RECENT_ACTIONS = 6;

/** Newest first, by signup time. Rows with no timestamp sort last rather than
 *  being dropped — an account with a missing `signupAt` still exists. */
function newestSignups(users: readonly AdminUser[]): AdminUser[] {
  return [...users]
    .sort((a, b) => {
      const at = a.signupAt ? Date.parse(a.signupAt) : Number.NaN;
      const bt = b.signupAt ? Date.parse(b.signupAt) : Number.NaN;
      if (Number.isNaN(at) && Number.isNaN(bt)) return 0;
      if (Number.isNaN(at)) return 1;
      if (Number.isNaN(bt)) return -1;
      return bt - at;
    })
    .slice(0, LATEST_SIGNUPS);
}

function KpiSkeletonBand() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="elev-1 rounded-2xl p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-28" />
          <Skeleton className="mt-4 h-6 w-full" />
          <Skeleton className="mt-3 h-3 w-3/4" />
        </div>
      ))}
    </div>
  );
}

function PanelSkeleton({ title, height }: { title: string; height: string }) {
  return (
    <Panel title={title}>
      <Skeleton className={height} />
    </Panel>
  );
}

export default function AdminExecutiveDashboardPage() {
  const [metrics, setMetrics] = useState<AdminExecutiveMetrics | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  /** True only until the FIRST attempt resolves — the one moment skeletons are
   *  honest, because nothing at all is known yet. */
  const [firstLoad, setFirstLoad] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setRefreshing(true);
    /*
     * The three reads are independent and are settled independently: a failing
     * audit-log call must not blank the revenue board, and a failing metrics
     * call must not blank the signup strip. Each failure is reported on the
     * surface it belongs to.
     */
    const [metricsResult, usersResult, auditResult] = await Promise.allSettled([
      fetchAdminExecutiveMetrics(),
      fetchAdminUsers({}),
      fetchAuditLog(RECENT_ACTIONS, 0),
    ]);
    if (!mounted.current) return;

    if (metricsResult.status === "fulfilled") {
      setMetrics(metricsResult.value);
      setError(null);
      setLoadedAt(new Date().toISOString());
    } else {
      const e = metricsResult.reason;
      setError(e instanceof Error ? e.message : "Failed to load executive metrics");
    }

    if (usersResult.status === "fulfilled") {
      setUsers(newestSignups(usersResult.value.users));
      setUsersError(null);
    } else {
      const e = usersResult.reason;
      setUsersError(
        `The account list could not be loaded: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    }

    if (auditResult.status === "fulfilled") {
      setAudit(auditResult.value.entries);
      setAuditError(null);
    } else {
      const e = auditResult.reason;
      setAuditError(
        `The audit trail could not be loaded: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    }

    setRefreshing(false);
    setFirstLoad(false);
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      void load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const tiles = useMemo(() => buildKpiTiles(metrics), [metrics]);
  const funnel = useMemo(() => buildFunnelSteps(metrics), [metrics]);
  const planMix = useMemo(() => buildPlanMix(metrics), [metrics]);
  const signups = useMemo(() => buildSignupSeries(metrics), [metrics]);
  const runs = useMemo(() => buildRunSeries(metrics), [metrics]);
  const referrers = useMemo(() => buildReferrers(metrics), [metrics]);

  const showSkeletons = firstLoad && metrics === null;

  return (
    <div>
      <AdminPageHeader
        title="Executive dashboard"
        subtitle="Revenue, growth and cost at a glance. Every figure is a real query — an unmeasured figure says so rather than showing a zero."
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="type-meta" data-testid="admin-exec-freshness">
          {loadedAt ? `Updated ${formatDateTime(loadedAt)}` : "Loading…"}
          {metrics?.asOf ? ` · measured by the API at ${formatDateTime(metrics.asOf)}` : ""}
          {` · auto-refreshes every ${POLL_MS / 1000}s`}
        </p>
        <div className="flex items-center gap-2">
          <Link
            href="/admin/users"
            className="type-mono-micro rounded-lg border border-white/10 px-2.5 py-1.5 text-aether-muted transition-colors hover:border-white/20 hover:text-aether-text"
          >
            All users →
          </Link>
          <button
            type="button"
            onClick={() => void load()}
            disabled={refreshing}
            className="type-mono-micro rounded-lg border border-white/10 px-2.5 py-1.5 text-aether-muted transition-colors hover:border-white/20 hover:text-aether-text disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error ? (
        <div
          data-testid="admin-exec-error"
          role="alert"
          className="mb-4 rounded-xl border border-aether-amber/40 bg-aether-amber/10 px-4 py-3 text-[13px] text-aether-amber"
        >
          Executive metrics could not be loaded: {error}
          {metrics ? " — the figures below are from the last successful read." : ""}
        </div>
      ) : null}

      {showSkeletons ? (
        <div className="flex flex-col gap-4">
          <KpiSkeletonBand />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <PanelSkeleton title="Signups by day" height="h-40" />
            <PanelSkeleton title="Signup → paid milestones" height="h-40" />
            <PanelSkeleton title="Plan mix" height="h-40" />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <KpiBand tiles={tiles} />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <SignupTrendPanel model={signups} />
            <GrowthFunnelPanel model={funnel} />
            <div className="flex min-w-0 flex-col gap-4">
              <PlanMixPanel model={planMix} />
              <RunVolumePanel model={runs} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <ReferrersPanel model={referrers} />
            <LatestSignupsPanel rows={users} error={usersError} />
            <RecentAuditPanel rows={audit} error={auditError} />
          </div>

          {/* Service health keeps a presence on the landing screen — it is the
              one thing an operator opens /admin to check when something feels
              wrong — while its full detail lives at /admin/health. */}
          <section aria-labelledby="admin-health-heading">
            <h2 id="admin-health-heading" className="type-section mb-2">
              Service health
            </h2>
            <HealthOverview />
          </section>

          {/* Provenance, once, at the foot of the board. Every claim above is
              already labelled on its own tile; this is the page-level note a
              reader needs to interpret the two currency columns. */}
          <p className="type-meta" data-testid="admin-exec-footnote">
            Revenue is {metrics?.currencies?.revenue ?? "A$"} and LLM cost is{" "}
            {metrics?.currencies?.llmCost ?? "US$"}; the API applies no exchange rate and reports no
            combined margin, so the two are never netted here either.
            {metrics?.gstRegistered === false
              ? " Figures exclude GST — this business is not GST-registered."
              : ""}
          </p>
        </div>
      )}
    </div>
  );
}
