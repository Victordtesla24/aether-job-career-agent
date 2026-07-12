/** Evidence Trace panel (wireframe cl07/024–026): claim → Story Bank source. */
import Link from "next/link";

import type { EvidenceRow } from "./api";

export function EvidenceTracePanel({
  evidence,
  loading,
}: {
  evidence: EvidenceRow[] | null;
  loading: boolean;
}) {
  return (
    <section
      className="glass rounded-2xl border border-aether-green/25 p-5"
      data-testid="evidence-trace-panel"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-link text-sm text-aether-green" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Evidence Trace</h2>
        </div>
        <Link
          href="/dashboard/stories"
          className="inline-flex min-h-[44px] items-center gap-1.5 text-[11px] font-medium text-aether-violet transition hover:text-white"
          data-testid="pull-from-story-bank-link"
        >
          Pull from Story Bank
          <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
        </Link>
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-aether-muted">
        Every highlighted claim is grounded in a Story Bank entry — nothing is invented.
        Review the source before you send.
      </p>
      {loading ? (
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-white/5" />
          ))}
        </div>
      ) : !evidence || evidence.length === 0 ? (
        <p className="text-[11px] text-aether-muted-dim" data-testid="evidence-empty">
          No traceable claims found — add Story Bank entries to ground this letter.
        </p>
      ) : (
        <ul className="space-y-2">
          {evidence.map((row) => (
            <li
              key={row.claim}
              className="flex items-start gap-2 text-[11px]"
              data-testid={row.grounded ? "evidence-grounded" : "evidence-ungrounded"}
            >
              <i
                className={
                  row.grounded
                    ? "fa-solid fa-circle-check mt-0.5 text-aether-green"
                    : "fa-solid fa-triangle-exclamation mt-0.5 text-aether-yellow"
                }
                aria-hidden="true"
              />
              <span className="text-aether-muted">
                “{row.claim}” →{" "}
                {row.grounded ? (
                  <span className="text-white">Story: {row.storyTitle}</span>
                ) : (
                  <span className="text-aether-yellow">no source yet — add or soften</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
