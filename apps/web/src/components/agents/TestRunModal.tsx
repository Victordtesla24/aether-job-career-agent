"use client";

/**
 * Test Run modal (wireframe: test-run-ag17). An accessible dialog that dry-runs
 * a single agent and previews its estimated cost via POST /agents/test-run
 * (no credits charged). Focus is trapped while open, Escape/backdrop/✕/Cancel
 * all close it, and focus returns to the trigger on close.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { runTestRun, type CatalogAgent, type TestRunResult } from "./api";

export default function TestRunModal({
  open,
  agents,
  onClose,
}: {
  open: boolean;
  agents: CatalogAgent[];
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const [selected, setSelected] = useState<string>("");
  const [result, setResult] = useState<TestRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = useMemo(() => agents.filter((a) => a.enabled), [agents]);
  const current = agents.find((a) => a.key === selected) ?? options[0] ?? null;

  // Reset local state whenever the modal opens; default to the first agent.
  useEffect(() => {
    if (open) {
      setSelected((prev) => (prev && agents.some((a) => a.key === prev) ? prev : options[0]?.key ?? ""));
      setResult(null);
      setError(null);
    }
  }, [open, agents, options]);

  // Move focus into the dialog when it opens, and restore it on close.
  const triggerRef = useRef<Element | null>(null);
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement;
      const t = setTimeout(() => selectRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
    if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
    return undefined;
  }, [open]);

  // Document-level Escape so the dialog closes regardless of where focus sits.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], select, input, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose],
  );

  const run = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const res = await runTestRun(current.key);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 140) : "Dry-run failed");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      data-testid="test-run-modal"
      onKeyDown={handleKey}
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        data-testid="test-run-backdrop"
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="test-run-title"
        className="glass-raised relative w-full max-w-lg rounded-2xl border border-aether-coral/40 p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-aether-indigo/15">
              <i className="fa-solid fa-vial text-sm text-aether-indigo" aria-hidden="true" />
            </div>
            <div>
              <h3 id="test-run-title" className="text-sm font-semibold">
                Test Run — Single Agent
              </h3>
              <p className="text-[11px] text-aether-muted-dim">
                Dry-run one agent and preview its estimated cost before spending credits.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="test-run-close"
            aria-label="Close test run dialog"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/5 transition hover:bg-white/10"
          >
            <i className="fa-solid fa-xmark text-xs text-aether-muted" aria-hidden="true" />
          </button>
        </div>

        <label
          htmlFor="test-agent-select"
          className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
        >
          Select agent
        </label>
        <select
          id="test-agent-select"
          ref={selectRef}
          data-testid="test-run-select"
          value={current?.key ?? ""}
          onChange={(e) => {
            setSelected(e.target.value);
            setResult(null);
          }}
          className="mb-4 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-xs text-white outline-none focus:border-aether-coral/50 [&>option]:bg-aether-bg"
        >
          {options.map((a) => (
            <option key={a.key} value={a.key}>
              {a.name} · {a.model}
            </option>
          ))}
        </select>

        <div className="mb-4 grid grid-cols-3 gap-3">
          <div className="glass rounded-xl border border-white/10 p-3">
            <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">Model</p>
            <p
              className="mt-1 truncate font-mono text-[11px] font-semibold text-aether-indigo"
              data-testid="test-run-model"
            >
              {current?.model ?? "—"}
            </p>
          </div>
          <div className="glass rounded-xl border border-white/10 p-3">
            <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">Est. tokens</p>
            <p className="mt-1 font-mono text-[11px] font-semibold" data-testid="test-run-tokens">
              {result
                ? result.estTokens != null
                  ? `~${(result.estTokens / 1000).toFixed(1)}K`
                  : "N/A"
                : "~4.2K"}
            </p>
          </div>
          <div className="glass rounded-xl border border-aether-coral/25 p-3">
            <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">
              Est. cost / run
            </p>
            <p
              className="mt-0.5 font-mono text-sm font-bold text-aether-coral"
              data-testid="test-run-cost"
            >
              {result
                ? result.estCost != null
                  ? `~$${result.estCost.toFixed(3)}`
                  : "N/A"
                : "~$0.032"}
            </p>
          </div>
        </div>

        {result ? (
          <div
            className="mb-4 glass rounded-xl border border-aether-green/25 p-4"
            data-testid="test-run-result"
          >
            <div className="mb-1.5 flex items-center gap-2">
              <i className="fa-solid fa-circle-check text-xs text-aether-green" aria-hidden="true" />
              <p className="text-xs font-semibold text-aether-green">Dry-run complete</p>
            </div>
            <p className="text-[11px] leading-relaxed text-aether-muted">
              {result.responseSeconds != null &&
              result.actualCost != null &&
              result.actualTokens != null ? (
                <>
                  Agent responded in{" "}
                  <span className="font-mono text-white">{result.responseSeconds}s</span>. Actual
                  cost <span className="font-mono text-white">${result.actualCost.toFixed(3)}</span>{" "}
                  ·{" "}
                  <span className="font-mono text-white">
                    {result.actualTokens.toLocaleString()}
                  </span>{" "}
                  tokens. No credits were charged for this preview.
                </>
              ) : (
                <>
                  No completed run yet for this agent — actual cost/timing will appear here after
                  it has run at least once. No credits were charged for this preview.
                </>
              )}
            </p>
          </div>
        ) : null}

        {error ? (
          <p
            role="alert"
            className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
          >
            {error}
          </p>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <p className="text-[10px] leading-relaxed text-aether-muted-dim">
            Estimates use the provider&apos;s published per-token pricing.
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              data-testid="test-run-cancel"
              className="rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium transition hover:bg-white/10"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void run()}
              disabled={busy || !current}
              data-testid="test-run-go"
              className="flex items-center gap-2 rounded-lg bg-aether-coral px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:opacity-90 disabled:opacity-50"
            >
              <i className="fa-solid fa-play text-[10px]" aria-hidden="true" />
              {busy ? "Running…" : "Run Test"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
