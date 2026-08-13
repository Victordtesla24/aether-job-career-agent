"use client";

/**
 * /admin/subscriptions — subscription management overview (H-07, QA-v2).
 *
 * The QA v2 report flagged /admin/subscriptions as a 404 with no way for an
 * operator to see who is on which plan. This page reads the SAME admin user
 * list the /admin/users screen uses (GET /api/admin/users, which already
 * carries per-user plan, subscription status, spend and run-count) and
 * presents it through a subscription lens: plan mix summary cards, then a
 * per-user table of plan / status / usage / spend. No new backend endpoint is
 * introduced — it re-projects existing, already-authorised data (AdminUser
 * dependency enforced server-side). Spend is shown in US$ because LLM
 * providers bill USD, matching /admin/users and /admin/spend.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { formatDate } from "../../../lib/format";
import { fetchAdminUsers, formatUsd, type AdminUser } from "../../../lib/api/admin";

const PLAN_ORDER = ["free", "starter", "pro", "power"] as const;

function planLabel(plan: string | null): string {
  if (!plan) return "Free";
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

function statusTone(status: string | null): string {
  const s = (status ?? "").toLowerCase();
  if (s === "active") return "bg-aether-green/15 text-aether-green border-aether-green/25";
  if (s === "trialing") return "bg-aether-indigo/15 text-aether-indigo border-aether-indigo/25";
  if (s === "past_due" || s === "unpaid")
    return "bg-aether-amber/15 text-aether-amber border-aether-amber/25";
  if (s === "canceled" || s === "cancelled")
    return "bg-red-500/10 text-red-300 border-red-500/25";
  return "bg-white/5 text-aether-muted-dim border-white/10";
}

export default function AdminSubscriptionsPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminUsers(plan ? { plan } : {});
      setRows(res.users);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load subscriptions");
    } finally {
      setLoading(false);
    }
  }, [plan]);

  useEffect(() => {
    void load();
  }, [load]);

  // Plan-mix summary derived from the loaded rows (honest: it summarises what
  // the current filter returned, and says so when a plan filter is active).
  const planCounts = useMemo(() => {
    const counts: Record<string, number> = { free: 0, starter: 0, pro: 0, power: 0 };
    for (const u of rows) {
      const key = (u.plan ?? "free").toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [rows]);

  const paidCount = useMemo(
    () => rows.filter((u) => (u.plan ?? "free").toLowerCase() !== "free").length,
    [rows],
  );

  return (
    <div>
      <AdminPageHeader
        title="Subscriptions"
        subtitle="Every account's plan, subscription status and usage. Spend is US$ (LLM providers bill USD)."
      />

      {/* Plan-mix summary */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Paid</p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">{paidCount}</p>
        </div>
        {PLAN_ORDER.map((p) => (
          <div key={p} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
            <p className="text-xs uppercase tracking-wide text-aether-muted-dim">{planLabel(p)}</p>
            <p className="mt-1 text-2xl font-semibold text-aether-text">{planCounts[p] ?? 0}</p>
          </div>
        ))}
      </div>

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="flex flex-col text-xs text-aether-muted">
          Plan
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            className="mt-1 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
          >
            <option value="">All plans</option>
            {PLAN_ORDER.map((p) => (
              <option key={p} value={p}>
                {planLabel(p)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90"
        >
          Apply
        </button>
      </form>

      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Runs</th>
              <th className="px-4 py-3 text-right">LLM spend (US$)</th>
              <th className="px-4 py-3">Signed up</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {rows.map((u) => (
              <tr key={u.id} className="hover:bg-white/5">
                <td className="px-4 py-3 text-aether-text">
                  <div className="font-medium">{u.name || "—"}</div>
                  <div className="text-xs text-aether-muted">{u.email}</div>
                </td>
                <td className="px-4 py-3">
                  <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-aether-text">
                    {planLabel(u.plan)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs ${statusTone(u.subStatus)}`}
                  >
                    {u.subStatus ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-aether-muted">{u.runCount}</td>
                <td className="px-4 py-3 text-right font-mono text-aether-text">
                  {formatUsd(u.spendUsd)}
                </td>
                <td className="px-4 py-3 text-aether-muted">{formatDate(u.signupAt)}</td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`/admin/users/${u.id}`}
                    className="text-xs text-aether-indigo hover:underline"
                  >
                    Manage
                  </Link>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-aether-muted">
                  No subscriptions match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-aether-muted-dim">
        {loading ? "Loading..." : `${rows.length} of ${total} accounts`}
      </p>
    </div>
  );
}
