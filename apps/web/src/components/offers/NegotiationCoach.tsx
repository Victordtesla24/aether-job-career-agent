/**
 * NegotiationCoach — payload-driven coaching panel (wireframe: negotiation-of12).
 * Insight callout, suggested counter, leverage list, and a Draft-counter-email
 * toggle that reveals a pre-filled draft referencing the suggested counter.
 */
import { useState } from "react";

export interface Negotiation {
  insight: string;
  suggestedCounter: number;
  leverage: string[];
}

export function NegotiationCoach({ negotiation }: { negotiation: Negotiation }) {
  const [showDraft, setShowDraft] = useState(false);
  const counter = negotiation.suggestedCounter;

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="negotiation-coach"
    >
      <div className="mb-3 flex items-center gap-2">
        <i className="fa-solid fa-comments-dollar text-[#34D399]" aria-hidden="true" />
        <h2 className="text-sm font-semibold">Negotiation Coach</h2>
      </div>

      <div className="mb-3 rounded-xl border border-[#34D399]/20 bg-[#34D399]/10 p-3 text-[12px] text-[#C7C7D6]">
        <i className="fa-solid fa-lightbulb mr-1 text-aether-yellow" aria-hidden="true" />
        {negotiation.insight}
      </div>

      <div className="space-y-2 text-[12px] text-[#C7C7D6]">
        <div className="flex items-baseline gap-1">
          <i className="fa-solid fa-arrow-up-right-dots mr-1 text-aether-coral" aria-hidden="true" />
          <span>Suggested counter:</span>
          <span className="mono font-semibold text-white" data-testid="suggested-counter">
            ${counter.toLocaleString()} base
          </span>
        </div>
        <ul className="space-y-1.5">
          {negotiation.leverage.map((point) => (
            <li key={point} className="flex items-start gap-2">
              <i
                className="fa-solid fa-shield-halved mt-0.5 shrink-0 text-[#818CF8]"
                aria-hidden="true"
              />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        data-testid="draft-counter-btn"
        aria-expanded={showDraft}
        aria-controls="counter-email-draft"
        onClick={() => setShowDraft((v) => !v)}
        className="mt-4 flex min-h-[44px] w-full items-center justify-center rounded-xl bg-aether-indigo px-3 py-2.5 text-xs font-semibold text-white transition hover:opacity-90"
      >
        <i className="fa-solid fa-wand-magic-sparkles mr-1" aria-hidden="true" />
        {showDraft ? "Hide counter email" : "Draft counter email"}
      </button>

      {showDraft ? (
        <p
          id="counter-email-draft"
          data-testid="counter-email-draft"
          className="mt-3 whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-3 text-[12px] text-aether-muted"
        >
          {`Hi Emma,\n\nThank you for the offer — I'm genuinely excited about the role and the team.\n\nBased on my competing offers and the market band for Senior TPMs in Sydney, I'd like to discuss a base of $${counter.toLocaleString()}. I'm confident the AI delivery experience I bring maps directly to the roadmap we discussed.\n\nHappy to jump on a call this week.\n\nBest,\n[Your Name]`}
        </p>
      ) : null}
    </section>
  );
}
