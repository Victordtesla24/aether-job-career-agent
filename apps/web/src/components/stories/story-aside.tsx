"use client";

import type { Story } from "../../lib/api/stories";

/** Canonical interview questions mapped to the best-matching live story. */
const MAPPER_QUESTIONS: { q: string; categories: string[]; accent: string }[] = [
  {
    q: "“Tell me about a time you improved a process.”",
    categories: ["Delivery", "Technical"],
    accent: "text-[#FF6B35]",
  },
  {
    q: "“Describe leading a large team.”",
    categories: ["Leadership"],
    accent: "text-[#818CF8]",
  },
  {
    q: "“A time you handled compliance risk.”",
    categories: ["Risk & Compliance"],
    accent: "text-[#A78BFA]",
  },
];

/** Coverage themes evaluated against the live story set. */
const COVERAGE_THEMES: { label: string; keywords: string[] }[] = [
  { label: "Conflict resolution", keywords: ["conflict", "disagree", "resolution", "mediat"] },
  { label: "Failure / lessons learned", keywords: ["fail", "lesson", "mistake", "setback", "learned"] },
  { label: "Stakeholder influence", keywords: ["stakeholder", "influence", "align", "buy-in", "persuad"] },
];

function bestStory(stories: Story[], categories: string[]): Story | null {
  const pool = stories.filter((s) => categories.includes(s.category ?? ""));
  const ranked = (pool.length ? pool : stories)
    .slice()
    .sort((a, b) => (b.voiceMatch ?? 0) - (a.voiceMatch ?? 0));
  return ranked[0] ?? null;
}

function coverageCount(stories: Story[], keywords: string[]): number {
  return stories.filter((s) => {
    const hay = `${s.title} ${s.situation} ${s.task} ${s.action} ${s.result} ${s.tags.join(" ")}`.toLowerCase();
    return keywords.some((k) => hay.includes(k));
  }).length;
}

export function StoryAside({
  stories,
  onDraftMissing,
}: {
  stories: Story[];
  onDraftMissing: () => void;
}) {
  return (
    <aside className="w-full space-y-4 lg:w-80 lg:shrink-0" aria-label="Story insights">
      <section className="glass rounded-2xl border border-white/10 p-5" data-testid="question-mapper">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-diagram-project text-aether-coral" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Interview Question Mapper</h2>
        </div>
        <p className="mb-4 text-[11px] text-aether-muted">Which stories answer common questions.</p>
        <div className="space-y-3 text-[13px]">
          {MAPPER_QUESTIONS.map(({ q, categories, accent }) => {
            const match = bestStory(stories, categories);
            return (
              <div key={q} className="glass-raised rounded-xl border border-white/10 p-3">
                <div className="mb-1 text-[#C7C7D6]">{q}</div>
                <div className={`text-[11px] ${match ? accent : "text-aether-muted-dim"}`}>
                  <i className="fa-solid fa-arrow-right-long mr-1" aria-hidden="true" />
                  {match ? match.title : "No matching story yet"}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="glass rounded-2xl border border-white/10 p-5" data-testid="coverage-gaps">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-triangle-exclamation text-[#FBBF24]" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Coverage Gaps</h2>
        </div>
        <div className="space-y-2 text-[13px] text-[#C7C7D6]">
          {COVERAGE_THEMES.map(({ label, keywords }) => {
            const count = coverageCount(stories, keywords);
            const status =
              count === 0
                ? { text: "No story", cls: "text-[#F87171]" }
                : count === 1
                  ? { text: "Thin", cls: "text-[#FBBF24]" }
                  : { text: "Covered", cls: "text-[#34D399]" };
            return (
              <div key={label} className="flex items-center justify-between gap-2">
                <span>{label}</span>
                <span className={`text-[11px] ${status.cls}`}>{status.text}</span>
              </div>
            );
          })}
        </div>
        <button
          type="button"
          data-testid="draft-missing-btn"
          onClick={onDraftMissing}
          className="mt-4 min-h-[44px] w-full rounded-xl bg-aether-indigo px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#5b52ea] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-indigo/50"
        >
          <i className="fa-solid fa-wand-magic-sparkles mr-1" aria-hidden="true" />
          Draft missing stories
        </button>
      </section>
    </aside>
  );
}
