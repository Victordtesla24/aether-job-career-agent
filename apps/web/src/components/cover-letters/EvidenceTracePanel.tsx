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
      className="elev-1 rounded-2xl border-state-ok/25 p-5"
      data-testid="evidence-trace-panel"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-link text-sm text-state-ok" aria-hidden="true" />
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Evidence Trace</h2>
        </div>
        <Link
          href="/dashboard/stories"
          className="inline-flex min-h-[44px] items-center gap-1.5 text-[11px] font-medium text-state-info transition hover:text-white"
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
        /*
         * U-STORY-1 citations, rendered as a citation LIST rather than one
         * run-on line: the claim the guard matched, then the Story Bank entry
         * that backs it. Both states keep their exact previous words — a
         * grounded row still says "Story: <title>", an ungrounded one still
         * says "no source yet — add or soften" — because those strings are the
         * honesty contract; only their typography changed.
         */
        <ul className="space-y-1.5">
          {evidence.map((row) => (
            <li
              key={row.claim}
              className={`rounded-lg border px-2.5 py-2 text-[11px] leading-[1.5] ${
                row.grounded
                  ? "border-state-ok/20 bg-state-ok/[0.06]"
                  : "border-state-warn/20 bg-state-warn/[0.06]"
              }`}
              data-testid={row.grounded ? "evidence-grounded" : "evidence-ungrounded"}
            >
              <span className="flex items-start gap-2">
                <i
                  className={
                    row.grounded
                      ? "fa-solid fa-circle-check mt-0.5 text-state-ok"
                      : "fa-solid fa-triangle-exclamation mt-0.5 text-state-warn"
                  }
                  aria-hidden="true"
                />
                <span className="min-w-0 text-aether-muted">
                  “{row.claim}” →{" "}
                  {row.grounded ? (
                    <span className="font-medium text-white">Story: {row.storyTitle}</span>
                  ) : (
                    <span className="text-state-warn">no source yet — add or soften</span>
                  )}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
