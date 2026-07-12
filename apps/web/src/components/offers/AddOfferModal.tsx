/**
 * AddOfferModal — accessible dialog to add an offer to the comparison
 * (interactivity for add-offer-of05 / empty-add-offer-of16). Validated form;
 * on submit appends a new offer card. Closable via ✕, Cancel, backdrop, Escape.
 */
import { useEffect, useId, useRef, useState } from "react";

import {
  emptyDraft,
  money,
  validateOfferDraft,
  type DraftErrors,
  type OfferDraft,
  type UiOffer,
} from "./offers-lib";

interface Props {
  open: boolean;
  onClose: () => void;
  onAdd: (offer: UiOffer) => void;
}

const NUMERIC_FIELDS: Array<keyof OfferDraft> = ["base", "bonus", "equity"];

export function AddOfferModal({ open, onClose, onAdd }: Props) {
  const [draft, setDraft] = useState<OfferDraft>(emptyDraft);
  const [errors, setErrors] = useState<DraftErrors>({});
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const addCounter = useRef(0);

  // Reset the form each time the modal opens, and move focus into the dialog.
  useEffect(() => {
    if (!open) return;
    setDraft(emptyDraft());
    setErrors({});
    const t = setTimeout(() => firstFieldRef.current?.focus(), 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const setField = (key: keyof OfferDraft) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setDraft((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => (prev[key] ? { ...prev, [key]: undefined } : prev));
  };

  const previewTotal =
    [draft.base, draft.bonus, draft.equity]
      .map((v) => Number(v.replace(/[$,\s]/g, "")) || 0)
      .reduce((a, b) => a + b, 0) || 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    addCounter.current += 1;
    const result = validateOfferDraft(draft, String(addCounter.current));
    if (!result.ok || !result.offer) {
      setErrors(result.errors);
      // focus the first invalid field
      const firstBad = (["company", "base", "location", "bonus", "equity"] as Array<keyof OfferDraft>).find(
        (k) => result.errors[k],
      );
      if (firstBad) {
        const el = dialogRef.current?.querySelector<HTMLInputElement>(`[name="${firstBad}"]`);
        el?.focus();
      }
      return;
    }
    onAdd(result.offer);
    onClose();
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

  return (
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
          {field("location", "Location", { required: true, placeholder: "e.g. Sydney · Hybrid" })}

          <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-[12px]">
            <span className="text-aether-muted-dim">Total comp / yr</span>
            <span className="mono font-semibold text-white" data-testid="add-offer-total">
              {money(previewTotal)}
            </span>
          </div>

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
              className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-[13px] font-semibold text-white transition hover:opacity-90"
            >
              <i className="fa-solid fa-plus" aria-hidden="true" />
              Add offer
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
