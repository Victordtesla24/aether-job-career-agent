"use client";

/**
 * Dashboard home — live stat cards (GET /analytics/funnel), today's top
 * opportunities (GET /jobs), the Application Funnel widget (DEF-014) and the
 * Recruiter CRM summary widget (DEF-015, GET /networking/summary).
 * Funnel numbers are data-driven per REQ-TM-09 — never hardcoded.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import DashboardStats from "../../components/dashboard/DashboardStats";
import { fetchFunnel, type Funnel } from "../../lib/api/analytics";
import { apiRequest } from "../../lib/api/client";
import type { Job } from "../../lib/api/jobs";
import { fetchNetworkingSummary, type NetworkingSummary } from "../../lib/api/workspaces";

const FUNNEL_STAGES: Array<{ key: keyof Funnel & string; label: string; color: string }> = [
  { key: "jobs_found", label: "Jobs Found", color: "bg-aether-violet" },
  { key: "applied", label: "Applied", color: "bg-aether-violet/80" },
  { key: "screened", label: "Screened", color: "bg-aether-coral" },
  { key: "interviewed", label: "Interviewed", color: "bg-aether-amber" },
  { key: "offers", label: "Offers", color: "bg-aether-green" },
];

function initials(company: string) {
  return company
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function DashboardPage() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [crm, setCrm] = useState<NetworkingSummary["crmSummary"] | null>(null);

  useEffect(() => {
    fetchFunnel("all").then(setFunnel).catch(() => setFunnel(null));
    apiRequest<Job[]>("/jobs?sort=fitScore")
      .then((list) => setJobs(list.slice(0, 3)))
      .catch(() => setJobs([]));
    fetchNetworkingSummary()
      .then((n) => setCrm(n.crmSummary))
      .catch(() => setCrm(null));
  }, []);

  const maxStage = funnel ? Math.max(funnel.jobs_found, 1) : 1;

  return (
    <div className="grid gap-7 xl:grid-cols-3">
      {/* Left 2/3 */}
      <div className="flex flex-col gap-7 xl:col-span-2">
        <DashboardStats />

        <section className="glass rounded-2xl border border-white/10 p-6">
          <div className="flex items-center gap-2.5 mb-2">
            <span className="w-2 h-2 rounded-full bg-aether-green live-dot" />
            <h2 className="text-[15px] font-semibold">Agent Activity</h2>
            <span className="text-[11px] text-aether-muted-dim mono">live</span>
          </div>
          <p className="text-sm text-aether-muted">
            Head to the{" "}
            <Link href="/dashboard/agents" className="text-aether-coral underline underline-offset-2">
              Agents workspace
            </Link>{" "}
            to trigger runs, review recent activity, and launch the full discovery → tailoring
            pipeline. Anything that leaves the system waits for your approval first.
          </p>
        </section>

        {/* Today's opportunities */}
        <section className="glass rounded-2xl border border-white/10 p-6" data-testid="todays-opportunities">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">Today&apos;s Opportunities</h2>
            <Link href="/dashboard/jobs" className="text-xs text-aether-muted transition hover:text-white">
              Browse all jobs
            </Link>
          </div>
          {jobs === null ? (
            <div className="grid gap-4 md:grid-cols-3" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="glass h-36 animate-pulse rounded-xl border border-white/10" />
              ))}
            </div>
          ) : jobs.length === 0 ? (
            <p className="py-4 text-center text-sm text-aether-muted-dim">
              No opportunities yet — run the Scout agent to discover jobs.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {jobs.map((job) => (
                <article
                  key={job.id}
                  data-testid="opportunity-card"
                  className="glass group rounded-xl border border-white/10 p-4 transition hover:border-aether-coral/30"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-xs font-bold">
                      {initials(job.company)}
                    </span>
                    {job.fitScore != null ? (
                      <span className="mono text-xs font-semibold text-aether-green">
                        {Math.round(Number(job.fitScore))}%
                      </span>
                    ) : null}
                  </div>
                  <h3 className="text-sm font-semibold leading-snug">{job.title}</h3>
                  <p className="mt-0.5 text-xs text-aether-muted">
                    {job.company}
                    {job.location ? ` · ${job.location}` : ""}
                  </p>
                  <Link
                    href="/dashboard/jobs"
                    className="mt-3 block w-full rounded-lg bg-aether-coral py-2 text-center text-xs font-medium text-white transition hover:opacity-90"
                  >
                    Tailor &amp; Apply
                  </Link>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Right 1/3 */}
      <div className="flex flex-col gap-7 xl:col-span-1">
        {/* Application funnel (DEF-014) */}
        <section className="glass rounded-2xl border border-white/10 p-6" data-testid="funnel-widget">
          <h2 className="mb-5 text-[15px] font-semibold">Application Funnel</h2>
          {funnel === null ? (
            <div className="h-40 animate-pulse rounded-xl border border-white/10" aria-busy="true" />
          ) : (
            <div className="flex flex-col gap-3">
              {FUNNEL_STAGES.map((stage) => {
                const value = Number(funnel[stage.key] ?? 0);
                const width = Math.max((value / maxStage) * 100, value > 0 ? 6 : 2);
                return (
                  <div key={stage.key}>
                    <div className="mb-1.5 flex justify-between text-xs">
                      <span className="text-aether-muted">{stage.label}</span>
                      <span className="mono font-medium">{value}</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5">
                      <div className={`h-2 rounded-full ${stage.color}`} style={{ width: `${width}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Recruiter CRM summary (DEF-015) */}
        <section
          className="glass rounded-2xl border border-white/10 p-6 transition hover:border-aether-coral/30"
          data-testid="crm-summary"
        >
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-aether-coral/25 bg-aether-coral/15">
                <i className="fa-solid fa-handshake text-xs text-aether-coral" aria-hidden="true" />
              </span>
              <h2 className="text-[15px] font-semibold">Recruiter CRM</h2>
            </div>
            <Link href="/dashboard/networking" className="flex items-center gap-1 text-xs text-aether-coral transition hover:text-white">
              Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
            </Link>
          </div>
          {crm === null ? (
            <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" />
          ) : (
            <div className="flex flex-col gap-2.5">
              <CrmRow icon="fa-comments" color="text-aether-green bg-aether-green/10" count={crm.activeConversations} label="active recruiter conversations" />
              <CrmRow icon="fa-clock" color="text-aether-amber bg-aether-amber/10" count={crm.followUpsDueToday} label="follow-ups due today" />
              <CrmRow icon="fa-user-plus" color="text-aether-violet bg-aether-violet/10" count={crm.warmIntrosPending} label="warm intro pending" />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function CrmRow({ icon, color, count, label }: { icon: string; color: string; count: number; label: string }) {
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
