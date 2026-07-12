/** Versions panel (wireframe cl14–cl16): per-job version chain, current marked. */
import type { LetterInsights } from "./api";

export function VersionsPanel({
  versions,
  selectedId,
  loading,
  onSelect,
}: {
  versions: LetterInsights["versions"] | null;
  selectedId: string | null;
  loading: boolean;
  onSelect: (letterId: string) => void;
}) {
  return (
    <section className="glass rounded-2xl border border-white/10 p-5" data-testid="versions-panel">
      <div className="mb-3 flex items-center gap-2">
        <i className="fa-solid fa-clock-rotate-left text-sm text-aether-violet" aria-hidden="true" />
        <h2 className="text-sm font-semibold">Versions</h2>
      </div>
      {loading ? (
        <div className="flex gap-2" aria-busy="true">
          {[0, 1].map((i) => (
            <div key={i} className="h-8 w-14 animate-pulse rounded-lg bg-white/5" />
          ))}
        </div>
      ) : !versions || versions.length === 0 ? (
        <p className="text-[11px] text-aether-muted-dim">No versions yet.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {versions.map((v) => {
            const active = v.id === selectedId;
            return (
              <button
                key={v.id}
                type="button"
                data-testid={`version-btn-v${v.version}`}
                aria-pressed={active}
                onClick={() => onSelect(v.id)}
                className={
                  active
                    ? "mono min-h-[44px] rounded-lg border border-aether-coral/25 bg-aether-coral/15 px-3 py-1.5 text-[11px] font-semibold text-aether-coral"
                    : "mono min-h-[44px] rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium transition hover:bg-white/10"
                }
              >
                v{v.version}
                {v.current ? " · current" : ""}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
