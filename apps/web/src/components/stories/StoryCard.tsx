"use client";

import { useState } from "react";

import type { Story, StoryInput } from "../../lib/api/stories";
import { StoryForm } from "./StoryForm";
import {
  CATEGORY_COLOR,
  categoryOf,
  impactBadge,
  storyToText,
  voiceMatchOf,
} from "./story-utils";

interface StoryCardProps {
  story: Story;
  isEditing: boolean;
  isFavourite: boolean;
  onToggleFavourite: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (input: StoryInput) => Promise<void>;
  onDelete: () => void;
}

const STAR_LABELS = [
  ["Situation", "#818CF8"],
  ["Task", "#818CF8"],
  ["Action", "#818CF8"],
  ["Result", "#34D399"],
] as const;

export function StoryCard({
  story,
  isEditing,
  isFavourite,
  onToggleFavourite,
  onEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}: StoryCardProps) {
  const [inserted, setInserted] = useState(false);
  const category = categoryOf(story);
  const colors = category ? CATEGORY_COLOR[category] : null;
  const impact = impactBadge(story);
  const voice = voiceMatchOf(story);
  const starValues: Record<string, string> = {
    Situation: story.situation,
    Task: story.task,
    Action: story.action,
    Result: story.result,
  };

  const insert = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(storyToText(story));
      }
      setInserted(true);
      setTimeout(() => setInserted(false), 1500);
    } catch {
      setInserted(false);
    }
  };

  if (isEditing) {
    return (
      <article
        data-testid="story-card"
        className="glass-raised rounded-2xl border border-white/10 p-5"
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
          onSubmit={onSaveEdit}
          onCancel={onCancelEdit}
        />
      </article>
    );
  }

  return (
    <article
      data-testid="story-card"
      className="glass-raised rounded-2xl border border-l-2 border-white/10 p-5 transition hover:border-white/20"
      style={{ borderLeftColor: colors?.border ?? "#FF6B35" }}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {category ? (
              <span
                className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ backgroundColor: colors?.badgeBg, color: colors?.badgeText }}
              >
                {category}
              </span>
            ) : null}
            {impact ? (
              <span className="mono rounded bg-aether-green/15 px-2 py-0.5 text-[10px] text-aether-green">
                {impact}
              </span>
            ) : null}
          </div>
          <h3 className="text-base font-semibold">{story.title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-aether-muted">
          <button
            type="button"
            onClick={onToggleFavourite}
            aria-pressed={isFavourite}
            aria-label={isFavourite ? "Unpin story" : "Pin story"}
            title={isFavourite ? "Unpin story" : "Pin story"}
            className="transition hover:text-aether-yellow"
          >
            <i className={`${isFavourite ? "fa-solid" : "fa-regular"} fa-star ${isFavourite ? "text-aether-yellow" : ""}`} aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="edit-story-btn"
            onClick={onEdit}
            aria-label="Edit story"
            title="Edit story"
            className="transition hover:text-white"
          >
            <i className="fa-solid fa-pen" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="delete-story-btn"
            onClick={onDelete}
            aria-label="Delete story"
            title="Delete story"
            className="transition hover:text-[#F87171]"
          >
            <i className="fa-solid fa-trash" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 text-[13px] sm:grid-cols-2 xl:grid-cols-4">
        {STAR_LABELS.map(([label, color]) => (
          <div key={label}>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color }}>
              {label}
            </div>
            <p className="text-[#C7C7D6]">{starValues[label]}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {story.tags.map((tag) => (
            <span key={tag} className="rounded-full border border-white/10 px-2 py-0.5 text-aether-muted-dim">
              {tag}
            </span>
          ))}
          {story.metrics
            ? Object.entries(story.metrics)
                .filter(([k]) => !/voice/i.test(k))
                .map(([k, v]) => (
                  <span key={k} className="mono rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">
                    {k}: {String(v)}
                  </span>
                ))
            : null}
        </div>
        <div className="flex items-center gap-2">
          {voice !== null ? (
            <span className="mono text-[11px] text-[#A78BFA]">Voice {voice}%</span>
          ) : null}
          <button
            type="button"
            data-testid="insert-story-btn"
            onClick={() => void insert()}
            className="rounded-lg bg-white/8 px-3 py-1.5 text-xs transition hover:bg-white/12"
          >
            {inserted ? (
              <>
                <i className="fa-solid fa-check mr-1 text-aether-green" aria-hidden="true" />Copied
              </>
            ) : (
              <>
                <i className="fa-solid fa-arrow-right-to-bracket mr-1" aria-hidden="true" />Insert
              </>
            )}
          </button>
        </div>
      </div>
    </article>
  );
}
