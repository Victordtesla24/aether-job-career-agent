"use client";

/**
 * RESUME STUDIO — the aha moment.
 *
 * This is the screen the whole onboarding funnel aims at: what a subscriber
 * sees minutes after their first tailoring run. Its job is to make the value
 * visceral WITHOUT making one claim the machinery did not measure, so every
 * element below is wired to a specific measurement and refuses to render when
 * that measurement is missing:
 *
 * | element              | source                                        | when absent |
 * |----------------------|-----------------------------------------------|-------------|
 * | job line             | `GET /resumes/{id}/tailoring-impact` job/company | the line is dropped |
 * | before / after ATS   | the same call's `before.ats` / `after.ats`     | `—` + the API's own `unmeasuredReason` |
 * | delta                | after − before, both measured                 | "not measured", never a subtraction against a placeholder |
 * | verified chip        | `GET /resumes/{id}/fidelity` counts            | a neutral "not verified" chip — never a green one |
 * | evidence claim       | the diff's own `evidenceRef` coverage          | the exact covered/total count instead of the absolute claim |
 *
 * D-β: the only motion is a one-shot entrance and a one-shot count-up on the
 * two scores, both suppressed under `prefers-reduced-motion`, and the count-up
 * runs ONLY when both halves are real measurements (M2 — an unmeasured→measured
 * transition must never draw a trajectory that was never taken).
 */
import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { chip } from "../ui/recipes";

export interface AhaHeroProps {
  jobTitle: string | null;
  company: string | null;
  /** Measured baseline ATS, or `null` when the API withheld it. */
  beforeAts: number | null;
  /** Measured tailored ATS, or `null` when the API withheld it. */
  afterAts: number | null;
  /** The API's own words for why a half is absent. */
  unmeasuredReason: string | null;
  /** Verified-fidelity counts from `GET /resumes/{id}/fidelity`. */
  changesRequested: number | null;
  changesApplied: number | null;
  changesDropped: number | null;
  /** How many diff changes carry an `evidenceRef`, and how many exist. */
  evidenceCovered: number;
  evidenceTotal: number;
  /** The version this hero describes, for the eyebrow. */
  versionLabel: string;
  /**
   * True while the per-version reads are still open.
   *
   * Load-bearing honesty flag, not a spinner: with every measurement still
   * `null`, this hero would otherwise print "not measured" and a neutral
   * verification chip for a beat — a false negative claim about the user's own
   * resume, made before we had even asked. M7: the skeleton stands at the
   * final geometry instead, so nothing is claimed and nothing shifts.
   */
  loading?: boolean;
}

/** `+4` / `-2` / `±0` — the sign is always explicit; zero is never blank. */
function formatDelta(delta: number): string {
  if (delta === 0) return "±0";
  return delta > 0 ? `+${delta}` : `${delta}`;
}

/**
 * One big score numeral. Counts up on mount only when it is a real
 * measurement AND motion is allowed; otherwise it is simply printed.
 */
function Score({
  value,
  label,
  tone,
  testId,
}: {
  value: number | null;
  label: string;
  tone: "before" | "after";
  testId: string;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<number | null>(value);
  const started = useRef(false);

  useEffect(() => {
    if (value === null || reduced || started.current) {
      setShown(value);
      return;
    }
    started.current = true;
    const controls = animate(0, value, {
      duration: 0.6,
      ease: [0.2, 0, 0, 1],
      onUpdate: (v) => setShown(Math.round(v)),
    });
    return () => controls.stop();
  }, [value, reduced]);

  return (
    <div className="min-w-0">
      <p
        data-testid={testId}
        className={`mono text-[44px] font-bold leading-none tracking-[-0.03em] sm:text-[56px] ${
          value === null
            ? "text-state-neutral"
            : tone === "after"
              ? "bg-gradient-to-br from-aether-coral to-aether-amber bg-clip-text text-transparent"
              : "text-aether-muted-dim"
        }`}
      >
        {shown === null ? "—" : shown}
      </p>
      <p className="type-section mt-2">{label}</p>
    </div>
  );
}

export default function AhaHero({
  jobTitle,
  company,
  beforeAts,
  afterAts,
  unmeasuredReason,
  changesRequested,
  changesApplied,
  changesDropped,
  evidenceCovered,
  evidenceTotal,
  versionLabel,
  loading = false,
}: AhaHeroProps) {
  const measured = beforeAts !== null && afterAts !== null;
  const delta = measured ? (afterAts as number) - (beforeAts as number) : null;
  // AUD-TAILOR-1: "measurably better" is a betterment claim — it may render
  // ONLY when there is a measured, strictly positive delta. Zero or negative
  // deltas (both real, reproduced outcomes — see
  // docs/delivery/evidence/RUN-20260818T0223Z/AUD-TAILOR-1/01-scout-reproduction.log)
  // and the unmeasured case all fall back to an honest, non-comparative headline.
  const claimsBetterment = delta !== null && delta > 0;

  // The verified chip is gated on the API's counts EXACTLY: a report with a
  // real request count and nothing dropped is the only thing that earns green.
  const hasCounts = typeof changesRequested === "number" && changesRequested > 0;
  const dropped = changesDropped ?? 0;
  const verified: { tone: "ok" | "warn" | "neutral"; text: string } = hasCounts
    ? dropped > 0
      ? {
          tone: "warn",
          text: `${changesApplied ?? 0} of ${changesRequested} changes verified in the file`,
        }
      : {
          tone: "ok",
          text: `Verified · all ${changesRequested} changes present in the file you download`,
        }
    : { tone: "neutral", text: "File-level verification not available for this version" };

  if (loading) {
    return (
      <section
        data-testid="aha-hero"
        data-state="loading"
        aria-busy="true"
        className="elev-1 relative overflow-hidden rounded-2xl px-5 py-6 sm:px-7 sm:py-8"
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-24 -top-32 h-[420px] w-[620px] rounded-full opacity-70"
          style={{
            background:
              "radial-gradient(ellipse at 32% 42%, rgba(255,107,53,0.14), transparent 62%)",
          }}
        />
        <div className="relative">
          <div className="h-[17px] w-[46%] max-w-[420px] animate-pulse rounded bg-white/[0.07]" />
          <div className="mt-3 h-[38px] w-[62%] max-w-[520px] animate-pulse rounded bg-white/[0.07] sm:h-[46px]" />
          <div className="mt-2 h-[21px] w-[74%] max-w-[600px] animate-pulse rounded bg-white/[0.05]" />
          <div className="mt-6 flex flex-wrap items-end gap-x-7 gap-y-4">
            {[0, 1].map((i) => (
              <div key={i} className="min-w-0">
                <div className="h-[44px] w-[92px] animate-pulse rounded bg-white/[0.07] sm:h-[56px] sm:w-[112px]" />
                <div className="mt-2 h-[12px] w-[104px] animate-pulse rounded bg-white/[0.05]" />
              </div>
            ))}
            <div className="pb-1">
              <div className="h-[28px] w-[104px] animate-pulse rounded-full bg-white/[0.05]" />
              <div className="mt-2 h-[30px] w-[200px] animate-pulse rounded bg-white/[0.04]" />
            </div>
          </div>
          <div className="mt-6 border-t border-hairline pt-4">
            <div className="h-[22px] w-[320px] max-w-full animate-pulse rounded-md bg-white/[0.05]" />
          </div>
          <span className="sr-only">Measuring this version — scores and verification pending.</span>
        </div>
      </section>
    );
  }

  return (
    <section
      data-testid="aha-hero"
      aria-labelledby="aha-hero-title"
      className="elev-1 relative overflow-hidden rounded-2xl px-5 py-6 sm:px-7 sm:py-8"
    >
      {/* Background depth — one coral radial off the brand hue, no data claim. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 -top-32 h-[420px] w-[620px] rounded-full opacity-70"
        style={{
          background:
            "radial-gradient(ellipse at 32% 42%, rgba(255,107,53,0.14), transparent 62%)",
        }}
      />
      <div className="relative">
        <p className="type-meta flex flex-wrap items-baseline gap-x-1.5" data-testid="aha-job-line">
          {jobTitle ? (
            <>
              <span>Tailored for</span>
              <b className="font-semibold text-aether-text">{jobTitle}</b>
              {company ? <span className="text-aether-muted">· {company}</span> : null}
            </>
          ) : (
            <span>{versionLabel}</span>
          )}
        </p>

        <h2
          id="aha-hero-title"
          className="mt-2 max-w-[26ch] text-[26px] font-semibold leading-[1.15] tracking-[-0.022em] sm:text-[32px]"
        >
          Your resume,{" "}
          <span className="bg-gradient-to-r from-aether-coral to-aether-amber bg-clip-text text-transparent">
            {claimsBetterment ? "measurably better." : "rewritten on your evidence."}
          </span>
        </h2>
        <p className="mt-2 max-w-[62ch] text-[13px] leading-[1.6] text-aether-muted">
          {evidenceTotal > 0 && evidenceCovered === evidenceTotal
            ? "Every rewritten line below traces back to evidence in your base resume."
            : evidenceTotal > 0
              ? `${evidenceCovered} of ${evidenceTotal} rewritten lines carry an evidence reference back to your base resume.`
              : "Select a tailored version to trace its changes to evidence."}
        </p>
        <p
          data-testid="aha-hero-honesty-note"
          className="type-meta mt-1 max-w-[62ch] text-aether-muted-dim"
        >
          Tailoring rewrites your resume using evidence from your own work history. It never
          invents experience or fabricates metrics, and it does not stuff keywords — typical
          score lift is modest, not guaranteed.
        </p>

        <div className="mt-6 flex flex-wrap items-end gap-x-7 gap-y-4">
          <Score value={beforeAts} label="ATS · baseline" tone="before" testId="aha-ats-before" />
          <span
            aria-hidden="true"
            className="pb-6 text-2xl leading-none text-aether-coral"
          >
            &rarr;
          </span>
          <Score value={afterAts} label="ATS · this version" tone="after" testId="aha-ats-after" />
          <div className="pb-1">
            <span
              data-testid="aha-ats-delta"
              className={`mono inline-flex items-center rounded-full border px-3 py-1 text-[13px] font-semibold ${
                delta === null
                  ? "border-hairline text-state-neutral"
                  : delta > 0
                    ? "border-state-ok/35 text-state-ok"
                    : delta < 0
                      ? "border-state-danger/35 text-state-danger"
                      : "border-hairline text-aether-muted-dim"
              }`}
            >
              {delta === null ? "not measured" : formatDelta(delta)}
            </span>
            <p className="type-meta mt-2 max-w-[30ch]">
              {measured
                ? "Both scores come from one engine scoring against this posting — not an estimate."
                : `Not measured${unmeasuredReason ? ` — ${unmeasuredReason}` : "."} We show a dash rather than a score that was never taken.`}
            </p>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-hairline pt-4">
          <span data-testid="aha-verified-chip" className={chip({ tone: verified.tone })}>
            <i
              className={`fa-solid ${
                verified.tone === "ok"
                  ? "fa-circle-check"
                  : verified.tone === "warn"
                    ? "fa-triangle-exclamation"
                    : "fa-circle-minus"
              }`}
              aria-hidden="true"
            />
            {verified.text}
          </span>
        </div>
      </div>
    </section>
  );
}
