"use client";

/**
 * /admin/audit-log — paginated, append-only admin audit trail (ADMIN-003).
 * Every admin mutation writes one immutable row (actor, action, target, detail,
 * ip). The UI is read-only — the log is never edited or deleted.
 */
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { fetchAuditLog, type AuditEntry } from "../../../lib/api/admin";

const PAGE = 50;

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function detailText(detail: unknown): string {
  if (detail === null || detail === undefined) return "—";
  try {
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    return "—";
  }
}

export default function AdminAuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextOffset: number) => {
    setError(null);
    try {
      const res = await fetchAuditLog(PAGE, nextOffset);
      setEntries(res.entries);
      setTotal(res.total);
      setOffset(res.offset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    }
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  return (
    <div>
      <AdminPageHeader
        title="Audit log"
        subtitle="Append-only record of every admin action (read-only)."
      />

      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">When</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Target</th>
              <th className="px-4 py-3">Detail</th>
              <th className="px-4 py-3">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {entries.map((e) => (
              <tr key={e.id} className="hover:bg-white/5 align-top">
                <td className="px-4 py-3 text-aether-muted whitespace-nowrap">{fmtDate(e.createdAt)}</td>
                <td className="px-4 py-3 font-mono text-xs text-aether-muted">{e.actorUserId}</td>
                <td className="px-4 py-3 text-aether-text">{e.action}</td>
                <td className="px-4 py-3 text-aether-muted">
                  {e.targetType ? `${e.targetType}:${e.targetId ?? ""}` : "—"}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-aether-muted">{detailText(e.detail)}</td>
                <td className="px-4 py-3 text-aether-muted">{e.ip ?? "—"}</td>
              </tr>
            ))}
            {entries.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-aether-muted">
                  No admin actions recorded yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-aether-muted-dim">
        <span>
          {total === 0 ? "0" : `${offset + 1}–${offset + entries.length}`} of {total}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => void load(Math.max(0, offset - PAGE))}
            disabled={offset === 0}
            className="rounded-md border border-white/10 px-3 py-1.5 text-aether-muted hover:text-aether-text disabled:opacity-40"
          >
            Previous
          </button>
          <button
            onClick={() => void load(offset + PAGE)}
            disabled={offset + entries.length >= total}
            className="rounded-md border border-white/10 px-3 py-1.5 text-aether-muted hover:text-aether-text disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
