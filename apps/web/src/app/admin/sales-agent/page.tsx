"use client";

/**
 * /admin/sales-agent — visibility into the autonomous growth/marketing
 * engine that drives Aether subscriptions.
 *
 * IMPORTANT — architecture honesty: the growth engine itself does NOT run
 * inside this app. It runs as an external scheduled process (6x/day) that
 * reads/writes a Google Sheet (CRM + activity log) and two Google Docs
 * (LinkedIn content calendar, messaging playbook), and sends email through
 * a separate Gmail account. There is no backend job, queue, or table for it
 * in this codebase, so this page cannot show "live" engine internals from
 * Aether's own API — it does two honest things instead:
 *   1. Re-projects REAL Aether subscription data this app already has
 *      (GET /api/admin/users, the same admin-gated endpoint /admin/users
 *      and /admin/subscriptions use) into growth-relevant numbers: total
 *      signups, paid conversions by plan, and an estimated MRR.
 *   2. Links out to the actual system of record (the Sheet + Docs) for
 *      real campaign/lead detail, rather than faking an embedded view of
 *      data this backend cannot see.
 * No new backend endpoint was added for this page — it reuses the existing
 * AdminUser-gated /api/admin/users route, same pattern as /admin/subscriptions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { fetchAdminUsers, type AdminUser } from "../../../lib/api/admin";

// Monthly AUD list price per plan (docs/subscription/billing-architecture.md,
// ADR-P6-PRICING). Used only to ESTIMATE MRR from plan mix — an annual
// subscriber is counted at this same monthly-equivalent rate since the
// admin/users API does not expose billingInterval, so this is a floor
// estimate, not a Stripe-verified figure. Labelled as such below.
const MONTHLY_AUD_BY_PLAN: Record<string, number> = {
  starter: 19,
  pro: 39,
  power: 69,
};

const GROWTH_ENGINE_LINKS = [
  {
    label: "CRM & Learning Log (Google Sheet)",
    href: "https://docs.google.com/spreadsheets/d/1hiaoc7lDKW09IKbHwL9FlJAYU37k290ZjQUvB2v_52M/edit",
    detail: "Prospects, Email_Log, LinkedIn_Content_Queue, Learnings, Metrics, Suppression_List",
  },
  {
    label: "LinkedIn Content Calendar (Google Doc)",
    href: "https://docs.google.com/document/d/1FgpWoxG_AAUodf8Nz21QsTiApj0eSz5jeSDXvCiyFSM/edit",
    detail: "Draft-only queue — a human posts these manually (LinkedIn's Terms prohibit automated posting)",
  },
  {
    label: "Messaging Playbook & Email Templates (Google Doc)",
    href: "https://docs.google.com/document/d/1mc5tPZRN3kKGKTO2-S1W6CDYPoiDECH0yKapoW9j760/edit",
    detail: "ICP, positioning, pricing, compliance footer, and the 4 approved outreach templates",
  },
];

function planLabel(plan: string | null): string {
  if (!plan) return "Free";
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

export default function AdminSalesAgentPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminUsers({});
      setRows(res.users);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load subscriber data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Entitled-paid definition mirrors SubscriptionRepository.has_active_paid_subscription:
  // status in (active, trialing, past_due) AND plan != free.
  const entitled = useMemo(
    () =>
      rows.filter((u) => {
        const status = (u.subStatus ?? "").toLowerCase();
        const plan = (u.plan ?? "free").toLowerCase();
        return plan !== "free" && ["active", "trialing", "past_due"].includes(status);
      }),
    [rows],
  );

  const planCounts = useMemo(() => {
    const counts: Record<string, number> = { free: 0, starter: 0, pro: 0, power: 0 };
    for (const u of rows) {
      const key = (u.plan ?? "free").toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [rows]);

  const estimatedMrrAud = useMemo(
    () =>
      entitled.reduce((sum, u) => {
        const plan = (u.plan ?? "free").toLowerCase();
        return sum + (MONTHLY_AUD_BY_PLAN[plan] ?? 0);
      }, 0),
    [entitled],
  );

  return (
    <div>
      <AdminPageHeader
        title="Sales Agent"
        subtitle="Real Aether subscriber numbers, plus links to the growth engine's actual system of record."
      />

      {error ? <p className="mb-4 text-sm text-red-300">{error}</p> : null}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Total signups</p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">{loading ? "…" : total}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Paid conversions</p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">
            {loading ? "…" : entitled.length}
          </p>
        </div>
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">
            Estimated MRR (AUD)
          </p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">
            {loading ? "…" : `$${estimatedMrrAud}`}
          </p>
          <p className="mt-1 text-[10px] text-aether-muted-dim">
            Monthly list price × plan mix — a floor estimate, not Stripe-verified (annual billing
            intervals aren&apos;t distinguished by this API).
          </p>
        </div>
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Conversion rate</p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">
            {loading || total === 0 ? "—" : `${((entitled.length / total) * 100).toFixed(1)}%`}
          </p>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(["free", "starter", "pro", "power"] as const).map((p) => (
          <div key={p} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
            <p className="text-xs uppercase tracking-wide text-aether-muted-dim">{planLabel(p)}</p>
            <p className="mt-1 text-xl font-semibold text-aether-text">
              {loading ? "…" : (planCounts[p] ?? 0)}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-5">
        <h2 className="text-sm font-semibold text-aether-text">Growth engine (external)</h2>
        <p className="mt-1 text-xs text-aether-muted">
          The autonomous outreach/marketing engine runs outside this app on a 6x/day schedule: it
          scans a connected Gmail inbox for real inbound signals, replies with an approved
          template, drafts LinkedIn content for manual posting, and emails a daily summary. Its
          live activity log, lead list, and content queue live here, not in this backend:
        </p>
        <ul className="mt-3 space-y-2">
          {GROWTH_ENGINE_LINKS.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-aether-indigo hover:underline"
              >
                {link.label}
              </a>
              <p className="text-xs text-aether-muted-dim">{link.detail}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
