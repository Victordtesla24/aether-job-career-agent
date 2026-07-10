"use client";

import { useId, useState } from "react";

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
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-aether-muted-dim focus:border-aether-coral/60 focus:outline-none";

export function StoryForm({ initial, submitLabel, onSubmit, onCancel }: StoryFormProps) {
  const [form, setForm] = useState<StoryInput>(initial);
  const [tagsText, setTagsText] = useState((initial.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uid = useId();

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
        <p role="alert" className="text-xs text-[#F87171]">
          {error}
        </p>
      ) : null}
      <div>
        <label htmlFor={`${uid}-title`} className="mb-1 block text-[11px] uppercase tracking-wide text-aether-muted-dim">
          Title
        </label>
        <input
          id={`${uid}-title`}
          required
          value={form.title}
          onChange={set("title")}
          placeholder="e.g. Reduced ATO test automation effort by 92%"
          data-testid="story-form-title"
          className={FIELD_CLS}
        />
      </div>
      {(
        [
          ["situation", "Situation"],
          ["task", "Task"],
          ["action", "Action"],
          ["result", "Result"],
        ] as const
      ).map(([key, label]) => (
        <div key={key}>
          <label
            htmlFor={`${uid}-${key}`}
            className="mb-1 block text-[11px] uppercase tracking-wide text-aether-muted-dim"
          >
            {label}
          </label>
          <textarea
            id={`${uid}-${key}`}
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
      <div>
        <label htmlFor={`${uid}-tags`} className="mb-1 block text-[11px] uppercase tracking-wide text-aether-muted-dim">
          Tags
        </label>
        <input
          id={`${uid}-tags`}
          value={tagsText}
          onChange={(e) => setTagsText(e.target.value)}
          placeholder="Tags (comma separated) — e.g. delivery, automation"
          data-testid="story-form-tags"
          className={FIELD_CLS}
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          data-testid="story-form-submit"
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : submitLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-white/10 px-4 py-2 text-sm text-aether-muted transition hover:border-white/25"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
