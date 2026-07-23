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
import type { DecisionContext } from "./api";
import { isExpired, metaLine, parseApprovalPayload, previewLabel } from "./lib";

interface ApprovalModalProps {
  approval: Approval;
  onClose: () => void;
  /** Resolves when the API call lands; throwing keeps the modal open. */
  onDecide: (decision: "approve" | "reject", context: DecisionContext) => Promise<void>;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
          {details.reasoning.length > 0 ? (
            <div>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
                AI reasoning
              </p>
              <ul data-testid="modal-reasoning" className="flex flex-col gap-1.5 text-xs text-aether-muted">
                {details.reasoning.map((item, index) => (
                  <li key={index} className="flex gap-2">
                    <i
                      className={`mt-0.5 text-[10px] ${
                        item.kind === "warning"
                          ? "fa-solid fa-triangle-exclamation text-aether-yellow"
                          : "fa-solid fa-check text-aether-green"
                      }`}
                      aria-hidden="true"
                    />
                    <span>
                      <span className="sr-only">
                        {item.kind === "warning" ? "Caveat: " : "Verified: "}
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
                ? ` on ${new Date(approval.resolvedAt).toLocaleString()}`
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
            disabled={!pending || busy !== null}
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
            disabled={!pending || busy !== null}
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
