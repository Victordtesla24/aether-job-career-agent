"use client";

/**
 * /admin/users/[id] — user detail: activity, subscription, quota, recent runs,
 * LLM spend (US$) plus admin actions: set spend cap (US$) and suspend/unsuspend.
 */
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../../components/admin/admin-shell";
import {
  fetchAdminUser,
  formatUsd,
  setSpendCap,
  setSuspended,
  type AdminUserDetail,
} from "../../../../lib/api/admin";

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
      <p className="mb-3 text-xs uppercase tracking-wide text-aether-muted-dim">{title}</p>
      {children}
    </div>
  );
}

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params?.id ?? "";
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [capInput, setCapInput] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await fetchAdminUser(userId);
      setDetail(d);
      if (d.quota) setCapInput(String(d.quota.spendCapUsd));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load user");
    }
  }, [userId]);

  useEffect(() => {
    if (userId) void load();
  }, [userId, load]);

  const onSaveCap = async () => {
    if (capInput.trim() === "") {
      setError("Spend cap must be a non-negative number (US$).");
      return;
    }
    const value = Number(capInput);
    if (!Number.isFinite(value) || value < 0) {
      setError("Spend cap must be a non-negative number (US$).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setSpendCap(userId, value);
      setNotice(`Spend cap set to ${formatUsd(value)}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set spend cap");
    } finally {
      setBusy(false);
    }
  };

  const onToggleSuspend = async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await setSuspended(userId, !detail.user.suspended);
      setNotice(detail.user.suspended ? "User unsuspended." : "User suspended.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update suspension");
    } finally {
      setBusy(false);
    }
  };

  if (error && !detail) return <p className="text-sm text-red-300">{error}</p>;
  if (!detail) return <p className="text-sm text-aether-muted">Loading…</p>;

  const u = detail.user;
  return (
    <div>
      <AdminPageHeader title={u.name || u.email} subtitle={u.email} />

      {notice ? <p className="mb-3 text-sm text-aether-green">{notice}</p> : null}
      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Account">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-aether-muted">Plan</dt>
            <dd className="text-aether-text">{u.plan ?? "—"}</dd>
            <dt className="text-aether-muted">Status</dt>
            <dd className="text-aether-text">{u.suspended ? "suspended" : "active"}</dd>
            <dt className="text-aether-muted">Admin</dt>
            <dd className="text-aether-text">{u.isAdmin ? "yes" : "no"}</dd>
            <dt className="text-aether-muted">Signed up</dt>
            <dd className="text-aether-text">{fmtDate(u.signupAt)}</dd>
            <dt className="text-aether-muted">Last login</dt>
            <dd className="text-aether-text">{fmtDate(u.lastLoginAt)}</dd>
            <dt className="text-aether-muted">Total LLM spend</dt>
            <dd className="font-mono text-aether-text">{formatUsd(detail.spendUsd)} US$</dd>
            <dt className="text-aether-muted">Runs</dt>
            <dd className="text-aether-text">{detail.runCount}</dd>
          </dl>
        </Panel>

        <Panel title="Subscription & quota">
          {detail.quota ? (
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-aether-muted">Runs used</dt>
              <dd className="text-aether-text">
                {detail.quota.runsUsed} / {detail.quota.runsAllowed}
              </dd>
              <dt className="text-aether-muted">Spend used</dt>
              <dd className="font-mono text-aether-text">{formatUsd(detail.quota.spendUsedUsd)}</dd>
              <dt className="text-aether-muted">Spend cap</dt>
              <dd className="font-mono text-aether-text">{formatUsd(detail.quota.spendCapUsd)}</dd>
              <dt className="text-aether-muted">Period ends</dt>
              <dd className="text-aether-text">{fmtDate(detail.quota.periodEnd)}</dd>
            </dl>
          ) : (
            <p className="text-sm text-aether-muted">No quota row.</p>
          )}
        </Panel>

        <Panel title="Spend cap (US$)">
          <p className="mb-2 text-xs text-aether-muted">
            Enforced before every metered agent run — a run is blocked with 429 once
            accumulated spend reaches the cap.
          </p>
          <div className="flex items-center gap-2">
            <span className="text-aether-muted">US$</span>
            <input
              value={capInput}
              onChange={(e) => setCapInput(e.target.value)}
              inputMode="decimal"
              className="w-32 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
            />
            <button
              onClick={() => void onSaveCap()}
              disabled={busy}
              className="rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90 disabled:opacity-50"
            >
              Save cap
            </button>
          </div>
        </Panel>

        <Panel title="Suspension">
          <p className="mb-2 text-xs text-aether-muted">
            A suspended user is refused (403) on every authenticated route until reinstated.
          </p>
          <button
            onClick={() => void onToggleSuspend()}
            disabled={busy}
            className={`rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 ${
              u.suspended
                ? "bg-aether-green/20 text-aether-green hover:bg-aether-green/30"
                : "bg-red-500/20 text-red-300 hover:bg-red-500/30"
            }`}
          >
            {u.suspended ? "Unsuspend user" : "Suspend user"}
          </button>
        </Panel>
      </div>

      <div className="mt-4">
        <Panel title="Recent runs">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
              <tr>
                <th className="py-2 pr-4">Agent</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4 text-right">Cost (US$)</th>
                <th className="py-2 pr-4">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {detail.recentRuns.map((r) => (
                <tr key={r.id}>
                  <td className="py-2 pr-4 text-aether-text">{r.agentName}</td>
                  <td className="py-2 pr-4 text-aether-muted">{r.status}</td>
                  <td className="py-2 pr-4 text-right font-mono text-aether-text">
                    {formatUsd(r.costUsd)}
                  </td>
                  <td className="py-2 pr-4 text-aether-muted">{fmtDate(r.createdAt)}</td>
                </tr>
              ))}
              {detail.recentRuns.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 text-center text-aether-muted">
                    No runs yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        </Panel>
      </div>
    </div>
  );
}
