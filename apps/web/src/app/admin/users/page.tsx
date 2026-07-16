"use client";

/**
 * /admin/users — user list with filters + LLM spend in US$ (§15 Tier 1).
 * Columns: name, email, plan, last-login, signup date, LLM spend (USD).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import {
  fetchAdminUsers,
  formatUsd,
  type AdminUser,
  type UserFilters,
} from "../../../lib/api/admin";

const PLANS = ["", "free", "starter", "pro", "power"];

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState("");
  const [suspendedOnly, setSuspendedOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const filters: UserFilters = {};
    if (q.trim()) filters.q = q.trim();
    if (plan) filters.plan = plan;
    if (suspendedOnly) filters.suspended = true;
    try {
      const res = await fetchAdminUsers(filters);
      setRows(res.users);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, [q, plan, suspendedOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <AdminPageHeader
        title="Users"
        subtitle="Accounts with plan, activity and LLM spend (US$ — LLM providers bill USD)."
      />

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="flex flex-col text-xs text-aether-muted">
          Search
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="email or name"
            className="mt-1 w-56 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text placeholder:text-aether-muted-dim"
          />
        </label>
        <label className="flex flex-col text-xs text-aether-muted">
          Plan
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            className="mt-1 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
          >
            {PLANS.map((p) => (
              <option key={p} value={p}>
                {p === "" ? "All plans" : p}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-xs text-aether-muted">
          <input
            type="checkbox"
            checked={suspendedOnly}
            onChange={(e) => setSuspendedOnly(e.target.checked)}
          />
          Suspended only
        </label>
        <button
          type="submit"
          className="rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90"
        >
          Apply
        </button>
      </form>

      {error ? <p className="text-sm text-red-300">{error}</p> : null}

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Last login</th>
              <th className="px-4 py-3">Signed up</th>
              <th className="px-4 py-3 text-right">LLM spend (US$)</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {rows.map((u) => (
              <tr key={u.id} className="hover:bg-white/5">
                <td className="px-4 py-3 text-aether-text">
                  {u.name || "—"}
                  {u.isAdmin ? (
                    <span className="ml-2 rounded bg-aether-violet/20 px-1.5 py-0.5 text-[10px] text-aether-violet">
                      admin
                    </span>
                  ) : null}
                  {u.suspended ? (
                    <span className="ml-2 rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] text-red-300">
                      suspended
                    </span>
                  ) : null}
                </td>
                <td className="px-4 py-3 text-aether-muted">{u.email}</td>
                <td className="px-4 py-3 text-aether-muted">{u.plan ?? "—"}</td>
                <td className="px-4 py-3 text-aether-muted">{fmtDate(u.lastLoginAt)}</td>
                <td className="px-4 py-3 text-aether-muted">{fmtDate(u.signupAt)}</td>
                <td className="px-4 py-3 text-right font-mono text-aether-text">
                  {formatUsd(u.spendUsd)}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`/admin/users/${u.id}`}
                    className="text-xs text-aether-indigo hover:underline"
                  >
                    View
                  </Link>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-aether-muted">
                  No users match these filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-aether-muted-dim">
        {loading ? "Loading…" : `${rows.length} of ${total} users`}
      </p>
    </div>
  );
}
