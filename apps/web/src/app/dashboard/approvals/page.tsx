"use client";

/**
 * Approvals queue — the human-in-the-loop gate. Backed by GET /approvals,
 * POST /approvals/{id}/approve and POST /approvals/{id}/reject.
 */
import { useCallback, useEffect, useState } from "react";

import {
  approveRequest,
  fetchApprovals,
  rejectRequest,
  type Approval,
} from "../../../lib/api/approvals";

type StatusFilter = "pending" | "approved" | "rejected" | "all";

/** Server-side expiry window (see apps/api approval_service.EXPIRY_HOURS). */
const EXPIRY_HOURS = 48;

/** Pending approvals older than 48h are void — the API answers 409 (D8). */
function isExpired(approval: Approval): boolean {
  return (
    approval.status === "pending" &&
    Date.now() - new Date(approval.createdAt).getTime() > EXPIRY_HOURS * 3600 * 1000
  );
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trustAgent, setTrustAgent] = useState(false);

  const load = useCallback(async () => {
    try {
      setApprovals(await fetchApprovals(filter));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load approvals");
      setApprovals([]);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (id: string, decision: "approve" | "reject") => {
    setBusy(id);
    try {
      if (decision === "approve") await approveRequest(id);
      else await rejectRequest(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusy(null);
    }
  };

  const summarize = (approval: Approval): string => {
    const payload = approval.payload as { kind?: string; job_title?: string; company?: string };
    const kind = payload.kind === "cover_letter" ? "Cover letter" : "Application";
    const target = payload.job_title
      ? ` for ${payload.job_title}${payload.company ? ` @ ${payload.company}` : ""}`
      : "";
    return `${kind}${target}`;
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Approvals</h1>
          <p className="text-sm text-aether-muted">
            Nothing is sent without your sign-off. Requests expire after 48h.
          </p>
        </div>
        <div className="flex gap-1 rounded-xl border border-white/10 p-1">
          {(["pending", "approved", "rejected", "all"] as StatusFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(s)}
              className={`rounded-lg px-3 py-1 text-sm capitalize ${
                filter === s ? "bg-aether-coral font-semibold text-white" : "text-aether-muted"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {/* Approval gate rationale (wireframe approval-modal.html) */}
      <section
        data-testid="approval-explainer"
        className="glass rounded-2xl border border-aether-amber/30 p-5"
      >
        <h2 className="text-[15px] font-semibold">
          <i className="fa-solid fa-shield-halved mr-2 text-aether-amber" aria-hidden="true" />
          Approval Needed
        </h2>
        <div className="mt-3 rounded-xl border border-white/10 bg-white/5 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Why approval is needed
          </p>
          <p className="mt-1 text-sm text-aether-muted">
            This role sits above your salary target and the cover letter references a project
            outside your verified portfolio. Your approval gate for high-stakes applications is on.
          </p>
        </div>
        <label className="mt-3 flex items-center gap-2.5 text-sm text-aether-muted">
          <input
            type="checkbox"
            checked={trustAgent}
            data-testid="trust-agent-checkbox"
            onChange={(e) => setTrustAgent(e.target.checked)}
            className="h-4 w-4 rounded accent-[#FF6B35]"
          />
          Trust this agent for similar decisions going forward
        </label>
      </section>

      {approvals === null ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass h-24 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : approvals.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="approvals-empty-state">
          <p className="text-lg font-semibold">Queue clear</p>
          <p className="mt-1 text-sm text-aether-muted">
            No {filter === "all" ? "" : `${filter} `}approval requests right now.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((approval) => (
            <article
              key={approval.id}
              data-testid="approval-card"
              className="glass rounded-2xl border border-white/10 p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="font-semibold">{summarize(approval)}</h2>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs ${
                        approval.status === "pending"
                          ? "border-aether-amber/40 text-aether-amber"
                          : approval.status === "approved"
                            ? "border-aether-green/40 text-aether-green"
                            : "border-red-500/40 text-red-300"
                      }`}
                    >
                      {approval.status}
                    </span>
                    {isExpired(approval) ? (
                      <span
                        data-testid="expired-badge"
                        className="rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-xs text-red-300"
                        title={`Older than ${EXPIRY_HOURS}h — re-run the agent to get a fresh request`}
                      >
                        expired
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-aether-muted-dim">
                    {approval.type} · requested {new Date(approval.createdAt).toLocaleString()}
                    {approval.resolvedAt
                      ? ` · resolved ${new Date(approval.resolvedAt).toLocaleString()}`
                      : ""}
                  </p>
                  {typeof (approval.payload as { preview?: unknown }).preview === "string" ? (
                    <p className="mt-2 line-clamp-3 whitespace-pre-line text-sm text-aether-muted">
                      {(approval.payload as { preview: string }).preview}
                    </p>
                  ) : null}
                </div>
                {approval.status === "pending" ? (
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      data-testid="approve-btn"
                      onClick={() => void decide(approval.id, "approve")}
                      disabled={busy === approval.id || isExpired(approval)}
                      className="rounded-xl bg-aether-green/80 px-4 py-2 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      data-testid="reject-btn"
                      onClick={() => void decide(approval.id, "reject")}
                      disabled={busy === approval.id || isExpired(approval)}
                      className="rounded-xl border border-red-500/40 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
