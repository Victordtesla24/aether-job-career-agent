"use client";

import type { Story } from "../../lib/api/stories";
import { coverageGaps, mapQuestions } from "./story-utils";

interface StoryInsightsProps {
  stories: Story[];
  onDraftMissing: () => void;
}

export function StoryInsights({ stories, onDraftMissing }: StoryInsightsProps) {
  const mappings = mapQuestions(stories);
  const gaps = coverageGaps(stories);

  return (
    <aside data-testid="story-insights" className="w-full shrink-0 space-y-4 lg:w-80">
      <section className="glass rounded-2xl p-5">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-diagram-project text-aether-coral" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Interview Question Mapper</h2>
        </div>
        <p className="mb-4 text-[11px] text-aether-muted">Which stories answer common questions.</p>
        <div className="space-y-3 text-[13px]">
          {mappings.map(({ question, story, accent }) => (
            <div key={question} className="glass-raised rounded-xl border border-white/10 p-3">
              <div className="mb-1 text-[#C7C7D6]">{question}</div>
              {story ? (
                <div className="text-[11px]" style={{ color: accent }}>
                  <i className="fa-solid fa-arrow-right-long mr-1" aria-hidden="true" />
                  {story.title}
                </div>
              ) : (
                <div className="text-[11px] text-aether-muted-dim">
                  <i className="fa-solid fa-circle-minus mr-1" aria-hidden="true" />
                  No matching story yet
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="glass rounded-2xl p-5">
        <div className="mb-3 flex items-center gap-2">
          <i className="fa-solid fa-triangle-exclamation text-aether-yellow" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Coverage Gaps</h2>
        </div>
        {gaps.length === 0 ? (
          <p className="text-[13px] text-aether-muted">
            <i className="fa-solid fa-circle-check mr-1 text-aether-green" aria-hidden="true" />
            Full coverage across tracked competencies.
          </p>
        ) : (
          <div className="space-y-2 text-[13px] text-[#C7C7D6]">
            {gaps.map(({ competency, status }) => (
              <div key={competency} className="flex items-center justify-between">
                <span>{competency}</span>
                <span
                  className="text-[11px]"
                  style={{ color: status === "No story" ? "#F87171" : "#FBBF24" }}
                >
                  {status}
                </span>
              </div>
            ))}
          </div>
        )}
        <button
          type="button"
          data-testid="draft-missing-btn"
          onClick={onDraftMissing}
          className="mt-4 w-full rounded-xl bg-aether-indigo px-3 py-2 text-xs font-semibold transition hover:opacity-90"
        >
          <i className="fa-solid fa-wand-magic-sparkles mr-1" aria-hidden="true" />
          Draft missing stories
        </button>
      </section>
    </aside>
  );
}
