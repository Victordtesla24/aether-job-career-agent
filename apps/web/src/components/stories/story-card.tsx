"use client";

import { useState } from "react";

import type { Story, StoryInput } from "../../lib/api/stories";
import { StoryForm } from "./story-form";

/**
 * Category → accent classes. Literal Tailwind strings so the JIT compiler keeps
 * them (arbitrary values can't be built dynamically).
 */
const CATEGORY_STYLE: Record<
  string,
  { border: string; badge: string }
> = {
  Delivery: { border: "border-l-[#FF6B35]", badge: "bg-[#FF6B35]/15 text-[#FF6B35]" },
  Leadership: { border: "border-l-[#4F46E5]", badge: "bg-[#4F46E5]/20 text-[#818CF8]" },
  "Risk & Compliance": { border: "border-l-[#A78BFA]", badge: "bg-[#A78BFA]/20 text-[#A78BFA]" },
  Technical: { border: "border-l-[#38BDF8]", badge: "bg-[#38BDF8]/15 text-[#38BDF8]" },
};

const DEFAULT_STYLE = { border: "border-l-white/20", badge: "bg-white/10 text-aether-muted" };

function starText(story: Story): string {
  return [
    `${story.title}`,
    `Situation: ${story.situation}`,
    `Task: ${story.task}`,
    `Action: ${story.action}`,
    `Result: ${story.result}`,
  ].join("\n");
}

interface StoryCardProps {
  story: Story;
  editing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: (input: StoryInput) => Promise<void>;
  onDelete: () => void;
  onToggleStar: () => void;
}

export function StoryCard({
  story,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
  onDelete,
  onToggleStar,
}: StoryCardProps) {
  const [copied, setCopied] = useState(false);
  const style = CATEGORY_STYLE[story.category ?? ""] ?? DEFAULT_STYLE;
  const voice = story.voiceMatch ?? 0;
  const voiceCls = voice >= 90 ? "text-[#A78BFA]" : "text-[#FBBF24]";

  const insert = async () => {
    try {
      await navigator.clipboard.writeText(starText(story));
    } catch {
      /* clipboard blocked — still show confirmation of the attempt */
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  if (editing) {
    return (
      <article
        data-testid="story-card"
        className={`glass-raised rounded-2xl border border-white/10 border-l-2 ${style.border} p-5`}
      >
        <StoryForm
          initial={{
            title: story.title,
            situation: story.situation,
            task: story.task,
            action: story.action,
            result: story.result,
            tags: story.tags,
          }}
          submitLabel="Save Changes"
          onSubmit={onSave}
          onCancel={onCancelEdit}
        />
      </article>
    );
  }

  return (
    <article
      data-testid="story-card"
      data-category={story.category}
      className={`glass-raised rounded-2xl border border-white/10 border-l-2 ${style.border} p-5 transition hover:border-white/20`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span
              className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${style.badge}`}
            >
              {story.category ?? "Story"}
            </span>
            {story.impact ? (
              <span className="mono rounded bg-[#34D399]/15 px-2 py-0.5 text-[10px] text-[#34D399]">
                {story.impact}
              </span>
            ) : null}
          </div>
          <h3 className="truncate text-base font-semibold">{story.title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            data-testid="star-story-btn"
            aria-pressed={story.starred ?? false}
            aria-label={story.starred ? "Unstar story" : "Star story"}
            onClick={onToggleStar}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[#FBBF24] transition hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40"
          >
            <i className={`${story.starred ? "fa-solid" : "fa-regular"} fa-star`} aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="edit-story-btn"
            aria-label="Edit story"
            onClick={onStartEdit}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted transition hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40"
          >
            <i className="fa-solid fa-pen" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="delete-story-btn"
            aria-label="Delete story"
            onClick={onDelete}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted transition hover:bg-white/5 hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40"
          >
            <i className="fa-solid fa-trash-can" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 text-[13px] sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Situation", story.situation, "text-[#818CF8]"],
            ["Task", story.task, "text-[#818CF8]"],
            ["Action", story.action, "text-[#818CF8]"],
            ["Result", story.result, "text-[#34D399]"],
          ] as const
        ).map(([label, value, labelCls]) => (
          <div key={label}>
            <div className={`mb-1 text-[10px] font-semibold uppercase ${labelCls}`}>{label}</div>
            <p className="text-[#C7C7D6]">{value}</p>
          </div>
        ))}
      </div>

      {story.tags.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {story.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-aether-muted-dim"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/6 pt-3">
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-aether-muted">
          <span>
            <i className="fa-solid fa-link mr-1" aria-hidden="true" />
            Used in {story.usedInResumes ?? 0} resumes
          </span>
          <span>
            <i className="fa-solid fa-microphone-lines mr-1" aria-hidden="true" />
            {story.interviewAnswers ?? 0} interview answers
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`mono text-[11px] ${voiceCls}`}>Voice {voice}%</span>
          <button
            type="button"
            data-testid="insert-story-btn"
            onClick={() => void insert()}
            aria-label={`Insert ${story.title} — copy STAR text to clipboard`}
            className="min-h-[44px] rounded-lg bg-white/8 px-3 py-1.5 text-xs transition hover:bg-white/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40 sm:min-h-0"
          >
            {copied ? (
              <span className="text-[#34D399]">
                <i className="fa-solid fa-check mr-1" aria-hidden="true" />
                Copied
              </span>
            ) : (
              "Insert"
            )}
          </button>
        </div>
      </div>
    </article>
  );
}
