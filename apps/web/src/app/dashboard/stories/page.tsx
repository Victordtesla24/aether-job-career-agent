"use client";

/**
 * Story Bank — STAR stories extracted from the base resume with evidence-backed
 * metrics. Backed by GET/POST/PUT/DELETE /stories and
 * POST /agents/story-extractor/run. Manual creation + inline editing added for
 * audit defect D6 (journey J5 requires the creation flow to work end-to-end).
 */
import { useCallback, useEffect, useState } from "react";

import {
  createStory,
  deleteStory,
  fetchStories,
  runStoryExtractor,
  updateStory,
  type Story,
  type StoryInput,
} from "../../../lib/api/stories";

const EMPTY_FORM: StoryInput = {
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

function StoryForm({ initial, submitLabel, onSubmit, onCancel }: StoryFormProps) {
  const [form, setForm] = useState<StoryInput>(initial);
  const [tagsText, setTagsText] = useState((initial.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof StoryInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
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

  const fieldCls =
    "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-aether-muted-dim focus:border-aether-coral/60 focus:outline-none";

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3" data-testid="story-form">
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
      <input
        required
        value={form.title}
        onChange={set("title")}
        placeholder="Title"
        data-testid="story-form-title"
        className={fieldCls}
      />
      {(
        [
          ["situation", "Situation"],
          ["task", "Task"],
          ["action", "Action"],
          ["result", "Result"],
        ] as const
      ).map(([key, label]) => (
        <textarea
          key={key}
          required
          value={form[key] as string}
          onChange={set(key)}
          placeholder={label}
          rows={2}
          data-testid={`story-form-${key}`}
          className={fieldCls}
        />
      ))}
      <input
        value={tagsText}
        onChange={(e) => setTagsText(e.target.value)}
        placeholder="Tags (comma separated)"
        data-testid="story-form-tags"
        className={fieldCls}
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          data-testid="story-form-submit"
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : submitLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-white/10 px-4 py-2 text-sm text-aether-muted hover:border-white/25"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function StoryBankPage() {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStories(await fetchStories());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stories");
      setStories([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const extract = async () => {
    setRunning(true);
    try {
      await runStoryExtractor();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Story extraction failed");
    } finally {
      setRunning(false);
    }
  };

  const remove = async (id: string) => {
    await deleteStory(id);
    setStories((prev) => (prev ?? []).filter((s) => s.id !== id));
  };

  const create = async (input: StoryInput) => {
    const story = await createStory(input);
    setStories((prev) => [story, ...(prev ?? [])]);
    setCreating(false);
  };

  const saveEdit = async (id: string, input: StoryInput) => {
    const updated = await updateStory(id, input);
    setStories((prev) => (prev ?? []).map((s) => (s.id === id ? updated : s)));
    setEditingId(null);
  };

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Story Bank</h1>
          <p className="text-sm text-aether-muted">
            STAR stories mined from your resume — metrics must trace to evidence.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="add-story-btn"
            onClick={() => {
              setCreating((v) => !v);
              setEditingId(null);
            }}
            className="rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-aether-muted hover:border-white/30 hover:text-white"
          >
            {creating ? "Close" : "Add Story"}
          </button>
          <button
            type="button"
            data-testid="run-extractor-btn"
            onClick={() => void extract()}
            disabled={running}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {running ? "Extracting..." : "Extract Stories"}
          </button>
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {creating ? (
        <div className="glass rounded-2xl border border-aether-coral/30 p-5" data-testid="create-story-panel">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-aether-muted">
            New story
          </h2>
          <StoryForm
            initial={EMPTY_FORM}
            submitLabel="Create Story"
            onSubmit={create}
            onCancel={() => setCreating(false)}
          />
        </div>
      ) : null}

      {stories === null ? (
        <div className="grid gap-4 md:grid-cols-2" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass h-48 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : stories.length === 0 ? (
        <div className="glass rounded-2xl border border-white/10 p-10 text-center" data-testid="stories-empty-state">
          <p className="text-lg font-semibold">No stories yet</p>
          <p className="mt-1 text-sm text-aether-muted">
            Run the Story Extractor to mine STAR stories from your resume.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {stories.map((story) => (
            <article
              key={story.id}
              data-testid="story-card"
              className="glass rounded-2xl border border-white/10 p-5 transition hover:border-white/20"
            >
              {editingId === story.id ? (
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
                  onSubmit={(input) => saveEdit(story.id, input)}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="font-semibold">{story.title}</h2>
                    <div className="flex shrink-0 gap-2">
                      <button
                        type="button"
                        data-testid="edit-story-btn"
                        onClick={() => {
                          setEditingId(story.id);
                          setCreating(false);
                        }}
                        className="text-xs text-aether-muted-dim hover:text-aether-amber"
                        title="Edit story"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(story.id)}
                        className="text-xs text-aether-muted-dim hover:text-red-300"
                        title="Delete story"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                  <dl className="mt-3 space-y-2 text-sm">
                    {(
                      [
                        ["Situation", story.situation],
                        ["Task", story.task],
                        ["Action", story.action],
                        ["Result", story.result],
                      ] as const
                    ).map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-xs uppercase tracking-wide text-aether-muted-dim">{label}</dt>
                        <dd className="text-aether-muted">{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {story.tags.map((tag) => (
                      <span key={tag} className="rounded-full border border-white/10 px-2 py-0.5 text-aether-muted-dim">
                        {tag}
                      </span>
                    ))}
                    {story.metrics
                      ? Object.entries(story.metrics).map(([k, v]) => (
                          <span key={k} className="mono rounded-full border border-aether-green/30 px-2 py-0.5 text-aether-green">
                            {k}: {String(v)}
                          </span>
                        ))
                      : null}
                  </div>
                </>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
