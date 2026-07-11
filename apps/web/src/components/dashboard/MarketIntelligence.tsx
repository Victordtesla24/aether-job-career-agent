/**
 * Market Intelligence section (wireframe market-intel-mi01): demand heatmap,
 * remote-work index rings, hot sectors, salary trends, best-time-to-apply and
 * the "where to focus" recommendation. Static AU+US market snapshot content
 * per the approved wireframe — no API is prescribed for this section in the
 * component registry or traceability matrix.
 */
import Link from "next/link";

const HEATMAP: Array<{ role: string; au: number; us: number; dim?: boolean }> = [
  { role: "AI / ML Engineer", au: 88, us: 96 },
  { role: "DevOps Engineer", au: 74, us: 82 },
  { role: "Technical Program Manager", au: 68, us: 71 },
  { role: "Solutions Architect", au: 62, us: 70 },
  { role: "Scrum Master", au: 41, us: 38, dim: true },
];

const SALARY_TRENDS = [
  { role: "TPM", delta: "+6%", au: "AU $180–220K", us: "US $160–200K" },
  { role: "AI / ML Engineer", delta: "+18%", au: "AU $160–200K", us: "US $150–250K" },
  { role: "DevOps Engineer", delta: "+9%", au: "AU $150–190K", us: "US $118–174K" },
];

const HOT_SECTORS = [
  { name: "Financial Services", tier: "coral" as const, fire: true },
  { name: "Government / Defence", tier: "indigo" as const },
  { name: "Healthcare AI", tier: "indigo" as const },
  { name: "Cloud Infrastructure", tier: "neutral" as const },
  { name: "Fintech", tier: "neutral" as const },
];

const SECTOR_CLS = {
  coral: "bg-aether-coral/12 text-aether-coral border-aether-coral/25",
  indigo: "bg-aether-indigo/12 text-[#818CF8] border-aether-indigo/25",
  neutral: "bg-white/5 text-aether-muted border-white/10",
};

/** Days row for Best Time to Apply — Mon–Wed hot per the wireframe. */
const WEEK_CELLS = [
  "bg-aether-coral/70",
  "bg-aether-coral",
  "bg-aether-coral/85",
  "bg-white/10",
  "bg-white/10",
  "bg-white/5",
  "bg-white/5",
];
const WEEK_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

/** SVG ring gauge: r=15.5 → circumference 97.4. */
function Ring({ pct, stroke, caption }: { pct: number; stroke: string; caption: string }) {
  const C = 97.4;
  return (
    <div className="text-center">
      <div className="relative mx-auto h-16 w-16">
        <svg className="h-16 w-16 -rotate-90" viewBox="0 0 36 36" aria-hidden="true">
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
          <circle
            cx="18"
            cy="18"
            r="15.5"
            fill="none"
            stroke={stroke}
            strokeWidth="3"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - pct / 100)}
            strokeLinecap="round"
          />
        </svg>
        <span className="mono absolute inset-0 flex items-center justify-center text-sm font-bold">
          {pct}%
        </span>
      </div>
      <p className="mt-2 text-[11px] text-aether-muted">{caption}</p>
    </div>
  );
}

export default function MarketIntelligence() {
  return (
    <section
      className="glass relative overflow-hidden rounded-2xl border border-white/10 p-6"
      data-testid="market-intelligence"
    >
      <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-aether-indigo/[0.08] blur-3xl" />
      <div className="relative mb-6 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="live-dot h-2 w-2 rounded-full bg-aether-indigo" />
          <h2 className="text-[15px] font-semibold">Market Intelligence</h2>
          <span className="mono text-[11px] text-aether-muted-dim">
            Hiring &amp; recruitment trends · AU + US
          </span>
        </div>
        <div className="mono flex items-center gap-2 text-[11px] text-aether-muted-dim">
          <i className="fa-solid fa-circle text-[6px] text-aether-green" aria-hidden="true" />
          updated 4 min ago
        </div>
      </div>

      <div className="relative grid gap-5 lg:grid-cols-3">
        {/* Demand heatmap */}
        <div className="rounded-xl border border-white/10 bg-white/5 p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
              Demand Heatmap by Role
            </h3>
            <div className="flex items-center gap-3 text-[10px] text-aether-muted">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-aether-coral" />
                AU
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-aether-indigo" />
                US
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-3.5">
            {HEATMAP.map((r) => (
              <div
                key={r.role}
                className="grid grid-cols-[minmax(0,120px)_1fr] items-center gap-3 sm:grid-cols-[180px_1fr]"
              >
                <span className="truncate text-xs text-[#C8C8DC]">{r.role}</span>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="h-2 rounded-full bg-white/5">
                    <div
                      className={`h-2 rounded-full ${r.dim ? "bg-aether-coral/70" : "bg-aether-coral"}`}
                      style={{ width: `${r.au}%` }}
                    />
                  </div>
                  <div className="h-2 rounded-full bg-white/5">
                    <div
                      className={`h-2 rounded-full ${r.dim ? "bg-aether-indigo/70" : "bg-aether-indigo"}`}
                      style={{ width: `${r.us}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Remote index + hot sectors */}
        <div className="flex flex-col gap-5">
          <div className="rounded-xl border border-white/10 bg-white/5 p-5">
            <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
              Remote Work Index
            </h3>
            <div className="flex items-center justify-around">
              <Ring pct={35} stroke="#FF6B35" caption="🇦🇺 Australia" />
              <Ring pct={45} stroke="#4F46E5" caption="🌏 United States" />
            </div>
            <p className="mt-3 text-center text-[11px] text-aether-muted-dim">
              share of remote-friendly senior roles
            </p>
          </div>
          <div className="flex-1 rounded-xl border border-white/10 bg-white/5 p-5">
            <h3 className="mb-3.5 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
              Hot Sectors
            </h3>
            <div className="flex flex-wrap gap-2">
              {HOT_SECTORS.map((s) => (
                <span
                  key={s.name}
                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] ${SECTOR_CLS[s.tier]}`}
                >
                  {s.fire ? <i className="fa-solid fa-fire text-[9px]" aria-hidden="true" /> : null}
                  {s.name}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="relative mt-5 grid gap-5 lg:grid-cols-3">
        {/* Salary trends */}
        <div className="rounded-xl border border-white/10 bg-white/5 p-5">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Salary Trends
          </h3>
          <div className="flex flex-col gap-4">
            {SALARY_TRENDS.map((r) => (
              <div key={r.role}>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs text-[#C8C8DC]">{r.role}</span>
                  <span className="mono text-[10px] text-aether-green">
                    <i className="fa-solid fa-arrow-trend-up mr-1" aria-hidden="true" />
                    {r.delta}
                  </span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-2 text-[11px]">
                  <span className="mono text-aether-coral">{r.au}</span>
                  <span className="mono text-[#818CF8]">{r.us}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Best time to apply */}
        <div className="rounded-xl border border-aether-indigo/25 bg-white/5 p-5">
          <div className="mb-3 flex items-center gap-2">
            <i className="fa-solid fa-clock text-sm text-[#818CF8]" aria-hidden="true" />
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[#818CF8]">
              Best Time to Apply
            </h3>
          </div>
          <div className="mb-2 flex items-baseline gap-2">
            <span className="mono text-2xl font-bold text-white">+23%</span>
            <span className="text-xs text-aether-muted">response rate</span>
          </div>
          <p className="text-xs leading-relaxed text-aether-muted">
            Applications submitted <span className="font-medium text-white">Mon–Wed morning</span>{" "}
            earn 23% higher response rates than the weekly average.
          </p>
          <div className="mt-4 grid grid-cols-7 gap-1" aria-hidden="true">
            {WEEK_CELLS.map((cls, i) => (
              <div key={i} className={`h-6 rounded ${cls}`} />
            ))}
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1 text-center text-[9px] text-aether-muted-dim">
            {WEEK_LABELS.map((d, i) => (
              <span key={i}>{d}</span>
            ))}
          </div>
        </div>

        {/* Where to focus */}
        <div className="relative overflow-hidden rounded-xl border border-aether-coral/25 bg-white/5 p-5">
          <div className="absolute -bottom-6 -right-6 h-24 w-24 rounded-full bg-aether-coral/10 blur-2xl" />
          <div className="relative mb-3 flex items-center gap-2">
            <i className="fa-solid fa-brain text-sm text-aether-coral" aria-hidden="true" />
            <h3 className="text-xs font-semibold uppercase tracking-wide text-aether-coral">
              Where to Focus
            </h3>
          </div>
          <p className="relative text-xs leading-relaxed text-[#C8C8DC]">
            Your profile matches strongly for{" "}
            <span className="font-medium text-white">TPM roles in Financial Services</span>. Consider
            expanding to <span className="font-medium text-white">US remote opportunities</span>,
            where demand is <span className="mono text-aether-coral">40% higher</span>.
          </p>
          <Link
            href="/dashboard/jobs"
            className="relative mt-4 block w-full rounded-lg border border-aether-coral/25 bg-aether-coral/15 py-2 text-center text-xs font-medium text-aether-coral transition hover:bg-aether-coral/25 max-sm:min-h-11 max-sm:content-center"
          >
            Explore matching roles
          </Link>
        </div>
      </div>
    </section>
  );
}
