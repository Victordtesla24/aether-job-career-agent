/** Actions panel (wireframe cl10–cl13): regenerate, request changes, export, email. */
import Link from "next/link";
import { useId, useState } from "react";

import {
  changeRequestSubmitDisabled,
  changeRequestToggleDisabled,
  exportDisabled,
  regenerateDisabled,
} from "./actions";

export function ActionsPanel({
  disabled,
  regenerating,
  refining,
  exporting,
  emailHref,
  onRegenerate,
  onRequestChanges,
  onExport,
}: {
  disabled: boolean;
  regenerating: boolean;
  refining: boolean;
  exporting: boolean;
  emailHref: string;
  onRegenerate: () => void;
  onRequestChanges: (instructions: string) => Promise<boolean>;
  onExport: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const textareaId = useId();
  // `disabled` is the panel's "no letter selected" signal; hasSelection is its inverse.
  const state = {
    hasSelection: !disabled,
    regenerating,
    refining,
    exporting,
    hasInstructions: instructions.trim().length > 0,
  };

  const submit = async () => {
    if (!instructions.trim()) return;
    const ok = await onRequestChanges(instructions.trim());
    if (ok) {
      setInstructions("");
      setOpen(false);
    }
  };

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="letter-actions-panel"
    >
      <button
        type="button"
        data-testid="rail-regenerate-btn"
        onClick={onRegenerate}
        disabled={regenerateDisabled(state)}
        className="mb-2.5 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-aether-coral py-2.5 text-sm font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:opacity-90 disabled:opacity-50"
      >
        <i
          className={
            regenerating
              ? "fa-solid fa-circle-notch fa-spin text-[12px]"
              : "fa-solid fa-wand-magic-sparkles text-[12px]"
          }
          aria-hidden="true"
        />
        {regenerating ? "Regenerating…" : "Regenerate"}
      </button>
      <div className="mb-2.5 grid grid-cols-2 gap-2.5">
        <button
          type="button"
          data-testid="request-changes-btn"
          onClick={() => setOpen((v) => !v)}
          disabled={changeRequestToggleDisabled(state)}
          aria-expanded={open}
          className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 py-2.5 text-xs font-medium transition hover:bg-white/10 disabled:opacity-50"
        >
          <i className="fa-solid fa-comment-dots text-[11px] text-aether-violet" aria-hidden="true" />
          Request Changes
        </button>
        <button
          type="button"
          data-testid="export-pdf-btn"
          onClick={onExport}
          disabled={exportDisabled(state)}
          className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 py-2.5 text-xs font-medium transition hover:bg-white/10 disabled:opacity-50"
        >
          <i
            className={
              exporting
                ? "fa-solid fa-circle-notch fa-spin text-[11px] text-aether-violet"
                : "fa-solid fa-file-arrow-down text-[11px] text-aether-violet"
            }
            aria-hidden="true"
          />
          {exporting ? "Exporting…" : "Export PDF"}
        </button>
      </div>
      {open ? (
        <form
          className="mb-2.5 rounded-xl border border-white/10 bg-white/5 p-3"
          data-testid="request-changes-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label htmlFor={textareaId} className="mb-1.5 block text-[11px] text-aether-muted">
            What should the next draft change?
          </label>
          <textarea
            id={textareaId}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            maxLength={2000}
            rows={3}
            placeholder="e.g. Lead with the AI/ML delivery experience and keep it under 250 words."
            className="w-full rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs text-white placeholder:text-aether-muted-dim focus:border-aether-coral/50 focus:outline-none"
            data-testid="request-changes-input"
          />
          <button
            type="submit"
            disabled={changeRequestSubmitDisabled(state)}
            data-testid="request-changes-submit"
            className="mt-2 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg bg-aether-violet/20 py-2 text-xs font-semibold text-aether-violet transition hover:bg-aether-violet/30 disabled:opacity-50"
          >
            {refining ? (
              <>
                <i className="fa-solid fa-circle-notch fa-spin text-[11px]" aria-hidden="true" />
                Redrafting…
              </>
            ) : (
              "Submit change request"
            )}
          </button>
        </form>
      ) : null}
      <Link
        href={emailHref}
        data-testid="email-center-link"
        className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-aether-indigo/25 bg-aether-indigo/15 py-2.5 text-xs font-medium text-aether-violet transition hover:bg-aether-indigo/25"
      >
        <i className="fa-solid fa-paper-plane text-[11px]" aria-hidden="true" />
        Attach &amp; send via Email Center
        <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
      </Link>
    </section>
  );
}
