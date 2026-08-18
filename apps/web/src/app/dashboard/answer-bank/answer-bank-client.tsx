"use client";

/**
 * /dashboard/answer-bank — the Answer Bank, first-class and user-owned.
 *
 * ADR-SUB-AUTON-1 Pillar 1: *"USER-VISIBLE: Answer Bank is a first-class UI
 * surface (view/edit/expire/delete every answer; see where each was used)."*
 *
 * TWO SURFACES, ONE PAGE:
 *
 * 1. **Set-up questionnaire** — the common screening questions ATS platforms
 *    ask, so the bank can be seeded BEFORE the first application waits on the
 *    user. Every field starts empty; skipping a question is a valid answer and
 *    banks nothing.
 * 2. **The bank itself** — every stored answer with its provenance, its class,
 *    its staleness, whether Aether will send it without asking (and, when it
 *    will not, WHY), and the recorded audit of where it has actually been used.
 *
 * THE PAGE NEVER DECIDES ANYTHING. `autoAnswers`, `gateReason`, `expired` and
 * the usage list are all server-computed facts; this component renders them.
 * The one thing the user can change here is their own data — the answer text,
 * the judgement-class opt-in, expiry and deletion — and a sensitive answer's
 * opt-in is refused by the server and REPORTED here, never hidden.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import ScreeningQuestionnaire from "../../../components/answer-bank/ScreeningQuestionnaire";
import {
  PROVENANCE_LABELS,
  SENSITIVITY_LABELS,
  deleteAnswer,
  expireAnswer,
  fetchAnswerBank,
  updateAnswer,
  type AnswerBankItem,
} from "../../../lib/api/answer-bank";
import {
  BANK_FILTERS,
  applyFilter,
  confidencePercent,
  statusLabel,
  statusTone,
  summarise,
  usageSummary,
  type BankFilter,
} from "./answer-bank-lib";

function Stat({ label, value, tone = "" }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <p className={`text-lg font-semibold leading-none ${tone}`}>{value}</p>
      <p className="mono mt-1 text-[10px] uppercase tracking-[0.08em] text-aether-muted-dim">
        {label}
      </p>
    </div>
  );
}

function SensitivityChip({ sensitivity }: { sensitivity: string }) {
  const tone =
    sensitivity === "sensitive"
      ? "border-aether-coral/40 text-aether-coral"
      : sensitivity === "judgment"
        ? "border-aether-yellow/40 text-aether-yellow"
        : "border-aether-green/40 text-aether-green";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] ${tone}`}>
      {SENSITIVITY_LABELS[sensitivity] ?? sensitivity}
    </span>
  );
}

function ItemRow({
  item,
  onChanged,
  onRemoved,
}: {
  item: AnswerBankItem;
  onChanged: (next: AnswerBankItem) => void;
  onRemoved: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.answer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const run = useCallback(
    async (work: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await work();
      } catch (err) {
        setError(err instanceof Error ? err.message : "That change did not save.");
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return (
    <li
      data-testid={`bank-item-${item.id}`}
      className="rounded-xl border border-white/10 bg-white/[0.02] p-3.5"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        {/* `basis-full` below `sm` is load-bearing, not decoration: with
            `flex-1` alone (basis 0) this column never forces the row to wrap,
            so on a 390px screen the four action buttons keep their width and
            squeeze the question down to one word per line. Taking the whole
            line on mobile puts the actions on their own row underneath. */}
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <p className="text-[13px] font-medium leading-snug text-white">{item.questionText}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <SensitivityChip sensitivity={item.sensitivity} />
            <span
              data-testid={`bank-status-${item.id}`}
              className={`text-[10px] ${statusTone(item)}`}
            >
              {statusLabel(item)}
            </span>
            {item.scope !== "global" ? (
              <span className="rounded border border-white/15 px-1.5 py-0.5 text-[10px] text-aether-muted">
                {item.scope === "company" ? `Only for ${item.scopeValue}` : item.scope}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {item.canOptIn && !item.expired ? (
            <button
              type="button"
              data-testid={`bank-optin-${item.id}`}
              disabled={busy}
              onClick={() =>
                run(async () =>
                  onChanged(
                    await updateAnswer(item.id, { autoAnswerOptIn: !item.autoAnswerOptIn }),
                  ),
                )
              }
              className={`rounded-md border px-2 py-0.5 text-[10px] transition disabled:opacity-50 ${
                item.autoAnswers
                  ? "border-aether-green/40 text-aether-green hover:text-white"
                  : "border-white/15 text-aether-muted hover:border-white/30 hover:text-white"
              }`}
            >
              {item.autoAnswers ? "Answering for you" : "Let Aether answer this"}
            </button>
          ) : null}
          <button
            type="button"
            data-testid={`bank-edit-${item.id}`}
            onClick={() => {
              setDraft(item.answer);
              setEditing((prev) => !prev);
            }}
            className="rounded-md border border-white/15 px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-white/30 hover:text-white"
          >
            {editing ? "Cancel" : "Edit"}
          </button>
          {!item.expired ? (
            <button
              type="button"
              data-testid={`bank-expire-${item.id}`}
              disabled={busy}
              onClick={() => run(async () => onChanged(await expireAnswer(item.id)))}
              className="rounded-md border border-white/15 px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-aether-yellow/40 hover:text-aether-yellow disabled:opacity-50"
            >
              Retire
            </button>
          ) : null}
          <button
            type="button"
            data-testid={`bank-delete-${item.id}`}
            disabled={busy}
            onClick={() =>
              run(async () => {
                await deleteAnswer(item.id);
                onRemoved(item.id);
              })
            }
            className="rounded-md border border-white/15 px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-red-500/40 hover:text-red-300 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>

      {editing ? (
        <div className="mt-2">
          <textarea
            data-testid={`bank-answer-input-${item.id}`}
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full rounded-md border border-white/15 bg-black/30 px-2 py-1.5 text-[12px] text-white focus:border-[#818CF8]/60 focus:outline-none"
          />
          <button
            type="button"
            data-testid={`bank-save-${item.id}`}
            disabled={busy || !draft.trim()}
            onClick={() =>
              run(async () => {
                onChanged(await updateAnswer(item.id, { answer: draft.trim() }));
                setEditing(false);
              })
            }
            className="mt-1.5 rounded-md border border-[#818CF8]/50 px-2 py-0.5 text-[10px] text-[#818CF8] transition hover:text-white disabled:opacity-50"
          >
            Save answer
          </button>
        </div>
      ) : (
        <p
          data-testid={`bank-answer-${item.id}`}
          className="mt-2 whitespace-pre-wrap rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[12px] leading-relaxed text-aether-muted"
        >
          {item.answer}
        </p>
      )}

      <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-aether-muted-dim">
        <i className="fa-solid fa-circle-info mt-[3px] shrink-0 text-[9px]" aria-hidden="true" />
        <span>{item.gateReason}</span>
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-aether-muted-dim">
        <span data-testid={`bank-provenance-${item.id}`}>
          {PROVENANCE_LABELS[item.provenance] ?? item.provenance}
        </span>
        <span aria-hidden="true">·</span>
        <span data-testid={`bank-usage-${item.id}`}>{usageSummary(item)}</span>
        {item.staleDays ? (
          <>
            <span aria-hidden="true">·</span>
            <span>Re-confirmed every {item.staleDays} days</span>
          </>
        ) : null}
        {item.usedOn.length > 0 ? (
          <button
            type="button"
            data-testid={`bank-usage-toggle-${item.id}`}
            onClick={() => setExpanded((prev) => !prev)}
            className="text-[10px] text-[#818CF8] transition hover:text-white"
          >
            {expanded ? "Hide where it was used" : "Where it was used"}
          </button>
        ) : null}
      </div>

      {expanded ? (
        <ul
          data-testid={`bank-usage-list-${item.id}`}
          className="mt-2 space-y-1 border-t border-white/10 pt-2"
        >
          {item.usedOn.map((use, index) => (
            <li key={`${use.applicationId}-${index}`} className="text-[10px] text-aether-muted">
              <span className="text-white">“{use.questionAsSeen}”</span>{" "}
              <span className="mono text-aether-muted-dim">
                {confidencePercent(use.matchConfidence)}% match · {use.matchMethod}
              </span>
              {use.applicationId ? (
                <>
                  {" · "}
                  <Link
                    href={`/dashboard/applications?application=${use.applicationId}`}
                    className="text-[#818CF8] transition hover:text-white"
                  >
                    application
                  </Link>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {error ? <p className="mt-1.5 text-[10px] text-red-300">{error}</p> : null}
    </li>
  );
}

export default function AnswerBankClient() {
  const [items, setItems] = useState<AnswerBankItem[]>([]);
  const [filter, setFilter] = useState<BankFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openQuestionnaire, setOpenQuestionnaire] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const bank = await fetchAnswerBank();
      setItems(bank.items);
      // The set-up panel opens by itself only while the bank is genuinely
      // empty — once the user has answers, it is a thing they choose to open.
      if (bank.items.length === 0) setOpenQuestionnaire(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The Answer Bank could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => summarise(items), [items]);
  const visible = useMemo(() => applyFilter(items, filter), [items, filter]);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">Answer Bank</h1>
          <p className="mono mt-1 text-xs text-aether-muted-dim" data-testid="bank-subtitle">
            {summary.total} saved answer{summary.total === 1 ? "" : "s"} ·{" "}
            {summary.automatic} sent automatically · {summary.gated} ask you first
          </p>
        </div>
        <Link
          href="/dashboard/applications"
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-aether-muted transition hover:bg-white/10 hover:text-white"
        >
          <i className="fa-solid fa-arrow-left mr-1.5 text-[10px]" aria-hidden="true" />
          Applications
        </Link>
      </header>

      <div
        className="flex items-start gap-3 rounded-xl border border-aether-green/25 bg-aether-green/[0.06] px-4 py-3"
        data-testid="bank-honesty-banner"
      >
        <i className="fa-solid fa-shield-halved mt-0.5 text-aether-green" aria-hidden="true" />
        <p className="text-xs leading-relaxed text-aether-muted">
          <span className="font-semibold text-aether-green">
            Aether only ever sends answers you wrote.
          </span>{" "}
          It never invents one. A question it has no confident, current answer for comes back
          to you on the application card — and sensitive or legal questions (background checks,
          diversity disclosures, visa specifics) are asked every single time, whatever is
          saved here.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="bank-stats">
        <Stat label="Saved answers" value={summary.total} />
        <Stat label="Sent automatically" value={summary.automatic} tone="text-aether-green" />
        <Stat label="Ask you first" value={summary.gated} tone="text-aether-yellow" />
        <Stat label="Times used" value={summary.timesUsed} />
      </div>

      {/* ---- Set-up questionnaire -------------------------------------
          One shared component with the Settings → Screening Answers panel
          (`components/answer-bank/ScreeningQuestionnaire`). It owns its own
          fetch and save; this page only tells it whether to start expanded
          (it does while the bank is genuinely empty) and refreshes the list
          below once answers are banked. */}
      <section className="rounded-[14px] border border-white/10 bg-white/[0.02] p-5">
        <ScreeningQuestionnaire defaultOpen={openQuestionnaire} onSaved={() => void load()} />
      </section>

      {/* ---- The bank -------------------------------------------------- */}
      <section className="rounded-[14px] border border-white/10 bg-white/[0.02] p-5">
        <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <p className="mono text-[10px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
              Your answers
            </p>
            <h2 className="text-[15px] font-semibold">Everything Aether has saved</h2>
          </div>
          <div className="flex flex-wrap rounded-lg border border-white/10 bg-white/5 p-0.5">
            {BANK_FILTERS.map((option) => (
              <button
                key={option.key}
                type="button"
                data-testid={`bank-filter-${option.key}`}
                onClick={() => setFilter(option.key)}
                className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition ${
                  filter === option.key
                    ? "bg-aether-coral/15 text-aether-coral"
                    : "text-aether-muted hover:text-white"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </header>

        {error ? (
          <p data-testid="bank-error" className="text-[12px] text-red-300">
            {error}
          </p>
        ) : loading ? (
          <p className="text-[12px] text-aether-muted-dim">Loading your answers…</p>
        ) : visible.length === 0 ? (
          <p data-testid="bank-empty" className="text-[12px] leading-relaxed text-aether-muted">
            {items.length === 0
              ? "Nothing saved yet. Answer the set-up questions above, or answer a question on an application card — Aether banks it either way."
              : "No answers in this view."}
          </p>
        ) : (
          <ul className="space-y-2.5" data-testid="bank-list">
            {visible.map((item) => (
              <ItemRow
                key={item.id}
                item={item}
                onChanged={(next) =>
                  setItems((prev) => prev.map((row) => (row.id === next.id ? next : row)))
                }
                onRemoved={(id) => setItems((prev) => prev.filter((row) => row.id !== id))}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
