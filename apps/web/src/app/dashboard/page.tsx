"use client";

/**
 * Dashboard home (wireframe design/screens/dashboard.html): live stat cards,
 * agent activity feed, today's top opportunities, the Application Funnel,
 * Story Bank quick access, Recruiter CRM summary, the Needs Approval queue
 * (approve/reject wired to POST /approvals — REQ-TM-05/J4) and the Market
 * Intelligence snapshot. Every figure hydrates from the live API per
 * REQ-TM-10 — nothing is hardcoded (funnel is data-driven per audit D11).
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import DashboardStats from "../../components/dashboard/DashboardStats";
import { useRealtimeResources } from "../../hooks/useRealtime";
import { useNow } from "../../hooks/useNow";
import MarketPulse from "../../components/analytics/MarketPulse";
import ActivityTicker from "../../components/telemetry/ActivityTicker";
import Section from "../../components/ui/Section";
import { Funnel as FunnelChart } from "../../components/charts";
import { funnelSteps } from "../../lib/analytics/chart-adapters";
import {
  agentDisplayName,
  agentTile,
  describeRun,
  relTime,
  runBadge,
} from "../../components/dashboard/feed";
import { activityMessageAfterAgentName, humanizeActivityMessage } from "../../lib/humanize";
import { fetchAgentRuns, type AgentRun } from "../../lib/api/agents";
import { fetchFunnel, type Funnel } from "../../lib/api/analytics";
import { decideApproval } from "../../components/approvals/api";
import { fetchApprovals, type Approval } from "../../lib/api/approvals";
import { apiRequest, ApiError } from "../../lib/api/client";
import type { Job } from "../../lib/api/jobs";
import { fetchStories, type Story } from "../../lib/api/stories";
import { fetchNetworkingSummary, type NetworkingSummary } from "../../lib/api/workspaces";

/** /jobs rows carry salary columns the shared zod schema doesn't surface. */
type DashboardJob = Job & {
  salaryMin?: number | null;
  salaryMax?: number | null;
  currency?: string | null;
};

// CLI-D3 refix (audit wf_9a87f76f-eaa, attack-1): filtering matches on
// `runBadge(r).label`, and "Submitted" is now transmission-proven only
// (components/dashboard/feed.ts submissionRunBadge — output.submissionState
// === "transmitted"). A submission run that merely queued an approval carries
// the "Needs approval" badge, so this filter can no longer group
// never-transmitted applications under "Submitted".
const FEED_FILTERS = ["All", "Discovered", "Tailored", "Submitted", "Waiting"] as const;

function initials(company: string) {
  const parts = company.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "•";
  return parts
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function salaryLabel(job: DashboardJob): string {
  if (job.salaryMin != null && job.salaryMax != null) {
    const k = (n: number) => `AU$${Math.round(n / 1000)}k`;
    return `${k(job.salaryMin)} – ${k(job.salaryMax)}`;
  }
  return `via ${job.source}`;
}

/** Approval card title from the gated action payload. */
function approvalTitle(a: Approval): string {
  const kind = (a.payload as { kind?: string }).kind;
  if (kind === "cover_letter") return "Send cover letter";
  if (a.type === "email_send") return "Send email";
  if (a.type === "offer_response") return "Respond to offer";
  return "Submit application";
}

/**
 * A clean, honest, non-technical message for an approve/reject failure
 * (MV-dashboard-009). The raw ApiError message deliberately carries the HTTP
 * method, endpoint path, record id, status code and a raw JSON body (see
 * lib/api/client.ts) for developer logging — none of that belongs in a
 * user-facing toast. A 409/404 specifically means someone else already
 * resolved this request (another tab, another session, the approvals page).
 */
function describeApprovalError(e: unknown, action: "approve" | "reject"): string {
  if (e instanceof ApiError) {
    if (e.status === 409) return "This request was already handled — no action needed.";
    if (e.status === 404) return "This request no longer exists.";
  }
  return `Couldn't ${action} this request — please try again.`;
}

/**
 * Widget state with an explicit error channel (no fake-empty states).
 *
 * W-RT: this was load-ONCE — it fetched on mount and had no way to fetch again,
 * which is why the whole home screen froze at whatever was true when it opened.
 * It now exposes `reload`, so the shared realtime channel can refresh exactly
 * the widgets whose underlying rows really changed.
 */
function useLoad<T>(load: () => Promise<T>): {
  data: T | null;
  error: string | null;
  setData: (value: T) => void;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const aliveRef = useRef(true);

  const reload = useCallback(() => {
    loadRef
      .current()
      .then((value) => {
        if (aliveRef.current) {
          setData(value);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (aliveRef.current) setError(e instanceof Error ? e.message : "request failed");
      });
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    reload();
    return () => {
      aliveRef.current = false;
    };
  }, [reload]);
  return { data, error, setData, reload };
}

function WidgetError({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
      {children}
    </p>
  );
}

export default function DashboardPage() {
  const funnel = useLoad<Funnel>(() => fetchFunnel("all"));
  const weekly = useLoad<Funnel>(() => fetchFunnel("7d"));
  const jobs = useLoad<DashboardJob[]>(() => apiRequest<DashboardJob[]>("/jobs?sort=fitScore"));
  const runs = useLoad<AgentRun[]>(() => fetchAgentRuns());
  const stories = useLoad<Story[]>(() => fetchStories());
  const crm = useLoad<NetworkingSummary["crmSummary"]>(() =>
    fetchNetworkingSummary().then((n) => n.crmSummary),
  );
  const approvals = useLoad<Approval[]>(() => fetchApprovals("pending"));

  // W-RT — the shared realtime channel. Each widget is refreshed by the
  // resource it is actually built from, so an agent run does not blanket-refetch
  // the whole page and a change to one table cannot silently leave another
  // widget's numbers behind. `funnel`/`weekly` are derived from Jobs +
  // Applications, so they follow both.
  useRealtimeResources(["jobs", "applications"], () => {
    funnel.reload();
    weekly.reload();
  });
  useRealtimeResources(["jobs"], () => jobs.reload());
  useRealtimeResources(["agentRuns"], () => runs.reload());
  useRealtimeResources(["stories"], () => stories.reload());
  useRealtimeResources(["contacts", "outreach"], () => crm.reload());
  useRealtimeResources(["approvals"], () => approvals.reload());

  // CRITICAL-2. The channel above covers everything that changes because the
  // SERVER changed it. A run going stale is different: no row moves and no
  // event fires — the run simply stops being plausible as time passes. Without
  // this tick, the Agent Activity feed would keep an "in progress" line on
  // screen indefinitely for a run whose worker died while the tab was open,
  // which is exactly how a week of inactivity got hidden. It issues no
  // requests; it only re-renders so `runBadge`/`describeRun` are re-evaluated.
  useNow();

  const [feedFilter, setFeedFilter] = useState<(typeof FEED_FILTERS)[number]>("All");
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);
  const [approvalActionError, setApprovalActionError] = useState<string | null>(null);

  // Toast state for approval confirmations
  const [toast, setToast] = useState<{ message: string; kind: "success" | "error" } | null>(null);

  /** Show a temporary toast notification (auto-dismisses after 3.5 s). */
  function showToast(message: string, kind: "success" | "error" = "success") {
    setToast({ message, kind });
    setTimeout(() => setToast(null), 3500);
  }

  const scoredJobs = (jobs.data ?? []).filter((j) => j.fitScore != null);
  const avgFit =
    scoredJobs.length > 0
      ? scoredJobs.reduce((sum, j) => sum + Number(j.fitScore), 0) / scoredJobs.length
      : null;
  const topJobs = (jobs.data ?? []).slice(0, 3);
  const pending = approvals.data ?? [];
  // MV-dashboard-009: the live, independently-fetched set of genuinely
  // pending approval ids — the source of truth for whether an inline
  // Approve control should render, rather than the stale
  // AgentRun.output.approval_status snapshot cached at generation time.
  const pendingApprovalIds = new Set(pending.map((a) => a.id));

  async function resolveApproval(
    id: string,
    action: "approve" | "reject",
    acknowledgeBelowFloor = false,
  ) {
    setBusyApprovalId(id);
    setApprovalActionError(null);
    try {
      await decideApproval(
        id,
        action,
        acknowledgeBelowFloor ? { acknowledgeBelowFloor: true } : {},
      );
      approvals.setData(pending.filter((a) => a.id !== id));
      showToast(
        action === "approve" ? "Approved ✓" : "Rejected",
        "success",
      );
    } catch (e: unknown) {
      // U2c: a 409 on APPROVE whose detail asks for acknowledge_below_floor is
      // NOT a stale request — it is the quality-floor gate. The artifact is
      // readable and approvable; the human just has to say "yes, below floor"
      // once. Offer that here instead of leaking the raw 409 and dropping the
      // card. (The Approvals modal has always handled this; the dashboard
      // cards did not — this closes that gap so no approve surface forks.)
      if (
        action === "approve" &&
        !acknowledgeBelowFloor &&
        e instanceof ApiError &&
        e.status === 409 &&
        /acknowledge_below_floor/.test(e.message)
      ) {
        const reason =
          /Below quality floor:[^"]*?floor\.?/i.exec(e.message)?.[0] ??
          "This artifact is below the quality floor.";
        if (
          typeof window !== "undefined" &&
          window.confirm(`${reason}\n\nApprove it anyway?`)
        ) {
          await resolveApproval(id, "approve", true);
        }
        return;
      }
      const msg = describeApprovalError(e, action);
      setApprovalActionError(msg);
      showToast(msg, "error");
      // A 409/404 means this request was already resolved elsewhere (stale
      // client state) — drop it from the pending set so no surface keeps
      // offering a dead action for it.
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) {
        approvals.setData(pending.filter((a) => a.id !== id));
      }
    } finally {
      setBusyApprovalId(null);
    }
  }

  const visibleRuns = (runs.data ?? [])
    .filter((r) => feedFilter === "All" || runBadge(r).label === feedFilter)
    .slice(0, 8);

  return (
    <div className="flex flex-col gap-7">
      {/* Toast notification for approval actions */}
      {toast ? (
        <div
          role="status"
          aria-live="polite"
          className={`fixed right-6 top-20 z-50 animate-fade-in rounded-[10px] border bg-surface-2 px-5 py-3 text-sm font-medium shadow-lg transition-all ${
            toast.kind === "success"
              ? "border-aether-green/40 text-aether-green"
              : "border-red-500/40 text-red-300"
          }`}
        >
          {toast.message}
        </div>
      ) : null}
      {/*
        BAND 1 · PULSE (§5.1). The hero moment: the page title carries the
        screen's ONE saturated brand gesture (reference rule 3) and the KPI
        strip sits inside the atmospheric glow, so the top of the page has
        depth instead of being a flat expanse.
      */}
      <section className="atmos-hero">
        <div className="mb-4">
          <h1 className="type-page">
            <span className="text-gradient-brand">Your search</span>, right now
          </h1>
          <p className="type-page-sub mt-1">
            Every figure below is fetched live from your workspace.
          </p>
        </div>
        <DashboardStats
          funnel={funnel.data}
          extras={{ weeklyApplied: weekly.data?.applied ?? null, avgFit }}
          error={funnel.error}
        />
      </section>

      {/*
        BAND 2 (§5.1) — J-3 FIX, and the reason it is ONE grid rather than the
        spec's two stacked bands.

        Two stacked grids re-create the very defect J-3 names: each band's row
        height is its tallest column, so a short left column leaves a void
        beside a tall right one. Measured on the first build of this page: the
        left column ran out ~380px above the right, and the gap was plainly
        visible. One continuous 7/5 grid with `items-start` lets each column
        flow independently, and the widgets are distributed so the two columns
        finish near each other (left: activity + opportunities + funnel;
        right: approvals + ticker + story bank + CRM).

        The old layout was `xl:grid-cols-3` with the
        left column stacking two tall widgets against a right column of four
        short ones, which left a ~700px void at the bottom of one side. A 12-col
        grid split 7/5, with `items-start` so neither column stretches to match
        the other, and the four right-hand widgets split across two bands.
      */}
      <div className="grid gap-6 xl:grid-cols-12 xl:items-start">
        <div className="flex min-w-0 flex-col gap-6 xl:col-span-7">
          {/* Agent activity feed (agent-feed-s1t2u3) */}
          <section className="elev-1 rounded-[14px] p-6" data-testid="agent-feed">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                {/* ML-DASH-002: this feed (and every other widget on this
                    page) is fetched exactly once on mount — there is no
                    setInterval/usePolling refresh here. A "live" label +
                    green dot previously rendered unconditionally, claiming a
                    refresh capability that does not exist on this screen
                    (only the sidebar/topbar poll). Removed rather than
                    faked — see the W-I fix report for the honesty-class
                    reasoning (same defect class as the Gmail "Connected"
                    finding). */}
                <h2 className="text-[15px] font-semibold">Agent Activity</h2>
              </div>
              <Link
                href="/dashboard/agents"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center text-xs text-aether-coral transition hover:text-white"
              >
                View all
              </Link>
            </div>
            <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter agent activity">
              {FEED_FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={feedFilter === f}
                  onClick={() => setFeedFilter(f)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition max-sm:min-h-11 max-sm:px-4 ${
                    feedFilter === f
                      ? "border-aether-coral/50 bg-aether-coral/15 font-semibold text-aether-coral"
                      : "border-white/10 text-aether-muted hover:text-white"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            {runs.error ? (
              <WidgetError>Couldn&apos;t load agent activity — {runs.error}</WidgetError>
            ) : runs.data === null ? (
              <div className="space-y-2.5" aria-busy="true" aria-label="Loading agent activity">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-14 animate-pulse rounded-xl border border-white/10 bg-white/5" />
                ))}
              </div>
            ) : runs.data.length === 0 ? (
              <p className="text-sm text-aether-muted">
                No agent activity yet — head to the{" "}
                <Link href="/dashboard/agents" className="text-aether-coral underline underline-offset-2">
                  Agents workspace
                </Link>{" "}
                to launch the discovery → tailoring pipeline. Anything that leaves the system
                waits for your approval first.
              </p>
            ) : visibleRuns.length === 0 ? (
              <p className="py-2 text-sm text-aether-muted-dim">
                No “{feedFilter}” activity in the latest runs.
              </p>
            ) : (
              <ul className="space-y-3">
                {visibleRuns.map((r) => {
                  const badge = runBadge(r);
                  const tile = agentTile(r.agentName);
                  const desc = describeRun(r);
                  const out = (r.output ?? {}) as Record<string, unknown>;
                  // MV-dashboard-009: out.approval_status is a snapshot
                  // cached at generation time and is never updated once the
                  // linked ApprovalRequest is resolved elsewhere (the
                  // /dashboard/approvals page, another session, the Needs
                  // Approval widget). Cross-check against the live,
                  // independently-fetched pending-approvals set so a
                  // resolved approval's inline control disappears instead of
                  // staying live indefinitely and 409ing on click.
                  const isCoverLetterPending =
                    r.agentName === "coverLetter" &&
                    out.approval_status === "pending" &&
                    typeof out.approval_id === "string" &&
                    pendingApprovalIds.has(out.approval_id as string);
                  const feedApproveBusy = busyApprovalId === (out.approval_id as string);
                  return (
                    <li key={r.id} className="flex items-start gap-3.5">
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${tile.cls}`}
                      >
                        <i className={`fa-solid ${tile.icon} text-xs`} aria-hidden="true" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">
                          <span className="font-medium">{agentDisplayName(r.agentName)}</span>{" "}
                          {activityMessageAfterAgentName(
                            agentDisplayName(r.agentName),
                            humanizeActivityMessage(desc.text),
                          )}
                          {desc.highlight ? <span className="text-white">{desc.highlight}</span> : null}
                        </p>
                        <p className="mono mt-1 text-[11px] text-aether-muted-dim">
                          {relTime(r.startedAt ?? r.createdAt)}
                          {(() => {
                            const m = humanizeActivityMessage(desc.metric);
                            return m ? ` · ${m}` : "";
                          })()}
                        </p>
                        {isCoverLetterPending ? (
                          <button
                            type="button"
                            disabled={feedApproveBusy}
                            onClick={() => void resolveApproval(out.approval_id as string, "approve")}
                            className="mt-2 rounded-lg border border-aether-green/25 bg-aether-green/15 px-3 py-1 text-[11px] font-medium text-aether-green transition hover:bg-aether-green/25 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {feedApproveBusy ? "Approving…" : "Approve"}
                          </button>
                        ) : null}
                      </div>
                      <span
                        className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-medium ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Today's opportunities (opportunities-v4w5x6) */}
          <section className="elev-1 rounded-[14px] p-6" data-testid="todays-opportunities">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Today&apos;s Opportunities</h2>
              <Link href="/dashboard/jobs" className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center text-xs text-aether-muted transition hover:text-white">
                Browse all jobs
              </Link>
            </div>
            {jobs.error ? (
              <WidgetError>Couldn&apos;t load opportunities — {jobs.error}</WidgetError>
            ) : jobs.data === null ? (
              <div className="grid gap-4 md:grid-cols-3" aria-busy="true" aria-label="Loading opportunities">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="elev-1 h-40 animate-pulse rounded-xl" />
                ))}
              </div>
            ) : topJobs.length === 0 ? (
              <p className="py-4 text-center text-sm text-aether-muted-dim">
                No opportunities yet — run the Scout agent to discover jobs.
              </p>
            ) : (
              <div className="grid gap-4 md:grid-cols-3">
                {topJobs.map((job, idx) => (
                  <article
                    key={job.id}
                    data-testid="opportunity-card"
                    className="elev-2 group flex flex-col rounded-xl p-4 transition-colors duration-[--dur] hover:border-aether-coral/40"
                  >
                    <div className="mb-3 flex items-center justify-between">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-xs font-bold">
                        {initials(job.company)}
                      </span>
                      {job.fitScore != null ? (
                        <span
                          className={`mono text-xs font-semibold ${
                            Number(job.fitScore) >= 85 ? "text-aether-green" : "text-aether-yellow"
                          }`}
                        >
                          {Math.round(Number(job.fitScore))}%
                        </span>
                      ) : null}
                    </div>
                    <h3 className="text-sm font-semibold leading-snug">{job.title}</h3>
                    <p className="mt-0.5 text-xs text-aether-muted">
                      {job.company}
                      {job.location ? ` · ${job.location}` : ""}
                    </p>
                    <p className="mono mt-2 text-xs text-aether-muted-dim">
                      {salaryLabel(job)}
                      {job.sourceUrl ? (
                        <>
                          {" · "}
                          <a
                            href={job.sourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid="opportunity-posting-link"
                            className="underline underline-offset-2 transition hover:text-white"
                          >
                            posting ↗
                          </a>
                        </>
                      ) : null}
                    </p>
                    {idx === 0 ? (
                      <Link
                        href={`/dashboard/resume?job=${job.id}`}
                        data-testid="tailor-apply-link"
                        className="mt-3 block w-full rounded-lg bg-aether-coral py-2 text-center text-xs font-medium text-white transition hover:opacity-90 max-sm:min-h-11 max-sm:content-center"
                      >
                        Tailor & Apply
                      </Link>
                    ) : (
                      <Link
                        href="/dashboard/jobs"
                        className="mt-3 block w-full rounded-lg border border-white/10 bg-white/5 py-2 text-center text-xs font-medium transition hover:bg-white/10 max-sm:min-h-11 max-sm:content-center"
                      >
                        Review Match
                      </Link>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
          {/*
            Application funnel (funnel-q7r8s9 — data-driven per audit D11), now
            on the chart kit. The kit is what makes the zero stages honest: the
            hand-rolled bars above rendered `width: 0` for a zero, i.e. NOTHING,
            so "0 screened" and "never measured" looked identical. `<Funnel>`
            draws a zero as a C-1 hairline tick at the origin with the numeral
            in `state-neutral`, and states its own sample window (C-3).
          */}
          <section className="elev-1 rounded-[14px] p-6" data-testid="funnel-widget">
            {funnel.error ? (
              <WidgetError>Couldn&apos;t load the funnel — {funnel.error}</WidgetError>
            ) : funnel.data === null ? (
              <div className="h-40 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading funnel" />
            ) : (
              <FunnelChart
                title="Application funnel"
                windowLabel="all time — every stage counted since your first discovery run"
                steps={funnelSteps(funnel.data)}
                mode="share-of-previous"
              />
            )}
          </section>

        </div>

        {/*
          BAND 2, right — the two surfaces that are about RIGHT NOW. Needs
          Approval moves UP out of the old fourth-from-top slot (§5.1: it is
          the only widget on the page carrying a blocking user action), and the
          live ticker sits beside it so the pair reads as one live organism.
        */}
        <div className="flex min-w-0 flex-col gap-6 xl:col-span-5">
          <NeedsApprovalPanel
            approvals={approvals}
            pending={pending}
            busyApprovalId={busyApprovalId}
            approvalActionError={approvalActionError}
            resolveApproval={(id, action) => void resolveApproval(id, action)}
          />

          <Section
            testId="live-activity"
            className="band-recessed"
            bodyClassName="min-h-0"
          >
            <ActivityTicker maxRows={8} />
          </Section>
          <div className="grid min-w-0 gap-6 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          {/* Story Bank quick access (story-bank-quick-db10) */}
          <section
            className="elev-1 min-w-0 rounded-[14px] p-6 transition hover:border-aether-indigo/30"
            data-testid="story-bank-widget"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-aether-indigo/25 bg-aether-indigo/15">
                  <i className="fa-solid fa-book-bookmark text-xs text-aether-violet" aria-hidden="true" />
                </span>
                <h2 className="text-[15px] font-semibold">Story Bank</h2>
              </div>
              <Link
                href="/dashboard/stories"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center flex items-center gap-1 text-xs text-aether-violet transition hover:text-white"
              >
                Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
              </Link>
            </div>
            {stories.error ? (
              <WidgetError>Couldn&apos;t load stories — {stories.error}</WidgetError>
            ) : stories.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading stories" />
            ) : stories.data.length === 0 ? (
              <p className="text-sm text-aether-muted-dim">
                No STAR stories yet —{" "}
                <Link href="/dashboard/stories" className="text-aether-coral underline underline-offset-2">
                  capture your first achievement
                </Link>
                .
              </p>
            ) : (
              <>
                <p className="mb-4 text-sm text-aether-muted">
                  <span className="mono font-bold text-white">{stories.data.length}</span> STAR
                  achievement{stories.data.length === 1 ? "" : "s"} ready to deploy
                </p>
                <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-aether-muted-dim">
                  Latest stories
                </p>
                <ul className="flex flex-col gap-2">
                  {stories.data.slice(0, 3).map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2"
                    >
                      <span className="truncate text-xs text-aether-muted">{s.title}</span>
                      <span className="mono ml-2 shrink-0 rounded bg-aether-coral/15 px-1.5 py-0.5 text-[10px] text-aether-coral">
                        {Object.keys(s.metrics ?? {}).length} metrics
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {/* Recruiter CRM summary (crm-summary-db11) */}
          <section
            className="elev-1 min-w-0 rounded-[14px] p-6 transition hover:border-aether-coral/30"
            data-testid="crm-summary"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-aether-coral/25 bg-aether-coral/15">
                  <i className="fa-solid fa-handshake text-xs text-aether-coral" aria-hidden="true" />
                </span>
                <h2 className="text-[15px] font-semibold">Recruiter CRM</h2>
              </div>
              <Link
                href="/dashboard/networking"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center flex items-center gap-1 text-xs text-aether-coral transition hover:text-white"
              >
                Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
              </Link>
            </div>
            {crm.error ? (
              <WidgetError>Couldn&apos;t load CRM summary — {crm.error}</WidgetError>
            ) : crm.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading CRM summary" />
            ) : (
              <div className="flex flex-col gap-2.5">
                <CrmRow
                  icon="fa-comments"
                  color="text-aether-green bg-aether-green/10"
                  count={crm.data.activeConversations}
                  label="active recruiter conversations"
                />
                <CrmRow
                  icon="fa-clock"
                  color="text-aether-yellow bg-aether-yellow/10"
                  count={crm.data.followUpsDueToday}
                  label="follow-ups due today"
                />
                <CrmRow
                  icon="fa-user-plus"
                  color="text-aether-violet bg-aether-indigo/10"
                  count={crm.data.warmIntrosPending}
                  label="warm intro pending"
                />
              </div>
            )}
          </section>
          </div>
        </div>
      </div>


      {/* Market Intelligence (market-intel-mi01) */}
      <MarketPulse />
    </div>
  );
}

/**
 * The Needs Approval queue, extracted so BAND 2 can render it beside the live
 * ticker (§5.1: it moves UP — it is the only widget on this page carrying a
 * blocking user action, and it used to sit fourth in a right-hand stack).
 * Every prop it takes is state the page already owned; no fetch moved.
 */
function NeedsApprovalPanel({
  approvals,
  pending,
  busyApprovalId,
  approvalActionError,
  resolveApproval,
}: {
  approvals: { data: Approval[] | null; error: string | null };
  pending: Approval[];
  busyApprovalId: string | null;
  approvalActionError: string | null;
  resolveApproval: (id: string, action: "approve" | "reject") => void;
}) {
  return (
          <section
            className="elev-1 rounded-[14px] p-6"
            data-testid="needs-approval-widget"
          >
            <div className="mb-4 flex items-center gap-2">
              <i className="fa-solid fa-shield-halved text-sm text-aether-yellow" aria-hidden="true" />
              <h2 className="text-[15px] font-semibold">Needs Approval</h2>
              <span
                className="ml-auto rounded-full bg-aether-yellow/15 px-2 py-0.5 text-[10px] font-semibold text-aether-yellow"
                data-testid="approval-count"
              >
                {pending.length}
              </span>
            </div>
            {approvalActionError ? (
              <p role="alert" className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
                {approvalActionError}
              </p>
            ) : null}
            {approvals.error ? (
              <WidgetError>Couldn&apos;t load the approval queue — {approvals.error}</WidgetError>
            ) : approvals.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading approvals" />
            ) : pending.length === 0 ? (
              <p className="text-sm text-aether-muted-dim">
                Queue clear — nothing is waiting on you right now.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {pending.slice(0, 3).map((a) => {
                  const payload = a.payload as { job_title?: string; company?: string };
                  const title = approvalTitle(a);
                  const subtitle = [payload.job_title, payload.company].filter(Boolean).join(" · ");
                  const busy = busyApprovalId === a.id;
                  return (
                    <li
                      key={a.id}
                      className="min-w-0 rounded-xl border border-white/10 bg-white/5 p-4"
                    >
                      <p className="text-sm font-medium">{title}</p>
                      {subtitle ? (
                        <p className="mt-0.5 min-w-0 break-words text-xs text-aether-muted">
                          {subtitle}
                        </p>
                      ) : null}
                      <p className="mono mt-2 text-[11px] text-aether-muted-dim">
                        requested {relTime(a.createdAt)} · waiting on you
                      </p>
                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          aria-label={`Approve: ${title}${subtitle ? ` — ${subtitle}` : ""}`}
                          onClick={() => void resolveApproval(a.id, "approve")}
                          className="flex-1 rounded-lg border border-aether-green/25 bg-aether-green/15 py-2 text-xs font-medium text-aether-green transition hover:bg-aether-green/25 disabled:cursor-not-allowed disabled:opacity-50 max-sm:min-h-11"
                        >
                          {busy ? "Working…" : "Approve"}
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          aria-label={`Reject: ${title}${subtitle ? ` — ${subtitle}` : ""}`}
                          onClick={() => void resolveApproval(a.id, "reject")}
                          className="flex-1 rounded-lg border border-white/10 bg-white/5 py-2 text-xs font-medium text-aether-muted transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50 max-sm:min-h-11"
                        >
                          Reject
                        </button>
                      </div>
                    </li>
                  );
                })}
                {pending.length > 3 ? (
                  <li className="text-center text-xs text-aether-muted-dim">
                    <Link
                      href="/dashboard/approvals"
                      className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center hover:text-white"
                    >
                      +{pending.length - 3} more waiting — review all
                    </Link>
                  </li>
                ) : null}
              </ul>
            )}
          </section>
  );
}

function CrmRow({
  icon,
  color,
  count,
  label,
}: {
  icon: string;
  color: string;
  count: number;
  label: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${color}`}>
        <i className={`fa-solid ${icon} text-xs`} aria-hidden="true" />
      </span>
      <p className="text-sm text-aether-muted">
        <span className="mono font-semibold text-white">{count}</span> {label}
      </p>
    </div>
  );
}
