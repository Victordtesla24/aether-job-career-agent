"use client";

/**
 * SETUP-1 — the first-run interstitial on /dashboard.
 *
 * Signup still lands here (existing contract). The screening answers live in
 * Settings, next to the résumé and the profile links, which a new subscriber
 * has no reason to open until something tells them why. This card is that
 * something: it states how far the Answer Bank can already act, and it links
 * to Settings, where the résumé, career links, and screening answers sit
 * together on the Profile tab. Returning users who only need the answers
 * still have Settings → Screening Answers via the sub-nav.
 *
 * A failed check is reported as a failed check. It must never render as
 * "0 answers saved" — that fact belongs to a successful empty-bank read, and
 * showing it for an outage would tell a fully set-up user to start over.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchAnswerBankReadiness,
  type AnswerBankReadiness,
} from "../../lib/api/answer-bank";

const SETTINGS_HREF = "/dashboard/settings";

export default function ScreeningSetupPrompt() {
  const [readiness, setReadiness] = useState<AnswerBankReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAnswerBankReadiness()
      .then((value) => {
        if (cancelled) return;
        setReadiness(value);
        setError(null);
      })
      .catch(() => {
        if (cancelled) return;
        setReadiness(null);
        setError("Couldn't check your screening answers. Open Settings to add them.");
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!checked) return null;
  if (readiness?.setupComplete) return null;

  const headline =
    readiness === null
      ? null
      : readiness.essentialCovered === 0
        ? `None of the ${readiness.essentialTotal} reusable answers are saved yet. Until they are, an application that asks one will stop and wait for you.`
        : `${readiness.essentialCovered} of ${readiness.essentialTotal} reusable answers saved. Until the rest are answered, an application that asks one will stop and wait for you.`;

  return (
    <section
      data-testid="screening-setup-prompt"
      className="elev-1 relative overflow-hidden rounded-[14px] p-5 before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-aether-coral/60 before:via-aether-coral/10 before:to-transparent"
    >
      <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
            Set-up
          </p>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
            Answer the questions applications will ask
          </h2>
          <p className="mt-0.5 text-[13px] leading-[1.5] text-aether-muted">
            Application forms ask things your résumé cannot answer — work rights, notice
            period, start date. Aether sends only the words you type, never a guess.
          </p>
        </div>
        <Link
          href={SETTINGS_HREF}
          data-testid="screening-setup-cta"
          className="shrink-0 rounded-lg bg-aether-coral px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90"
        >
          Answer screening questions
        </Link>
      </header>
      {error ? (
        <p
          data-testid="screening-setup-error"
          role="status"
          className="text-[13px] leading-[1.5] text-state-warn"
        >
          {error}
        </p>
      ) : headline ? (
        <p data-testid="screening-setup-headline" className="text-[13px] text-aether-text">
          {headline}
        </p>
      ) : null}
    </section>
  );
}
