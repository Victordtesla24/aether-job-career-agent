"use client";

/**
 * Approvals queue — the human-in-the-loop gate (wireframe approval-modal.html).
 *
 * Queue backed by GET /approvals; reviewing a request opens the global
 * ApprovalModal overlay (deep-linkable via ?review=<id> so any route can
 * trigger it). Decisions POST /approvals/{id}/approve|reject and update the
 * queue in place.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalModal } from "../../../components/approvals/ApprovalModal";
import {
  decideApproval,
  executeApproval,
  fetchApproval,
  type DecisionContext,
} from "../../../components/approvals/api";
import {
  canRemove,
  isExpired,
  parseApprovalPayload,
  substantiveExcerpt,
  summarize,
} from "../../../components/approvals/lib";
import {
  deleteApproval,
  fetchApprovals,
  purgeExpiredApprovals,
  type Approval,
} from "../../../lib/api/approvals";

type StatusFilter = "pending" | "approved" | "rejected" | "all";

/** Sync the ?review= deep-link param without a Next.js navigation. */
function syncReviewParam(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("review", id);
  else url.searchParams.delete("review");
  window.history.replaceState(null, "", url.toString());
}

/**
 * Approving an email_send request only flips its status — the Gmail send
 * itself is the separate POST /approvals/{id}/execute call, the endpoint's
 * one real side effect (MV-approval-modal-008). Fire it immediately so the
 * wireframed "Approve" action actually sends the email end-to-end; a send
 * failure is reported honestly without hiding that the approval itself went
 * through (returns the message to show, or null when nothing went wrong).
 */
async function sendIfEmailApproval(
  resolved: Approval,
  decision: "approve" | "reject",
): Promise<string | null> {
  if (decision !== "approve" || resolved.type !== "email_send") return null;
  try {
    await executeApproval(resolved.id);
    return null;
  } catch (e) {
    return `Approved, but sending the email failed: ${
      e instanceof Error ? e.message : "please retry from the approval."
    }`;
  }
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [busy, setBusy] = useState<string | null>(null);
  // Two independent error slots so a successful list refresh can never
  // clobber a still-relevant deep-link failure (MV-approval-modal-006 /
  // MV-mobile-approval-002) — each source only ever writes its own slot.
  const [listError, setListError] = useState<string | null>(null);
  const [deepLinkError, setDeepLinkError] = useState<string | null>(null);
  const error = deepLinkError ?? listError;
  const [reviewing, setReviewing] = useState<Approval | null>(null);
  // Monotonic guard: a stale (slow) response must never overwrite a newer one.
  const fetchSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++fetchSeq.current;
    try {
      const rows = await fetchApprovals(filter);
      if (seq !== fetchSeq.current) return;
      setApprovals(rows);
      setListError(null);
    } catch (e) {
      if (seq !== fetchSeq.current) return;
      setListError(e instanceof Error ? e.message : "Failed to load approvals");
      setApprovals([]);
    }
  }, [filter]);

  useEffect(() => {
    setApprovals(null);
    void load();
  }, [load]);

  // Deep link: /dashboard/approvals?review=<id> opens the modal directly.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("review");
    if (!id) return;
    fetchApproval(id)
      .then((approval) => {
        // Splice a "modal closed" entry underneath the deep-linked "modal
        // open" state so Back always has a same-page entry to land on
        // instead of leaving the Approvals screen entirely
        // (MV-approval-modal-005).
        const bareUrl = new URL(window.location.href);
        bareUrl.searchParams.delete("review");
        window.history.replaceState(null, "", bareUrl.toString());
        const openUrl = new URL(window.location.href);
        openUrl.searchParams.set("review", id);
        window.history.pushState({ approvalReview: id }, "", openUrl.toString());
        setReviewing(approval);
      })
      .catch(() => {
        syncReviewParam(null);
        setDeepLinkError("The linked approval request could not be found.");
      });
  }, []);

  // Back/Forward: the review modal's open state lives in history (see
  // openReview/closeReview below), so popping to an entry without ?review=
  // must just close the dialog, never leave /dashboard/approvals
  // (MV-approval-modal-005).
  useEffect(() => {
    const onPopState = () => {
      const id = new URLSearchParams(window.location.search).get("review");
      if (!id) setReviewing(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const openReview = (approval: Approval) => {
    setReviewing(approval);
    setDeepLinkError(null);
    const url = new URL(window.location.href);
    url.searchParams.set("review", approval.id);
    window.history.pushState({ approvalReview: approval.id }, "", url.toString());
  };

  const closeReview = () => {
    setReviewing(null);
    // Consume the history entry pushed on open (if any) instead of just
    // rewriting the URL in place, so Back closes the modal exactly once
    // (MV-approval-modal-005) rather than leaving a stale entry behind.
    if (new URLSearchParams(window.location.search).get("review")) {
      window.history.back();
    } else {
      syncReviewParam(null);
    }
  };

  /** Replace the decided row in place; drop it if it no longer matches the filter. */
  const applyResolved = useCallback(
    (resolved: Approval) => {
      setApprovals((current) => {
        if (!current) return current;
        const keep = filter === "all" || resolved.status === filter;
        return keep
          ? current.map((a) => (a.id === resolved.id ? resolved : a))
          : current.filter((a) => a.id !== resolved.id);
      });
    },
    [filter],
  );

  const decideFromCard = async (id: string, decision: "approve" | "reject") => {
    setBusy(id);
    try {
      const resolved = await decideApproval(id, decision);
      applyResolved(resolved);
      setListError(await sendIfEmailApproval(resolved, decision));
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusy(null);
    }
  };

  const decideFromModal = async (decision: "approve" | "reject", context: DecisionContext) => {
    if (!reviewing) return;
    const resolved = await decideApproval(reviewing.id, decision, context);
    applyResolved(resolved);
    closeReview();
    const sendError = await sendIfEmailApproval(resolved, decision);
    if (sendError) setListError(sendError);
  };

  /** Remove one stale (expired/resolved) card — server enforces the 409 guard. */
  const removeFromCard = async (approval: Approval) => {
    if (
      !window.confirm(
        `Remove this ${approval.status === "pending" ? "expired" : approval.status} approval request? This cannot be undone.`,
      )
    ) {
      return;
    }
    setBusy(approval.id);
    try {
      await deleteApproval(approval.id);
      setListError(null);
      // Reconcile from server truth — list, badges and counters together.
      await load();
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Failed to remove the approval");
    } finally {
      setBusy(null);
    }
  };

  /** Bulk "Clear expired": ONE request; expiry decided server-side (48h). */
  const clearExpired = async (count: number) => {
    if (
      !window.confirm(
        `Remove ${count} expired approval request${count === 1 ? "" : "s"}? This cannot be undone.`,
      )
    ) {
      return;
    }
    setBusy("purge-expired");
    try {
      await purgeExpiredApprovals();
      setListError(null);
      await load();
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Failed to clear expired approvals");
    } finally {
      setBusy(null);
    }
  };

  const pendingCount = approvals?.filter((a) => a.status === "pending").length ?? null;
  const expiredCount = approvals?.filter((a) => isExpired(a)).length ?? 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Approvals</h1>
          <p className="text-sm text-aether-muted">
            Nothing is sent without your sign-off. Requests expire after 48h.
            {pendingCount !== null && filter === "pending" ? (
              <span className="ml-2 font-mono text-xs text-aether-muted-dim" data-testid="pending-count">
                {pendingCount} pending
              </span>
            ) : null}
          </p>
        </div>
        {expiredCount > 0 ? (
          <button
            type="button"
            data-testid="clear-expired-btn"
            onClick={() => void clearExpired(expiredCount)}
            disabled={busy === "purge-expired"}
            className="min-h-[44px] rounded-xl border border-red-500/40 px-4 text-sm font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50 sm:min-h-0 sm:py-2"
          >
            Clear expired ({expiredCount})
          </button>
        ) : null}
        <div
          className="flex gap-1 rounded-xl border border-white/10 p-1"
          role="group"
          aria-label="Filter approvals by status"
        >
          {(["pending", "approved", "rejected", "all"] as StatusFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={filter === s}
              onClick={() => setFilter(s)}
              className={`min-h-[44px] rounded-lg px-3 text-sm capitalize sm:min-h-0 sm:py-1 ${
                filter === s ? "bg-aether-coral font-semibold text-white" : "text-aether-muted"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </header>

      {error ? (
        <p
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
        >
          {error}
        </p>
      ) : null}

      {approvals === null ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass h-24 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : approvals.length === 0 ? (
        <div
          className="glass rounded-2xl border border-white/10 p-10 text-center"
          data-testid="approvals-empty-state"
        >
          <p className="text-lg font-semibold">Queue clear</p>
          <p className="mt-1 text-sm text-aether-muted">
            No {filter === "all" ? "" : `${filter} `}approval requests right now.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((approval) => {
            const details = parseApprovalPayload(approval);
            const expired = isExpired(approval);
            return (
              <article
                key={approval.id}
                data-testid="approval-card"
                className="glass rounded-2xl border border-white/10 p-5 transition hover:border-white/15"
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="min-w-0 break-words font-semibold">{summarize(approval)}</h2>
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
                      {details.confidence !== null ? (
                        <span className="font-mono text-xs text-aether-green">
                          {details.confidence}%
                        </span>
                      ) : null}
                      {expired ? (
                        <span
                          data-testid="expired-badge"
                          className="rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-xs text-red-300"
                          title="Older than 48h — re-run the agent to get a fresh request"
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
                    {details.preview ? (
                      <p className="mt-2 line-clamp-3 whitespace-pre-line text-sm text-aether-muted">
                        {substantiveExcerpt(details.preview)}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid="review-btn"
                      onClick={() => openReview(approval)}
                      className="min-h-[44px] rounded-xl border border-aether-indigo/40 px-4 text-sm font-semibold text-[#A5B4FC] hover:bg-aether-indigo/10 sm:min-h-0 sm:py-2"
                    >
                      {approval.status === "pending" ? "Review" : "View"}
                    </button>
                    {approval.status === "pending" ? (
                      <>
                        <button
                          type="button"
                          data-testid="approve-btn"
                          onClick={() => void decideFromCard(approval.id, "approve")}
                          disabled={busy === approval.id || expired}
                          className="min-h-[44px] rounded-xl bg-aether-green/80 px-4 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50 sm:min-h-0 sm:py-2"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          data-testid="reject-btn"
                          onClick={() => void decideFromCard(approval.id, "reject")}
                          disabled={busy === approval.id || expired}
                          className="min-h-[44px] rounded-xl border border-red-500/40 px-4 text-sm font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50 sm:min-h-0 sm:py-2"
                        >
                          Reject
                        </button>
                      </>
                    ) : null}
                    {canRemove(approval) ? (
                      <button
                        type="button"
                        data-testid="remove-btn"
                        aria-label={`Remove ${approval.status === "pending" ? "expired" : approval.status} approval request`}
                        onClick={() => void removeFromCard(approval)}
                        disabled={busy === approval.id}
                        className="min-h-[44px] rounded-xl border border-white/15 px-4 text-sm font-semibold text-aether-muted hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-50 sm:min-h-0 sm:py-2"
                      >
                        Remove
                      </button>
                    ) : null}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {reviewing ? (
        <ApprovalModal approval={reviewing} onClose={closeReview} onDecide={decideFromModal} />
      ) : null}
    </div>
  );
}
