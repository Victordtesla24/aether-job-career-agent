"use client";

import { useState } from "react";

import type { StoryInput } from "../../lib/api/stories";

export const EMPTY_STORY_FORM: StoryInput = {
  title: "",
  situation: "",
  task: "",
  action: "",
  result: "",
  tags: [],
};

interface StoryFormProps {
  initial: StoryInput;
  submitLabel: string;
  onSubmit: (input: StoryInput) => Promise<void>;
  onCancel: () => void;
}

const FIELD_CLS =
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-aether-muted-dim focus-visible:border-aether-coral/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40";

/** Create / edit form for a STAR story. Required-field validation is native. */
export function StoryForm({ initial, submitLabel, onSubmit, onCancel }: StoryFormProps) {
  const [form, setForm] = useState<StoryInput>(initial);
  const [tagsText, setTagsText] = useState((initial.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set =
    (key: keyof StoryInput) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        ...form,
        tags: tagsText
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save story");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3" data-testid="story-form">
      {error ? (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      ) : null}
      <div>
        <label htmlFor="story-title" className="sr-only">
          Story title
        </label>
        <input
          id="story-title"
          required
          value={form.title}
          onChange={set("title")}
          placeholder="Title — e.g. Reduced ATO test automation effort by 92%"
          data-testid="story-form-title"
          className={FIELD_CLS}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {(
          [
            ["situation", "Situation"],
            ["task", "Task"],
            ["action", "Action"],
            ["result", "Result"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label htmlFor={`story-${key}`} className="sr-only">
              {label}
            </label>
            <textarea
              id={`story-${key}`}
              required
              value={form[key] as string}
              onChange={set(key)}
              placeholder={label}
              rows={2}
              data-testid={`story-form-${key}`}
              className={FIELD_CLS}
            />
          </div>
        ))}
      </div>
      <div>
        <label htmlFor="story-tags" className="sr-only">
          Tags
        </label>
        <input
          id="story-tags"
          value={tagsText}
          onChange={(e) => setTagsText(e.target.value)}
          placeholder="Tags (comma separated) — e.g. Leadership, Delivery"
          data-testid="story-form-tags"
          className={FIELD_CLS}
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          data-testid="story-form-submit"
          className="min-h-[44px] rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-aether-bg transition hover:bg-[#ff7d4d] disabled:opacity-50"
        >
          {saving ? "Saving…" : submitLabel}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={onCancel}
          data-testid="story-form-cancel"
          className="min-h-[44px] rounded-xl border border-white/10 px-4 py-2 text-sm text-aether-muted transition hover:border-white/25 hover:text-white disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
