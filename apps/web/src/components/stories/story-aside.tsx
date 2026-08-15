"use client";

import type { Story } from "../../lib/api/stories";
import { extractorTriggerState } from "./logic";

/**
 * Canonical interview questions mapped to the best-matching live story.
 * Accents mirror story-card's CATEGORY_STYLE — the validated CHART_PALETTE in
 * fixed order (RULINGS.md R6). "Delivery, Technical" keeps Delivery's gold.
 */
const MAPPER_QUESTIONS: { q: string; categories: string[]; accent: string }[] = [
  {
    q: "“Tell me about a time you improved a process.”",
    categories: ["Delivery", "Technical"],
    accent: "text-[#AE8E32]",
  },
  {
    q: "“Describe leading a large team.”",
    categories: ["Leadership"],
    accent: "text-[#4F74B5]",
  },
  {
    q: "“A time you handled compliance risk.”",
    categories: ["Risk & Compliance"],
    accent: "text-[#C16F7B]",
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
    .sort(
      (a, b) =>
        Object.keys(b.metrics ?? {}).length - Object.keys(a.metrics ?? {}).length,
    );
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
  drafting = false,
  onDraftMissing,
}: {
  stories: Story[];
  /** True while the Story Extraction Agent run is in flight. */
  drafting?: boolean;
  onDraftMissing: () => void;
}) {
  const extractorState = extractorTriggerState(drafting, "Draft missing stories", "Drafting from resume…");
  return (
    <aside className="w-full space-y-4 lg:w-[300px] lg:shrink-0 lg:sticky lg:top-20" aria-label="Story insights">
      <section className="elev-1 rounded-2xl p-5" data-testid="question-mapper">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-diagram-project text-aether-coral" aria-hidden="true" />
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Interview Question Mapper</h2>
        </div>
        <p className="mb-4 text-[11px] text-aether-muted">Which stories answer common questions.</p>
        <div className="space-y-3 text-[13px]">
          {MAPPER_QUESTIONS.map(({ q, categories, accent }) => {
            const match = bestStory(stories, categories);
            return (
              <div key={q} className="elev-2 rounded-xl p-3">
                <div className="mb-1 text-aether-muted">{q}</div>
                <div
                  className={`flex items-center text-[11px] ${match ? accent : "text-aether-muted-dim"}`}
                >
                  <i className="fa-solid fa-arrow-right-long mr-1 shrink-0" aria-hidden="true" />
                  {/*
                    MV-story-bank-008: an unbroken-long story title has no
                    whitespace to wrap at, so without truncate it can overflow
                    this fixed-width aside — the same class of bug
                    MV-story-bank-002 fixed on the STAR fields. `min-w-0`
                    overrides the flex item's default `min-width: auto` so
                    `truncate` (overflow:hidden + ellipsis + nowrap) can
                    actually take effect, matching the story-card header's
                    already-fixed `h3.truncate` treatment of story.title.
                  */}
                  <span className="min-w-0 truncate">
                    {match ? match.title : "No matching story yet"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="elev-1 rounded-2xl p-5" data-testid="coverage-gaps">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-triangle-exclamation text-state-warn" aria-hidden="true" />
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Coverage Gaps</h2>
        </div>
        <div className="space-y-2 text-[13px] text-aether-muted">
          {COVERAGE_THEMES.map(({ label, keywords }) => {
            const count = coverageCount(stories, keywords);
            const status =
              count === 0
                ? { text: "No story", cls: "text-state-danger" }
                : count === 1
                  ? { text: "Thin", cls: "text-state-warn" }
                  : { text: "Covered", cls: "text-state-ok" };
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
          disabled={extractorState.disabled}
          aria-busy={drafting}
          className="mt-4 min-h-[44px] w-full rounded-xl bg-aether-indigo px-3 py-2 text-xs font-semibold text-white transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-indigo/50 disabled:opacity-60"
        >
          <i
            className={`fa-solid ${drafting ? "fa-spinner fa-spin" : "fa-wand-magic-sparkles"} mr-1`}
            aria-hidden="true"
          />
          {extractorState.label}
        </button>
      </section>
    </aside>
  );
}
