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
import { ConfirmPanel, formatAudExact, StatTile } from "../../components/admin/admin-ui";
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
import { DecisionGuidance } from "../../components/ui/decision-guidance";
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
  fetchAdminBillingSummary,
  fetchAdminUsers,
  fetchAuditLog,
  fetchHygiene,
  purgeOrphans,
  type AdminBillingSummary,
  type AdminHygiene,
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
  const [billing, setBilling] = useState<AdminBillingSummary | null>(null);
  const [hygiene, setHygiene] = useState<AdminHygiene | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [hygieneError, setHygieneError] = useState<string | null>(null);
  // Purge-orphans is a real write (unlike the other three reads on this
  // board), so it gets its own confirm + busy state rather than piggybacking
  // on the poll.
  const [purgeOrphansOpen, setPurgeOrphansOpen] = useState(false);
  const [purgeOrphansBusy, setPurgeOrphansBusy] = useState(false);
  const [purgeOrphansError, setPurgeOrphansError] = useState<string | null>(null);
  const [purgeOrphansMessage, setPurgeOrphansMessage] = useState<string | null>(null);
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
     * The five reads are independent and are settled independently: a failing
     * audit-log call must not blank the revenue board, and a failing metrics
     * call must not blank the signup strip. Each failure is reported on the
     * surface it belongs to.
     */
    const [metricsResult, usersResult, auditResult, billingResult, hygieneResult] =
      await Promise.allSettled([
        fetchAdminExecutiveMetrics(),
        fetchAdminUsers({}),
        fetchAuditLog(RECENT_ACTIONS, 0),
        fetchAdminBillingSummary(),
        fetchHygiene(),
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

    if (billingResult.status === "fulfilled") {
      setBilling(billingResult.value);
      setBillingError(null);
    } else {
      const e = billingResult.reason;
      setBillingError(e instanceof Error ? e.message : "unknown error");
    }

    if (hygieneResult.status === "fulfilled") {
      setHygiene(hygieneResult.value);
      setHygieneError(null);
    } else {
      const e = hygieneResult.reason;
      setHygieneError(
        `The stale-data report could not be loaded: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    }

    setRefreshing(false);
    setFirstLoad(false);
  }, []);

  const onPurgeOrphans = async () => {
    setPurgeOrphansBusy(true);
    setPurgeOrphansError(null);
    try {
      await purgeOrphans();
      setPurgeOrphansOpen(false);
      setPurgeOrphansMessage("Orphaned billing pairs purged.");
      await load();
    } catch (e) {
      setPurgeOrphansError(e instanceof Error ? e.message : "Could not purge orphaned rows.");
    } finally {
      setPurgeOrphansBusy(false);
    }
  };

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

  /**
   * Signups over the last 7 days, summed from the executive metrics' own
   * daily series (oldest-first, ending today — `admin_metrics._window_dates`).
   * `null` when the block itself is absent, which renders as an honest
   * "Not measured" rather than a fabricated 0.
   */
  const signups7d = useMemo(() => {
    const series = metrics?.signupsByDay?.series;
    if (!series || series.length === 0) return null;
    return series
      .slice(-7)
      .reduce((sum, day) => sum + (typeof day.count === "number" ? day.count : 0), 0);
  }, [metrics]);

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

          <Panel
            title="Sales AI"
            testId="admin-exec-sales-ai"
            measured={metrics?.salesAi != null}
            caption="native outreach agent — not human resellers"
            action={
              <Link
                href="/admin/sales-agent"
                className="type-mono-micro text-aether-coral hover:underline"
              >
                Open →
              </Link>
            }
            guidance={{
              tellsYou:
                "whether the in-app Sales AI agent is live or in shadow mode, how many emails it has actually sent, and how many inbound replies it has observed. Signups are not attributed to it.",
              next: "open /admin/sales-agent, read the Strategy tab, and post LinkedIn drafts yourself. Do not treat this panel as revenue.",
            }}
          >
            {metrics?.salesAi ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <p className="type-mono-micro text-aether-muted-dim">Mode</p>
                  <p className="mono text-sm font-semibold tabular-nums text-aether-text">
                    {metrics.salesAi.enabled === false
                      ? "Disabled"
                      : metrics.salesAi.dryRun
                        ? "Shadow"
                        : "Live"}
                  </p>
                </div>
                <div>
                  <p className="type-mono-micro text-aether-muted-dim">Emails sent</p>
                  <p className="mono text-sm font-semibold tabular-nums text-aether-text">
                    {metrics.salesAi.emailsSent ?? "Not measured"}
                  </p>
                </div>
                <div>
                  <p className="type-mono-micro text-aether-muted-dim">Replies observed</p>
                  <p className="mono text-sm font-semibold tabular-nums text-aether-text">
                    {metrics.salesAi.repliesObserved ?? "Not measured"}
                  </p>
                </div>
                <div>
                  <p className="type-mono-micro text-aether-muted-dim">Reply rate</p>
                  <p className="mono text-sm font-semibold tabular-nums text-aether-text">
                    {metrics.salesAi.replyRate == null
                      ? "Not measured"
                      : `${Math.round(metrics.salesAi.replyRate * 1000) / 10}%`}
                  </p>
                </div>
                <p className="type-meta col-span-2 sm:col-span-4 text-aether-muted">
                  {metrics.salesAi.cannotAttributeReason ??
                    "Signups cannot be attributed to Sales AI."}
                </p>
              </div>
            ) : (
              <p className="type-meta text-aether-muted">
                GET /admin/metrics/executive did not return a Sales AI block.
              </p>
            )}
          </Panel>

          {/* ADMIN-MGMT E2 — operator-facing figures the growth board above
              doesn't carry: revenue-side accounts (billing/summary, not the
              metrics payload's own admin-exempt revenue block), a 7-day
              signup count, and the one figure that genuinely is not measured
              yet (a 24h failed-run rate — `GET /admin/metrics/executive` has
              no such field; rather than compute a different-shaped number
              from a different endpoint and call it the same thing, this tile
              says so). Stale-data counts come from the read-only
              `GET /admin/hygiene` report and link straight to the screen that
              acts on each one. */}
          <section aria-labelledby="admin-ops-heading" data-testid="admin-ops-section">
            <h2 id="admin-ops-heading" className="type-section mb-2">
              Operations
            </h2>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-2 xl:grid-cols-4">
                <StatTile
                  testId="admin-ops-paying"
                  label="Paying accounts"
                  value={billing ? String(billing.paidSubscribers) : "Not measured"}
                  hint={
                    billingError
                      ? `Could not load: ${billingError}`
                      : billing
                        ? `${billing.excludedAdminRows} admin + ${billing.excludedDeletedRows} deleted excluded`
                        : undefined
                  }
                  tone={billing ? undefined : "neutral"}
                />
                <StatTile
                  testId="admin-ops-mrr"
                  label="MRR"
                  value={billing ? formatAudExact(billing.mrrAud) : "Not measured"}
                  hint={
                    billingError
                      ? `Could not load: ${billingError}`
                      : billing
                        ? `${billing.currency}${billing.estimate ? " · estimate" : ""}`
                        : undefined
                  }
                  tone={billing ? undefined : "neutral"}
                />
                <StatTile
                  testId="admin-ops-signups-7d"
                  label="Signups (7d)"
                  value={signups7d === null ? "Not measured" : String(signups7d)}
                  hint={
                    signups7d === null
                      ? "GET /admin/metrics/executive did not return a signups series."
                      : "Last 7 days, from the executive metrics signup series."
                  }
                  tone={signups7d === null ? "neutral" : undefined}
                />
                <StatTile
                  testId="admin-ops-failed-run-rate"
                  label="Failed-run rate (24h)"
                  value={
                    !metrics?.failedRuns24h
                      ? "Not measured"
                      : metrics.failedRuns24h.total === 0
                        ? "Not measured"
                        : metrics.failedRuns24h.insufficientData || metrics.failedRuns24h.rate == null
                          ? `${metrics.failedRuns24h.failed} / ${metrics.failedRuns24h.total}`
                          : `${Math.round((metrics.failedRuns24h.rate ?? 0) * 1000) / 10}%`
                  }
                  hint={
                    !metrics?.failedRuns24h
                      ? "GET /admin/metrics/executive did not return a 24h failed-run block."
                      : metrics.failedRuns24h.total === 0
                        ? "No agent runs in the last 24 hours."
                        : metrics.failedRuns24h.insufficientData || metrics.failedRuns24h.rate == null
                          ? `${metrics.failedRuns24h.failed} failed of ${metrics.failedRuns24h.total} runs. The rate is not readable below the sample threshold.`
                          : `${metrics.failedRuns24h.failed} failed of ${metrics.failedRuns24h.total} runs in 24h.`
                  }
                  tone={
                    !metrics?.failedRuns24h || metrics.failedRuns24h.total === 0
                      ? "neutral"
                      : (metrics.failedRuns24h.failed ?? 0) > 0
                        ? "warn"
                        : undefined
                  }
                />
                {/* R1.2 — one guidance line spanning the operations tiles. */}
                <DecisionGuidance
                  className="sm:col-span-2 xl:col-span-4"
                  tellsYou="revenue-side account counts and a 7-day signup figure from billing/summary and the metrics series — a tile that cannot be measured says so instead of showing zero."
                  next="if paying accounts or MRR moved since your last visit, open /admin/billing to see which subscription rows changed."
                />
              </div>

              <Panel
                title="Stale data"
                testId="admin-ops-stale-data"
                measured={hygiene != null}
                guidance={{
                  tellsYou:
                    "counts of rows the hygiene report flags as stale — soft-deleted users, orphaned billing pairs and canceled subscriptions still on record.",
                  next: "keep these at zero: use the linked screens to review each bucket, and only purge orphans after confirming the count matches expectation.",
                }}
              >
                {hygieneError ? (
                  <p className="type-meta text-aether-amber">{hygieneError}</p>
                ) : hygiene ? (
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="type-mono-micro text-aether-muted-dim">Soft-deleted</p>
                        <p className="mono text-lg font-semibold tabular-nums text-aether-text">
                          {hygiene.softDeletedUsers.count}
                        </p>
                      </div>
                      <Link
                        href="/admin/users?view=deleted"
                        className="type-mono-micro text-aether-indigo hover:underline"
                      >
                        View →
                      </Link>
                    </div>

                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="type-mono-micro text-aether-muted-dim">
                          Orphaned billing pairs
                        </p>
                        <p className="mono text-lg font-semibold tabular-nums text-aether-text">
                          {hygiene.orphanedBillingPairs.count}
                        </p>
                      </div>
                      <button
                        type="button"
                        data-testid="admin-ops-purge-orphans"
                        onClick={() => setPurgeOrphansOpen(true)}
                        disabled={hygiene.orphanedBillingPairs.count === 0}
                        className="type-mono-micro rounded-md border border-red-500/40 px-2.5 py-1.5 text-red-300 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        Purge orphans
                      </button>
                    </div>

                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="type-mono-micro text-aether-muted-dim">Canceled subs</p>
                        <p className="mono text-lg font-semibold tabular-nums text-aether-text">
                          {hygiene.canceledSubscriptions.count}
                        </p>
                      </div>
                      <Link
                        href="/admin/subscriptions?tab=canceled"
                        className="type-mono-micro text-aether-indigo hover:underline"
                      >
                        View →
                      </Link>
                    </div>

                    <p className="type-meta text-aether-muted-dim">
                      {hygiene.neverLoggedIn30d.count} account
                      {hygiene.neverLoggedIn30d.count === 1 ? "" : "s"} never logged in, 30+ days
                      old.
                    </p>

                    {purgeOrphansMessage && !purgeOrphansOpen ? (
                      <p role="status" className="type-meta text-aether-green">
                        {purgeOrphansMessage}
                      </p>
                    ) : null}

                    {purgeOrphansOpen ? (
                      <ConfirmPanel
                        tone="critical"
                        testId="admin-ops-purge-orphans-panel"
                        confirmTestId="admin-ops-purge-orphans-confirm"
                        cancelTestId="admin-ops-purge-orphans-cancel"
                        title={`Purge ${hygiene.orphanedBillingPairs.count} orphaned billing pair(s)?`}
                        confirmLabel="Purge orphans"
                        busy={purgeOrphansBusy}
                        onConfirm={() => void onPurgeOrphans()}
                        onCancel={() => {
                          setPurgeOrphansOpen(false);
                          setPurgeOrphansError(null);
                        }}
                        body={
                          <>
                            Deletes ONLY Subscription/UsageQuota rows whose userId has no
                            matching User row — nothing else. This does not touch Stripe.
                          </>
                        }
                      >
                        {purgeOrphansError ? (
                          <p role="alert" className="mt-2 text-sm text-red-300">
                            {purgeOrphansError}
                          </p>
                        ) : null}
                      </ConfirmPanel>
                    ) : null}
                  </div>
                ) : (
                  <Skeleton className="h-32" />
                )}
              </Panel>
            </div>
          </section>

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
