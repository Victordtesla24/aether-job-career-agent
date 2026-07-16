"use client";

/**
 * /admin/spend — total + per-user LLM spend in US$ (§15 Tier 1, §14.8).
 * Spend is SUM("AgentRun"."costUsd"); LLM providers bill USD, so this page is
 * labelled US$ throughout (never AUD).
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { fetchAdminSpend, formatUsd, type AdminSpend } from "../../../lib/api/admin";

export default function AdminSpendPage() {
  const [data, setData] = useState<AdminSpend | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAdminSpend()
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className="text-sm text-red-300">{error}</p>;
  if (!data) return <p className="text-sm text-aether-muted">Loading spend…</p>;

  return (
    <div>
      <AdminPageHeader
        title="LLM spend"
        subtitle="Platform-wide and per-user LLM spend in US$ (providers bill USD)."
      />

      <div className="mb-6 rounded-xl border border-white/10 bg-aether-bg-elevated p-5">
        <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Total LLM spend (US$)</p>
        <p className="mt-2 text-3xl font-semibold text-aether-text">{formatUsd(data.totalUsd)}</p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3 text-right">Runs</th>
              <th className="px-4 py-3 text-right">Spend (US$)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.perUser.map((p) => (
              <tr key={p.userId} className="hover:bg-white/5">
                <td className="px-4 py-3 text-aether-text">
                  <Link href={`/admin/users/${p.userId}`} className="hover:underline">
                    {p.name || "—"}
                  </Link>
                </td>
                <td className="px-4 py-3 text-aether-muted">{p.email ?? "—"}</td>
                <td className="px-4 py-3 text-right text-aether-muted">{p.runCount}</td>
                <td className="px-4 py-3 text-right font-mono text-aether-text">
                  {formatUsd(p.spendUsd)}
                </td>
              </tr>
            ))}
            {data.perUser.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-aether-muted">
                  No LLM spend recorded yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
