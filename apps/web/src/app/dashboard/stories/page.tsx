"use client";

/**
 * Story Bank — STAR+R achievement library. Reusable evidence blocks that power
 * resumes, cover letters and interview answers.
 *
 * Backed by GET/POST/PUT/DELETE /stories and POST /agents/story-extractor/run.
 * Every card, stat, question-mapping and coverage-gap is derived from live API
 * data (see components/stories/story-utils.ts) — no hardcoded fixtures and no
 * fabricated metrics. Mirrors design/screens/story-bank.html.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createStory,
  deleteStory,
  fetchStories,
  runStoryExtractor,
  updateStory,
  type Story,
  type StoryInput,
} from "../../../lib/api/stories";
import { EMPTY_STORY_FORM, StoryForm } from "../../../components/stories/StoryForm";
import { StoryCard } from "../../../components/stories/StoryCard";
import { StoryInsights } from "../../../components/stories/StoryInsights";
import {
  STORY_FILTERS,
  type StoryFilter,
  computeStats,
  matchesFilter,
} from "../../../components/stories/story-utils";

function StatCard({
  label,
  value,
  valueClass = "",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="glass rounded-2xl border border-white/10 p-4">
      <div className="mb-1 text-[11px] text-aether-muted">{label}</div>
      <div className={`mono text-2xl font-bold ${valueClass}`}>{value}</div>
    </div>
  );
}

export default function StoryBankPage() {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<StoryFilter>("All");
  const [favourites, setFavourites] = useState<Set<string>>(new Set());
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
    try {
      await deleteStory(id);
      setStories((prev) => (prev ?? []).filter((s) => s.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete story");
    }
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

  const openCreate = () => {
    setCreating(true);
    setEditingId(null);
  };

  const toggleFavourite = (id: string) =>
    setFavourites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const stats = useMemo(() => computeStats(stories ?? []), [stories]);
  const visible = useMemo(
    () => (stories ?? []).filter((s) => matchesFilter(s, filter)),
    [stories, filter],
  );

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-2 text-[13px] text-aether-muted">
            <i className="fa-solid fa-book-bookmark text-aether-coral" aria-hidden="true" />
            Story Bank
          </div>
          <h1 className="text-2xl font-bold">Achievement &amp; Narrative Library</h1>
          <p className="mt-1 text-sm text-aether-muted">
            Reusable STAR+R evidence blocks that power your resumes, cover letters and interview
            answers.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="run-extractor-btn"
            onClick={() => void extract()}
            disabled={running}
            className="rounded-xl border border-white/15 px-4 py-2.5 text-sm font-semibold text-aether-muted transition hover:border-white/30 hover:text-white disabled:opacity-50"
          >
            <i className="fa-solid fa-wand-magic-sparkles mr-1.5" aria-hidden="true" />
            {running ? "Extracting…" : "Extract Stories"}
          </button>
          <button
            type="button"
            data-testid="add-story-btn"
            onClick={() => (creating ? setCreating(false) : openCreate())}
            className="rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90"
          >
            <i className={`fa-solid ${creating ? "fa-xmark" : "fa-plus"} mr-1.5`} aria-hidden="true" />
            {creating ? "Close" : "New Story"}
          </button>
        </div>
      </header>

      {error ? (
        <p role="alert" className="rounded-xl border border-[#F87171]/30 bg-[#F87171]/10 p-3 text-sm text-[#F87171]">
          {error}
        </p>
      ) : null}

      <section
        data-testid="story-stats"
        className="grid grid-cols-2 gap-4 lg:grid-cols-4"
        aria-label="Story bank statistics"
      >
        <StatCard label="Total Stories" value={String(stats.total)} />
        <StatCard
          label="Quantified w/ Metrics"
          value={String(stats.quantified)}
          valueClass="text-aether-green"
        />
        <StatCard label="Added This Month" value={String(stats.addedThisMonth)} />
        <StatCard
          label="Voice Match Avg"
          value={stats.voiceAvg === null ? "—" : `${stats.voiceAvg}%`}
          valueClass="text-[#A78BFA]"
        />
      </section>

      {creating ? (
        <div className="glass rounded-2xl border border-aether-coral/30 p-5" data-testid="create-story-panel">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-aether-muted">
            New story
          </h2>
          <StoryForm
            initial={EMPTY_STORY_FORM}
            submitLabel="Create Story"
            onSubmit={create}
            onCancel={() => setCreating(false)}
          />
        </div>
      ) : null}

      <div className="flex flex-col gap-6 lg:flex-row">
        <section className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter stories by category">
            {STORY_FILTERS.map((chip) => {
              const active = filter === chip;
              return (
                <button
                  key={chip}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setFilter(chip)}
                  className={
                    active
                      ? "rounded-lg bg-white/8 px-3 py-1.5 text-xs font-medium text-white"
                      : "rounded-lg px-3 py-1.5 text-xs text-aether-muted transition hover:bg-white/5"
                  }
                >
                  {chip}
                </button>
              );
            })}
          </div>

          {stories === null ? (
            <div className="grid gap-4 md:grid-cols-2" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="glass h-48 animate-pulse rounded-2xl border border-white/10" />
              ))}
            </div>
          ) : stories.length === 0 ? (
            <div
              data-testid="stories-empty-state"
              className="rounded-2xl border border-dashed border-white/15 p-10 text-center"
            >
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-aether-coral/25 bg-aether-coral/12">
                <i className="fa-solid fa-book-bookmark text-xl text-aether-coral" aria-hidden="true" />
              </div>
              <h2 className="mb-1.5 text-base font-semibold">Your Story Bank is empty</h2>
              <p className="mx-auto mb-5 max-w-md text-sm text-aether-muted">
                Import achievements from your resume to build your interview arsenal. Aether will
                auto-extract STAR+R stories you can reuse everywhere.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2.5">
                <button
                  type="button"
                  data-testid="empty-import-resume"
                  onClick={() => void extract()}
                  disabled={running}
                  className="rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  <i className="fa-solid fa-file-import mr-1.5" aria-hidden="true" />
                  {running ? "Extracting…" : "Import from Resume"}
                </button>
                <button
                  type="button"
                  disabled
                  title="Portfolio import lands in a later phase"
                  className="cursor-not-allowed rounded-xl border border-white/10 bg-white/8 px-4 py-2.5 text-sm font-medium opacity-50"
                >
                  <i className="fa-solid fa-briefcase mr-1.5" aria-hidden="true" />
                  Import from Portfolio
                </button>
                <button
                  type="button"
                  data-testid="empty-add-manual"
                  onClick={openCreate}
                  className="rounded-xl border border-white/10 bg-white/8 px-4 py-2.5 text-sm font-medium transition hover:bg-white/12"
                >
                  <i className="fa-solid fa-plus mr-1.5" aria-hidden="true" />
                  Add Manually
                </button>
              </div>
            </div>
          ) : visible.length === 0 ? (
            <div className="glass rounded-2xl border border-white/10 p-10 text-center text-sm text-aether-muted">
              No stories in “{filter}”. Try another category.
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {visible.map((story) => (
                <StoryCard
                  key={story.id}
                  story={story}
                  isEditing={editingId === story.id}
                  isFavourite={favourites.has(story.id)}
                  onToggleFavourite={() => toggleFavourite(story.id)}
                  onEdit={() => {
                    setEditingId(story.id);
                    setCreating(false);
                  }}
                  onCancelEdit={() => setEditingId(null)}
                  onSaveEdit={(input) => saveEdit(story.id, input)}
                  onDelete={() => void remove(story.id)}
                />
              ))}
            </div>
          )}
        </section>

        <StoryInsights stories={stories ?? []} onDraftMissing={openCreate} />
      </div>
    </div>
  );
}
