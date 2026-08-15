"use client";

import { useState } from "react";

import type { Story, StoryInput } from "../../lib/api/stories";
import { StoryForm } from "./story-form";

/**
 * Category → accent classes. Literal Tailwind strings so the JIT compiler keeps
 * them (arbitrary values can't be built dynamically). Colours are the validated
 * CHART_PALETTE (`../charts/tokens`) in fixed order — RULINGS.md R6: categorical
 * identity anywhere in the UI draws from the chart-kit hues, never a bespoke
 * rainbow. Order: #AE8E32 gold, #4F74B5 sapphire, #C16F7B rose, #439FC8 sky.
 */
const CATEGORY_STYLE: Record<
  string,
  { border: string; badge: string }
> = {
  Delivery: { border: "border-l-[#AE8E32]", badge: "bg-[#AE8E32]/15 text-[#AE8E32]" },
  Leadership: { border: "border-l-[#4F74B5]", badge: "bg-[#4F74B5]/20 text-[#4F74B5]" },
  "Risk & Compliance": { border: "border-l-[#C16F7B]", badge: "bg-[#C16F7B]/20 text-[#C16F7B]" },
  Technical: { border: "border-l-[#439FC8]", badge: "bg-[#439FC8]/15 text-[#439FC8]" },
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
  /**
   * Open the full story in the `elev-3` sheet (§5.8 / X-2). Optional so the
   * card keeps working anywhere it is rendered without one — the clamp then
   * simply stands on its own rather than promising a read that cannot happen.
   */
  onRead?: () => void;
}

export function StoryCard({
  story,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
  onDelete,
  onToggleStar,
  onRead,
}: StoryCardProps) {
  const [copied, setCopied] = useState(false);
  const style = CATEGORY_STYLE[story.category ?? ""] ?? DEFAULT_STYLE;
  const metricCount = Object.keys(story.metrics ?? {}).length;

  const insert = async () => {
    try {
      await navigator.clipboard.writeText(starText(story));
    } catch {
      /* clipboard blocked — still show confirmation of the attempt */
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  // MV-story-bank-003: deleting a story is permanent (no undo) — gate it
  // behind an explicit confirmation so a single accidental click can't
  // destroy a STAR narrative.
  const confirmDelete = () => {
    if (window.confirm(`Delete "${story.title}"? This cannot be undone.`)) {
      onDelete();
    }
  };

  if (editing) {
    return (
      <article
        data-testid="story-card"
        className={`elev-2 rounded-2xl border-l-2 ${style.border} p-5`}
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
      className={`elev-1 rounded-2xl border-l-2 ${style.border} p-4 transition-colors duration-[--dur-fast] hover:border-hairline-strong`}
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
              <span className="mono rounded bg-state-ok/15 px-2 py-0.5 text-[10px] text-state-ok">
                {story.impact}
              </span>
            ) : null}
          </div>
          <h3 className="truncate text-[14px] font-semibold tracking-[-0.01em]">{story.title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            data-testid="star-story-btn"
            aria-pressed={story.starred ?? false}
            aria-label={story.starred ? "Unstar story" : "Star story"}
            onClick={onToggleStar}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-coral transition-colors duration-[--dur-fast] hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
          >
            <i className={`${story.starred ? "fa-solid" : "fa-regular"} fa-star`} aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="edit-story-btn"
            aria-label="Edit story"
            onClick={onStartEdit}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-white/[0.06] hover:text-aether-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
          >
            <i className="fa-solid fa-pen" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="delete-story-btn"
            aria-label="Delete story"
            onClick={confirmDelete}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-white/[0.06] hover:text-state-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
          >
            <i className="fa-solid fa-trash-can" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 text-[12.5px] sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Situation", story.situation, "text-aether-violet"],
            ["Task", story.task, "text-aether-violet"],
            ["Action", story.action, "text-aether-violet"],
            ["Result", story.result, "text-state-ok"],
          ] as const
        ).map(([label, value, labelCls]) => (
          // min-w-0: CSS Grid items default to `min-width: auto` (i.e. sized
          // to their intrinsic content), so a single long unbroken token
          // (MV-story-bank-002) can stretch the grid track — and therefore
          // the whole page — no matter what wrap CSS the text itself has.
          <div key={label} className="min-w-0">
            <div className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] ${labelCls}`}>
              {label}
            </div>
            {/* D-ε: three lines each, never the whole narrative. With 20
                stories the un-clamped grid made this page 9,071px tall at
                1600 (b3/before/before-notes.json); the full text lives one
                click away in the sheet, not inline (X-2). */}
            <p className="line-clamp-3 min-w-0 break-words leading-[1.55] text-aether-muted">{value}</p>
          </div>
        ))}
      </div>

      {story.tags.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {story.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-aether-muted-dim"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-t border-hairline pt-3">
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-aether-muted">
          <span>
            <i className="fa-solid fa-chart-simple mr-1" aria-hidden="true" />
            {metricCount} evidenced metric{metricCount === 1 ? "" : "s"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {onRead ? (
            <button
              type="button"
              data-testid="read-story-btn"
              onClick={onRead}
              aria-label={`Read ${story.title} in full`}
              className="min-h-[44px] rounded-lg border border-hairline px-3 py-1.5 text-xs text-aether-muted transition-colors duration-[--dur-fast] hover:border-hairline-strong hover:text-aether-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50 sm:min-h-0"
            >
              Read
            </button>
          ) : null}
          <button
            type="button"
            data-testid="insert-story-btn"
            onClick={() => void insert()}
            aria-label={`Insert ${story.title} — copy STAR text to clipboard`}
            className="min-h-[44px] rounded-lg bg-white/[0.08] px-3 py-1.5 text-xs transition-colors duration-[--dur-fast] hover:bg-white/[0.12] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50 sm:min-h-0"
          >
            {copied ? (
              <span className="text-state-ok">
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
