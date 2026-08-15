/** JD Keyword Coverage panel (wireframe 031–042): computed chips + X / Y score. */
import type { LetterInsights } from "./api";

export function KeywordCoveragePanel({
  keywords,
  loading,
}: {
  keywords: LetterInsights["keywords"] | null;
  loading: boolean;
}) {
  return (
    <section
      className="elev-1 rounded-[14px] p-5"
      data-testid="keyword-coverage-panel"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-list-check text-sm text-aether-coral" aria-hidden="true" />
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">JD Keyword Coverage</h2>
        </div>
        <span className="mono text-xs font-bold text-state-ok" data-testid="keyword-score">
          {keywords ? `${keywords.covered} / ${keywords.total}` : "—"}
        </span>
      </div>
      {loading ? (
        <div className="flex flex-wrap gap-1.5" aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-5 w-20 animate-pulse rounded-md bg-white/5" />
          ))}
        </div>
      ) : !keywords || keywords.items.length === 0 ? (
        <p className="text-[11px] text-aether-muted-dim">
          No job description on file for this letter’s role.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {keywords.items.map((item) => (
            <span
              key={item.keyword}
              data-testid={item.covered ? "keyword-covered" : "keyword-missing"}
              className={
                item.covered
                  ? "rounded-md border border-state-ok/20 bg-state-ok/10 px-2 py-0.5 text-[10px] text-state-ok"
                  : "rounded-md border border-state-warn/20 bg-state-warn/10 px-2 py-0.5 text-[10px] text-state-warn"
              }
            >
              {item.keyword}
              {item.covered ? "" : " (missing)"}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
