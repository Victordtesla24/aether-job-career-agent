"use client";

/**
 * Approval Modal (global) — wireframe design/screens/approval-modal.html.
 *
 * Fully payload-driven: header subtitle, action summary, confidence, "why",
 * AI reasoning and the letter preview all come from the approval row. The
 * dialog traps focus, closes on Esc / backdrop / ×, and supports the three
 * wireframe decisions: Reject, Edit & Approve (inline textarea), Approve.
 * At the mobile breakpoint the footer stacks per mobile-approval.html.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { Approval } from "../../lib/api/approvals";
import { fetchResumeFidelity } from "../../lib/api/resumes";
import type { DecisionContext } from "./api";
import {
  FIDELITY_CHECKING,
  FIDELITY_FETCH_FAILED,
  type LiveFidelity,
  describeDimension,
  isExpired,
  metaLine,
  parseApprovalPayload,
  parseQualityGate,
  payloadKind,
  previewLabel,
  withLiveFidelity,
} from "./lib";

interface ApprovalModalProps {
  approval: Approval;
  onClose: () => void;
  /** Resolves when the API call lands; throwing keeps the modal open. */
  onDecide: (decision: "approve" | "reject", context: DecisionContext) => Promise<void>;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The résumé id a PENDING ``resume_tailor`` approval's live fidelity check
 * fetches for, or ``null`` when this approval will never fetch one (wrong
 * kind, resolved, or a payload with no ``resume_id``). Shared by the state
 * initializer and the fetch effect below (MF-A) so the two can never
 * disagree about whether a fetch is coming.
 */
function fidelityResumeId(approval: Approval): string | null {
  if (approval.status !== "pending" || payloadKind(approval) !== "resume_tailor") return null;
  const resumeId = (approval.payload as { resume_id?: unknown }).resume_id;
  return typeof resumeId === "string" ? resumeId : null;
}

function initialFidelity(approval: Approval): LiveFidelity | null {
  return fidelityResumeId(approval) !== null ? FIDELITY_CHECKING : null;
}

export function ApprovalModal({ approval, onClose, onDecide }: ApprovalModalProps) {
  const details = parseApprovalPayload(approval);
  const expired = isExpired(approval);
  const pending = approval.status === "pending" && !expired;
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const [editing, setEditing] = useState(false);
  const [editedPreview, setEditedPreview] = useState(details.preview ?? "");
  const [trustAgent, setTrustAgent] = useState(
    (approval.payload as { trust_agent?: unknown }).trust_agent === true,
  );
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // U2c: the artifact's own 80%-across-all-dimensions verdict, read off the
  // payload the agent stamped it on. `null` = never gated (every approval
  // predating the gate) — the modal then says nothing and blocks nothing,
  // because claiming a verdict that was never computed is its own lie.
  const qualityGate = parseQualityGate(approval);
  const belowFloor = qualityGate !== null && !qualityGate.passed;
  const [acknowledgedBelowFloor, setAcknowledgedBelowFloor] = useState(false);

  // ML-U2B-approval-honesty ruling 2: a PENDING resume_tailor approval's
  // "Original layout" reasoning line is superseded by the résumé's LIVE,
  // verified fidelity — never the frozen mechanism-level snapshot the
  // approval was written with (see lib.ts withLiveFidelity). Resolved
  // approvals and every other kind never fetch — nothing to supersede.
  //
  // MF-A (round-5 re-review): the frozen claim used to render, unsupervised,
  // for this fetch's ENTIRE in-flight window (~220-260ms in production;
  // indefinitely on a hang, since nothing in lib/api bounded a fetch with a
  // timeout — see resumes.ts FIDELITY_FETCH_TIMEOUT_MS for the other half of
  // this fix). The lazy initializer seeds FIDELITY_CHECKING synchronously,
  // in the SAME render that first learns a fetch is coming, so there is
  // never a paint with the frozen claim on screen — not even one frame — for
  // an approval this modal is about to check. The render-phase reset below
  // (React's documented "adjust state when a prop changes" pattern) gives
  // the same guarantee when this modal is reused for a different approval
  // without unmounting.
  const [seenApproval, setSeenApproval] = useState(approval);
  const [liveFidelity, setLiveFidelity] = useState<LiveFidelity | null>(() =>
    initialFidelity(approval),
  );
  if (approval !== seenApproval) {
    setSeenApproval(approval);
    setLiveFidelity(initialFidelity(approval));
  }
  useEffect(() => {
    const resumeId = fidelityResumeId(approval);
    if (resumeId === null) return;
    let cancelled = false;
    fetchResumeFidelity(resumeId)
      .then((fidelity) => {
        if (!cancelled) setLiveFidelity({ preserved: fidelity.formatPreserved, note: fidelity.note });
      })
      .catch(() => {
        // MF-1 (round-4 re-review): a failed fidelity fetch must NOT leave
        // the frozen "Original layout preserved" claim rendering as a green
        // "Verified" check — that silently restores the exact false-claim
        // pattern this slice exists to kill. Downgrade to the honest-unknown
        // warning instead of a no-op (`null` would keep showing the frozen
        // line unchanged; see withLiveFidelity's docstring). A timed-out
        // fetch (MF-A) rejects the same as any other network failure and
        // lands here too — never a silent revert to the frozen text.
        if (!cancelled) setLiveFidelity(FIDELITY_FETCH_FAILED);
      });
    return () => {
      cancelled = true;
    };
  }, [approval]);
  const reasoning = withLiveFidelity(approval, details.reasoning, liveFidelity);

  // Focus management: remember the trigger, move focus in, restore on close.
  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
      restoreFocusRef.current?.focus?.();
    };
  }, []);

  // Document-level so Esc and the Tab trap work no matter where focus sits
  // (e.g. after a backdrop mousedown focus can land on <body>). Hidden
  // elements — the display:none twin footer at the other breakpoint — must
  // not count as focus bounds, hence the getClientRects() visibility filter.
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      ).filter((node) => node.getClientRects().length > 0);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      const inside = active instanceof HTMLElement && dialogRef.current?.contains(active);
      if (!inside || active === dialogRef.current) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [handleKeyDown]);

  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision);
    setError(null);
    try {
      const context: DecisionContext = { trustAgent };
      if (decision === "approve" && belowFloor) {
        // Only ever sent with an APPROVE: rejecting a below-floor artifact is
        // the safe direction and is never gated.
        context.acknowledgeBelowFloor = acknowledgedBelowFloor;
      }
      if (decision === "approve" && editing && editedPreview !== (details.preview ?? "")) {
        context.editedPreview = editedPreview;
      }
      await onDecide(decision, context);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed — please retry");
      setBusy(null);
      return;
    }
    setBusy(null);
  };

  const approveLabel = editing ? "Approve with edits" : "Approve";
  // A below-floor artifact is never WITHHELD — it is readable, editable and
  // approvable. What it may not be is approved by accident.
  const approveBlocked = belowFloor && !acknowledgedBelowFloor;

  return (
    <div
      data-testid="approval-modal-backdrop"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="approval-modal"
        className="glass-raised flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-3xl border border-white/10 shadow-2xl shadow-black/60 outline-none sm:max-h-[85vh] sm:w-[560px] sm:rounded-3xl"
      >
        {/* Header */}
        <div className="border-b border-white/10 px-5 pb-5 pt-6 sm:px-7 sm:pt-7">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-aether-yellow/25 bg-aether-yellow/15"
                aria-hidden="true"
              >
                <i className="fa-solid fa-shield-halved text-aether-yellow" />
              </div>
              <div>
                <h2 id={titleId} className="text-lg font-bold leading-tight">
                  Approval Needed
                </h2>
                <p className="mt-0.5 text-xs text-aether-muted">
                  {details.agent} wants to {details.action}
                </p>
              </div>
            </div>
            <button
              type="button"
              data-testid="modal-close-btn"
              aria-label="Close approval dialog"
              onClick={onClose}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-aether-muted-dim transition hover:bg-white/10 hover:text-white sm:h-8 sm:w-8"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-7">
          {/* Action summary */}
          <div className="flex items-center gap-3">
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-xs font-bold"
              aria-hidden="true"
            >
              {details.initials}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">
                {details.jobTitle ?? summarizeType(approval)}
              </p>
              {metaLine(details) !== "" ? (
                <p className="truncate text-xs text-aether-muted">{metaLine(details)}</p>
              ) : null}
            </div>
            {details.confidence !== null ? (
              <div className="text-right" data-testid="modal-confidence">
                <div className="font-mono text-sm font-bold text-aether-green">
                  {details.confidence}%
                </div>
                <p className="text-[10px] text-aether-muted-dim">confidence</p>
              </div>
            ) : null}
          </div>

          {/* Why approval is needed */}
          {details.why ? (
            <div className="glass relative overflow-hidden rounded-xl border border-aether-indigo/25 p-4">
              <div
                className="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-aether-indigo/10 blur-2xl"
                aria-hidden="true"
              />
              <div className="mb-2 flex items-center gap-2">
                <i className="fa-solid fa-brain text-xs text-[#818CF8]" aria-hidden="true" />
                <span className="text-xs font-semibold">Why approval is needed</span>
              </div>
              <p data-testid="modal-why" className="text-xs leading-relaxed text-[#C8C8DC]">
                {details.why}
              </p>
            </div>
          ) : null}

          {/* AI reasoning */}
          {reasoning.length > 0 ? (
            <div>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
                AI reasoning
              </p>
              <ul data-testid="modal-reasoning" className="flex flex-col gap-1.5 text-xs text-aether-muted">
                {reasoning.map((item, index) => (
                  <li key={index} className="flex gap-2">
                    <i
                      className={`mt-0.5 text-[10px] ${
                        item.kind === "warning"
                          ? "fa-solid fa-triangle-exclamation text-aether-yellow"
                          : item.kind === "checking"
                            ? "fa-solid fa-circle-notch fa-spin text-aether-muted-dim"
                            : "fa-solid fa-check text-aether-green"
                      }`}
                      aria-hidden="true"
                    />
                    <span>
                      <span className="sr-only">
                        {item.kind === "warning"
                          ? "Caveat: "
                          : item.kind === "checking"
                            ? "Checking: "
                            : "Verified: "}
                      </span>
                      {item.text}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* Generated preview — read or edit */}
          {details.preview !== null || editing ? (
            <div className="glass rounded-xl border border-white/10 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
                  {previewLabel(approval)}
                </span>
                <span className="text-[10px] text-[#818CF8]">
                  {editing ? "editing" : "preview"}
                </span>
              </div>
              {editing ? (
                <textarea
                  data-testid="modal-edit-textarea"
                  aria-label="Edit the generated cover letter before approving"
                  value={editedPreview}
                  onChange={(event) => setEditedPreview(event.target.value)}
                  rows={6}
                  className="w-full resize-y rounded-lg border border-white/10 bg-white/5 p-3 text-xs leading-relaxed text-aether-text outline-none focus:border-aether-indigo/50"
                />
              ) : (
                <p
                  data-testid="modal-preview"
                  className="line-clamp-3 text-xs leading-relaxed text-aether-muted"
                >
                  {details.preview}
                </p>
              )}
            </div>
          ) : null}

          {/* U2c — below the quality floor: the failing dimensions, verbatim */}
          {belowFloor && qualityGate ? (
            <div
              data-testid="modal-quality-floor"
              className="rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100"
            >
              <p className="font-semibold">
                Below Aether&apos;s {qualityGate.floor.toFixed(0)}% quality floor
              </p>
              <ul className="mt-2 space-y-1">
                {qualityGate.failing.map((dimension) => (
                  <li key={dimension.key}>{describeDimension(dimension)}</li>
                ))}
              </ul>
              <p className="mt-2 text-amber-200/80">
                This is the real, measured result — nothing was inflated, and no claim
                your evidence does not support was added to reach the floor. You can
                still read, edit and approve it.
              </p>
              {pending ? (
                <label className="mt-3 flex min-h-[44px] cursor-pointer items-center gap-2.5 font-medium text-amber-50">
                  <input
                    type="checkbox"
                    data-testid="below-floor-ack-checkbox"
                    checked={acknowledgedBelowFloor}
                    onChange={(event) => setAcknowledgedBelowFloor(event.target.checked)}
                    className="h-4 w-4 rounded accent-amber-400"
                  />
                  {qualityGate.acknowledgementLabel}
                </label>
              ) : null}
            </div>
          ) : null}

          {/* Trust checkbox */}
          {pending ? (
            <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5 text-xs text-aether-muted">
              <input
                type="checkbox"
                data-testid="trust-agent-checkbox"
                checked={trustAgent}
                onChange={(event) => setTrustAgent(event.target.checked)}
                className="h-4 w-4 rounded accent-aether-coral"
              />
              Trust this agent for similar decisions going forward
            </label>
          ) : null}

          {expired ? (
            <p
              data-testid="modal-expired-note"
              className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300"
            >
              This request is older than 48h and has expired — re-run the agent to get a
              fresh one. Actions are disabled.
            </p>
          ) : null}

          {approval.status !== "pending" ? (
            <p className="rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted">
              This request was already {approval.status}
              {approval.resolvedAt
                ? ` on ${new Date(approval.resolvedAt).toLocaleString("en-AU")}`
                : ""}
              .
            </p>
          ) : null}

          {error ? (
            <p
              role="alert"
              data-testid="modal-error"
              className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300"
            >
              {error}
            </p>
          ) : null}
        </div>

        {/* Footer — desktop order per approval-modal.html */}
        <div className="hidden items-center gap-3 border-t border-white/10 px-7 py-5 sm:flex">
          <button
            type="button"
            data-testid="modal-reject-btn"
            onClick={() => void decide("reject")}
            disabled={!pending || busy !== null}
            className="rounded-xl px-5 py-2.5 text-sm font-medium text-aether-muted transition hover:bg-white/5 hover:text-white disabled:opacity-40"
          >
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
          <button
            type="button"
            data-testid="modal-edit-btn"
            onClick={() => setEditing((value) => !value)}
            disabled={!pending || busy !== null || details.preview === null}
            className="ml-auto rounded-xl border border-white/10 bg-white/5 px-5 py-2.5 text-sm font-medium transition hover:bg-white/10 disabled:opacity-40"
          >
            {editing ? "Discard edits" : "Edit & Approve"}
          </button>
          <button
            type="button"
            data-testid="modal-approve-btn"
            onClick={() => void decide("approve")}
            disabled={!pending || busy !== null || approveBlocked}
            className="rounded-xl bg-aether-coral px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:bg-[#ff7d4d] disabled:opacity-40"
          >
            <i className="fa-solid fa-check mr-2 text-xs" aria-hidden="true" />
            {busy === "approve" ? "Approving…" : approveLabel}
          </button>
        </div>

        {/* Footer — mobile stack per mobile-approval.html */}
        <div className="flex flex-col gap-3 border-t border-white/10 px-5 py-4 sm:hidden">
          <button
            type="button"
            data-testid="modal-approve-btn-mobile"
            onClick={() => void decide("approve")}
            disabled={!pending || busy !== null || approveBlocked}
            className="w-full rounded-2xl bg-aether-coral py-3.5 text-sm font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:bg-[#ff7d4d] disabled:opacity-40"
          >
            <i className="fa-solid fa-check mr-2 text-xs" aria-hidden="true" />
            {busy === "approve" ? "Approving…" : editing ? "Approve with edits" : "Approve & Submit"}
          </button>
          <div className="flex gap-3">
            <button
              type="button"
              data-testid="modal-edit-btn-mobile"
              onClick={() => setEditing((value) => !value)}
              disabled={!pending || busy !== null || details.preview === null}
              className="min-h-[44px] flex-1 rounded-2xl border border-white/10 bg-white/5 py-3 text-sm font-medium transition hover:bg-white/10 disabled:opacity-40"
            >
              {editing ? "Discard edits" : "Edit"}
            </button>
            <button
              type="button"
              data-testid="modal-reject-btn-mobile"
              onClick={() => void decide("reject")}
              disabled={!pending || busy !== null}
              className="min-h-[44px] flex-1 rounded-2xl border border-white/10 bg-white/5 py-3 text-sm font-medium text-aether-muted transition hover:bg-white/10 disabled:opacity-40"
            >
              {busy === "reject" ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function summarizeType(approval: Approval): string {
  switch (approval.type) {
    case "email_send":
      return "Outbound email";
    case "offer_response":
      return "Offer response";
    default:
      return "Application package";
  }
}
