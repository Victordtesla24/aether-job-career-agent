/**
 * AddOfferModal — accessible dialog to add an offer to the comparison
 * (interactivity for add-offer-of05 / empty-add-offer-of16). Validated form; on
 * submit it PERSISTS the offer via onAdd (POST /workspaces/offers) and only
 * closes on success — a failed write keeps the draft and shows an inline error
 * (no fake success). Closable via ✕, Cancel, backdrop, Escape.
 *
 * MV-offer-comparison-003: the dialog is rendered through a portal to
 * document.body. The offers page wraps this component as a non-first child of a
 * `space-y-6` container, and Tailwind's `space-y-6` injects `margin-top:1.5rem`
 * (24px) onto every non-first child — including this modal's `fixed inset-0`
 * root, which shifted the overlay down by exactly 24px and left the top strip of
 * the viewport (with the live Topbar controls) uncovered and clickable. Portaling
 * to document.body removes the overlay from that flow entirely, so `fixed
 * inset-0` resolves against the viewport and covers it fully.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  emptyDraft,
  money,
  tabTrapTarget,
  validateOfferDraft,
  type DraftErrors,
  type OfferDraft,
} from "./offers-lib";
import type { OfferCreateInput } from "../../lib/api/workspaces";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href]';

//: Currencies offered for a manually-entered offer — must mirror the API's
//: accepted set so the stored/displayed code is always a real user choice.
const CURRENCIES = ["AUD", "USD", "NZD", "GBP", "EUR", "SGD", "CAD", "INR"] as const;

interface Props {
  open: boolean;
  onClose: () => void;
  /** Persist the offer (POST) and resolve on success; reject to surface an
   * inline error and keep the modal + draft open. */
  onAdd: (input: OfferCreateInput) => Promise<void>;
}

const NUMERIC_FIELDS: Array<keyof OfferDraft> = ["base", "bonus", "equity"];

export function AddOfferModal({ open, onClose, onAdd }: Props) {
  const [draft, setDraft] = useState<OfferDraft>(emptyDraft);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const addCounter = useRef(0);

  useEffect(() => setMounted(true), []);

  // Keep Tab/Shift+Tab trapped inside the dialog (GAP-P4-057).
  const trapTab = useCallback((e: KeyboardEvent) => {
    if (e.key !== "Tab" || !dialogRef.current) return;
    const nodes = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const target = tabTrapTarget(nodes, document.activeElement as HTMLElement | null, e.shiftKey);
    if (target) {
      e.preventDefault();
      target.focus();
    }
  }, []);

  // Reset the form each time the modal opens, and move focus into the dialog.
  useEffect(() => {
    if (!open) return;
    setDraft(emptyDraft());
    setErrors({});
    setSubmitError(null);
    setSubmitting(false);
    const t = setTimeout(() => firstFieldRef.current?.focus(), 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else trapTab(e);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, trapTab]);

  if (!open || !mounted) return null;

  const setField = (key: keyof OfferDraft) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setDraft((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => (prev[key] ? { ...prev, [key]: undefined } : prev));
  };

  const previewTotal =
    [draft.base, draft.bonus, draft.equity]
      .map((v) => Number(v.replace(/[$,\s]/g, "")) || 0)
      .reduce((a, b) => a + b, 0) || 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    addCounter.current += 1;
    const result = validateOfferDraft(draft, String(addCounter.current));
    if (!result.ok || !result.offer) {
      setErrors(result.errors);
      const firstBad = (["company", "base", "location", "bonus", "equity"] as Array<keyof OfferDraft>).find(
        (k) => result.errors[k],
      );
      if (firstBad) {
        const el = dialogRef.current?.querySelector<HTMLInputElement>(`[name="${firstBad}"]`);
        el?.focus();
      }
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      await onAdd({
        company: result.offer.company,
        role: draft.role.trim() || undefined,
        base: result.offer.base,
        bonus: result.offer.bonus,
        equity: result.offer.equity,
        location: result.offer.location,
        currency: draft.currency || "AUD",
      });
      onClose();
    } catch {
      setSubmitError("Could not save the offer. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const field = (
    key: keyof OfferDraft,
    label: string,
    opts: { required?: boolean; placeholder?: string; ref?: boolean } = {},
  ) => {
    const errId = `${titleId}-${key}-err`;
    return (
      <label className="block">
        <span className="mb-1 block text-[11px] uppercase tracking-wide text-aether-muted-dim">
          {label}
          {opts.required ? <span className="text-aether-coral"> *</span> : null}
        </span>
        <div className="relative">
          {NUMERIC_FIELDS.includes(key) ? (
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs text-aether-muted-dim">
              $
            </span>
          ) : null}
          <input
            ref={opts.ref ? firstFieldRef : undefined}
            name={key}
            inputMode={NUMERIC_FIELDS.includes(key) ? "numeric" : "text"}
            value={draft[key]}
            onChange={setField(key)}
            placeholder={opts.placeholder}
            aria-invalid={errors[key] ? true : undefined}
            aria-describedby={errors[key] ? errId : undefined}
            className={`min-h-[44px] w-full rounded-lg border bg-black/25 py-2.5 text-sm text-white placeholder:text-aether-muted-dim focus:outline-none focus:ring-2 focus:ring-aether-coral/50 ${
              NUMERIC_FIELDS.includes(key) ? "pl-7 pr-3" : "px-3"
            } ${errors[key] ? "border-red-500/60" : "border-white/10"}`}
          />
        </div>
        {errors[key] ? (
          <span id={errId} role="alert" className="mt-1 block text-[11px] text-red-400">
            {errors[key]}
          </span>
        ) : null}
      </label>
    );
  };

  const modal = (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" data-testid="add-offer-modal">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="glass-raised relative max-h-[92vh] w-[520px] max-w-[92vw] overflow-y-auto rounded-2xl border border-aether-coral/30 p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id={titleId} className="text-base font-semibold">
              Add an offer
            </h2>
            <p className="mt-1 text-[12px] text-aether-muted">
              Add it to the comparison. The agent scores fit after analysis.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-11 w-11 shrink-0 items-center justify-center text-aether-muted transition hover:text-white"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5" noValidate>
          {field("company", "Company", { required: true, placeholder: "e.g. Figma", ref: true })}
          {field("role", "Role", { placeholder: "e.g. Senior TPM" })}
          <div className="grid grid-cols-3 gap-3">
            {field("base", "Base", { required: true, placeholder: "185000" })}
            {field("bonus", "Bonus", { placeholder: "0" })}
            {field("equity", "Equity / yr", { placeholder: "0" })}
          </div>
          <div className="grid grid-cols-2 gap-3">
            {field("location", "Location", { required: true, placeholder: "e.g. Sydney · Hybrid" })}
            <label className="block">
              <span className="mb-1 block text-[11px] uppercase tracking-wide text-aether-muted-dim">
                Currency
              </span>
              <select
                name="currency"
                value={draft.currency}
                onChange={(e) => setDraft((prev) => ({ ...prev, currency: e.target.value }))}
                className="min-h-[44px] w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-aether-coral/50"
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-[12px]">
            <span className="text-aether-muted-dim">Total comp / yr · {draft.currency}</span>
            <span className="mono font-semibold text-white" data-testid="add-offer-total">
              {money(previewTotal)}
            </span>
          </div>

          {submitError ? (
            <p role="alert" data-testid="add-offer-error" className="text-[12px] text-red-400">
              {submitError}
            </p>
          ) : null}

          <div className="mt-5 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="glass-raised min-h-[44px] rounded-xl px-4 py-2.5 text-[13px] transition hover:border-white/20"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="add-offer-submit"
              disabled={submitting}
              aria-busy={submitting}
              className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-[13px] font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className="fa-solid fa-plus" aria-hidden="true" />
              {submitting ? "Saving…" : "Add offer"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
