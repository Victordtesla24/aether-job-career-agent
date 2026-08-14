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
import { useRealtimeResources } from "../../../hooks/useRealtime";
import {
  decideApproval,
  executeApproval,
  fetchApproval,
  type DecisionContext,
} from "../../../components/approvals/api";
import {
  canRemove,
  isExpired,
  needsSendRetry,
  parseApprovalPayload,
  sendsOnApprove,
  substantiveExcerpt,
  summarize,
} from "../../../components/approvals/lib";
import {
  deleteApproval,
  fetchApprovals,
  purgeExpiredApprovals,
  type Approval,
} from "../../../lib/api/approvals";
import { fetchApplySweepStatus } from "../../../lib/api/applications";
import { automaticSubmissionDisclaimer } from "../../../components/applications/tracker-lib";

type StatusFilter = "pending" | "approved" | "rejected" | "all";

/** Sync the ?review= deep-link param without a Next.js navigation. */
function syncReviewParam(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("review", id);
  else url.searchParams.delete("review");
  window.history.replaceState(null, "", url.toString());
}

/**
 * Approving a request only flips its status — the send itself is the separate
 * POST /approvals/{id}/execute call, the endpoint's one real side effect
 * (MV-approval-modal-008). Fire it immediately so the wireframed "Approve"
 * action actually sends end-to-end; a send failure is reported honestly
 * without hiding that the approval itself went through (returns the message
 * to show, or null when nothing went wrong).
 *
 * MUST-FIX 1 (round-4 re-review): which requests this covers is decided by
 * `sendsOnApprove` — an outreach `email_send` AND an application whose
 * resolved apply channel is EMAIL (`application_submit` with
 * `payload.kind = "submission"`), which the same endpoint really transmits.
 * Gating on the approval TYPE alone left every email-channel application
 * approved-and-unsent, with `notTransmittedReason` telling the user that
 * approving it would email the employer.
 */
async function sendIfSendable(
  resolved: Approval,
  decision: "approve" | "reject",
): Promise<string | null> {
  if (decision !== "approve" || !sendsOnApprove(resolved)) return null;
  try {
    await executeApproval(resolved.id);
    return null;
  } catch (e) {
    return `Approved, but sending it failed: ${
      e instanceof Error ? e.message : "unknown error"
    }. Nothing was sent — use "Retry send" on the request below to try again.`;
  }
}

/**
 * The approved requests whose send never happened (MUST-FIX 2, round-4
 * re-review). A failed send releases the server's execution claim, leaving the
 * approval `approved` with nothing sent — invisible under the default
 * `pending` filter, which is where every failed send used to disappear to
 * while the error copy pointed at a retry the UI did not have.
 *
 * Best-effort by design: this is a SECOND list request layered on the one the
 * user asked for, so its failure must never take the queue down — an empty
 * result under-promises (no retry offered) rather than inventing state.
 */
async function fetchStrandedSends(): Promise<Approval[]> {
  try {
    return (await fetchApprovals("approved")).filter(needsSendRetry);
  } catch {
    return [];
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
  // SHOULD-FIX 6 (round-3 re-review): live read of the operator's apply-sweep
  // kill-switch, for the bulk-approve confirm copy (`automaticSubmissionDisclaimer`).
  // Defaults false — the code default, and the honest choice while this fetch
  // is still in flight — so a slow/failed status fetch can only ever
  // under-promise, never claim automation that is not actually configured.
  const [sweepEnabled, setSweepEnabled] = useState(false);
  useEffect(() => {
    fetchApplySweepStatus()
      .then(setSweepEnabled)
      .catch(() => {
        /* best-effort: keep the honest false default on failure */
      });
  }, []);
  // Monotonic guard: a stale (slow) response must never overwrite a newer one.
  const fetchSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++fetchSeq.current;
    try {
      const rows = await fetchApprovals(filter);
      // Approved-but-unsent requests are not `pending`, so the default filter
      // hides exactly the rows that need a human the most. Merge them in (by
      // id, never duplicating a row the filter already returned) so the
      // "Retry send" affordance the failure copy names is actually on screen.
      const stranded = filter === "pending" ? await fetchStrandedSends() : [];
      if (seq !== fetchSeq.current) return;
      const seen = new Set(rows.map((r) => r.id));
      setApprovals([...rows, ...stranded.filter((s) => !seen.has(s.id))]);
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

  // W-RT — the shared realtime channel. Approval requests are created by agents
  // and resolved from other surfaces (the dashboard's inline queue, another
  // tab); without this the queue only ever reflected what THIS tab did.
  // Deliberately does NOT clear the list first — a refresh in place must not
  // blank the queue the user is reading.
  useRealtimeResources(["approvals"], () => {
    void load();
  });

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

  /** Report a send failure AFTER reconciling the list, never before: `load`
   *  clears `listError` on success, so setting the message first would wipe it
   *  off screen the moment the refresh landed — and that refresh is what puts
   *  the retryable row (the message's own remediation) in front of the user. */
  const reportSendFailure = useCallback(
    async (sendError: string | null) => {
      if (sendError) await load();
      setListError(sendError);
    },
    [load],
  );

  const decideFromCard = async (id: string, decision: "approve" | "reject") => {
    setBusy(id);
    try {
      const resolved = await decideApproval(id, decision);
      applyResolved(resolved);
      await reportSendFailure(await sendIfSendable(resolved, decision));
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
    await reportSendFailure(await sendIfSendable(resolved, decision));
  };

  /**
   * Re-invoke the send behind an approved-but-unsent request (MUST-FIX 2).
   * The SAME POST /approvals/{id}/execute the approve path fires — idempotent
   * server-side: the execution claim is single-shot, so a request that did
   * send answers 409 and sends nothing again, and a request that did not is
   * transmitted for real (pinned by apps/api/tests/test_u5_email_retry.py).
   * The list is reconciled either way, so the row's state after this click is
   * the server's, not a guess.
   */
  const retrySend = async (approval: Approval) => {
    setBusy(approval.id);
    try {
      await executeApproval(approval.id);
      await load();
      setListError(null);
    } catch (e) {
      await load();
      setListError(
        `Retry failed — nothing was sent: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    } finally {
      setBusy(null);
    }
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

  /**
   * QA-2026-08-13 H-02, behavior fixed 2026-08-14 (C2, round-3 re-review):
   * bulk decision over every currently-listed pending request. The backend
   * has no bulk endpoint, so this loops the existing POST
   * /approvals/{id}/approve|reject sequentially (server remains the only
   * authority on each transition).
   *
   * Every request Aether can send by email IS sent here — for each approved
   * item this fires the SAME `sendIfSendable` a single-card approve does,
   * right after its own decision lands (sequential, per-item, honest partial
   * failure). That covers an outreach `email_send` AND an application whose
   * resolved apply channel is EMAIL (`application_submit` +
   * `payload.kind = "submission"`); `sendsOnApprove` is the single definition,
   * shared with the card and modal paths. Before this fix, `bulkDecide` only
   * ever called `decideApproval`, so a bulk-approved request was left
   * `approved` with nothing to ever send it — permanently "prepared only".
   * A send failure never hides inside the decision-failure count below: the
   * decision succeeded even when the send did not, the two are reported
   * separately, and a failed send leaves a row that surfaces in this queue
   * with a working "Retry send" (`needsSendRetry`).
   *
   * The OTHER `application_submit` approvals — the artifact cards
   * (`kind = "resume_tailor"` / `"cover_letter"`) and any application whose
   * channel is an employer FORM — are not driven further by this action;
   * approving one only records the decision. For a form channel, whether
   * anything happens next depends entirely on the operator's
   * `AETHER_APPLY_SWEEP_ENABLED` sweep (apps/api/app/workers/apply_sweep.py,
   * `sweepEnabled` above reads its live state via GET
   * /applications/apply-sweep-status): OFF by default, in which case the
   * application stays honestly "ready to submit" until a human acts on it;
   * ON, the sweep drives the submission on its OWN schedule, not on this
   * click. `automaticSubmissionDisclaimer` states exactly that split.
   */
  const bulkDecide = async (decision: "approve" | "reject") => {
    const targets = (approvals ?? []).filter((a) => a.status === "pending" && !isExpired(a));
    if (targets.length === 0) return;
    const verb = decision === "approve" ? "Approve" : "Reject";
    if (
      !window.confirm(
        `${verb} all ${targets.length} pending request${targets.length === 1 ? "" : "s"}? ` +
          (decision === "approve"
            ? automaticSubmissionDisclaimer(sweepEnabled)
            : "Rejected requests can be re-created by the agents on their next run."),
      )
    ) {
      return;
    }
    setBusy(`bulk-${decision}`);
    let decisionFailed = 0;
    let sendFailed = 0;
    for (const approval of targets) {
      let resolved: Approval;
      try {
        resolved = await decideApproval(approval.id, decision);
      } catch {
        decisionFailed += 1;
        continue;
      }
      // C2: a bulk-approved sendable request must be sent exactly like a
      // single-card approve — otherwise it is left "prepared only" with no
      // send affordance anywhere else in the product. No-op for a reject
      // decision or a non-sendable type (sendIfSendable's own gate).
      const sendError = await sendIfSendable(resolved, decision);
      if (sendError) sendFailed += 1;
    }
    const parts: string[] = [];
    if (decisionFailed > 0) {
      parts.push(
        `${decisionFailed} of ${targets.length} bulk ${decision} decisions failed — the rest were applied`,
      );
    }
    if (sendFailed > 0) {
      parts.push(
        `${sendFailed} approved request${sendFailed === 1 ? "" : "s"} failed to send — ` +
          `nothing was sent for ${sendFailed === 1 ? "it" : "them"}; use "Retry send" on the ` +
          `affected request${sendFailed === 1 ? "" : "s"} below`,
      );
    }
    // Reconcile from server truth FIRST — list, badges and counters together —
    // then report, because `load` clears `listError` on success and the
    // refreshed list is what puts the "Retry send" rows named above on screen.
    await load();
    if (parts.length > 0) setListError(`${parts.join("; ")}.`);
    setBusy(null);
  };

  const pendingCount = approvals?.filter((a) => a.status === "pending").length ?? null;
  const expiredCount = approvals?.filter((a) => isExpired(a)).length ?? 0;
  const actionablePendingCount =
    approvals?.filter((a) => a.status === "pending" && !isExpired(a)).length ?? 0;

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
        {actionablePendingCount > 1 ? (
          <div className="flex gap-2" data-testid="bulk-actions">
            <button
              type="button"
              data-testid="bulk-approve-btn"
              onClick={() => void bulkDecide("approve")}
              disabled={busy !== null}
              className="min-h-[44px] rounded-xl border border-aether-green/40 px-4 text-sm font-semibold text-aether-green hover:bg-aether-green/10 disabled:opacity-50 sm:min-h-0 sm:py-2"
            >
              Approve all ({actionablePendingCount})
            </button>
            <button
              type="button"
              data-testid="bulk-reject-btn"
              onClick={() => void bulkDecide("reject")}
              disabled={busy !== null}
              className="min-h-[44px] rounded-xl border border-red-500/40 px-4 text-sm font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50 sm:min-h-0 sm:py-2"
            >
              Reject all
            </button>
          </div>
        ) : null}
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
                      {needsSendRetry(approval) ? (
                        <span
                          data-testid="unsent-badge"
                          className="rounded-full border border-aether-amber/40 bg-aether-amber/10 px-2 py-0.5 text-xs text-aether-amber"
                          title="Approved, but the send did not go through — nothing has been sent yet"
                        >
                          not sent
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
                      {approval.type} · requested {new Date(approval.createdAt).toLocaleString("en-AU")}
                      {approval.resolvedAt
                        ? ` · resolved ${new Date(approval.resolvedAt).toLocaleString("en-AU")}`
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
                    {needsSendRetry(approval) ? (
                      <button
                        type="button"
                        data-testid="retry-send-btn"
                        onClick={() => void retrySend(approval)}
                        disabled={busy === approval.id}
                        className="min-h-[44px] rounded-xl border border-aether-amber/40 px-4 text-sm font-semibold text-aether-amber hover:bg-aether-amber/10 disabled:opacity-50 sm:min-h-0 sm:py-2"
                      >
                        Retry send
                      </button>
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
