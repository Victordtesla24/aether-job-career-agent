"use client";

/**
 * Story Bank — Achievement & Narrative Library. Reusable STAR+R evidence blocks
 * that power resumes, cover letters and interview answers. Backed by
 * GET/POST/PUT/DELETE /stories, GET /stories/stats and
 * POST /agents/story-extractor/run. Layout mirrors design/screens/story-bank.html.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { StoryAside } from "../../../components/stories/story-aside";
import { StoryCard } from "../../../components/stories/story-card";
import { EMPTY_STORY_FORM, StoryForm } from "../../../components/stories/story-form";
import {
  createStory,
  deleteStory,
  fetchStories,
  fetchStoryStats,
  runStoryExtractor,
  toggleStar,
  updateStory,
  type Story,
  type StoryInput,
  type StoryStats,
} from "../../../lib/api/stories";

const FILTERS = ["All", "Leadership", "Delivery", "Technical", "Risk & Compliance"] as const;
type Filter = (typeof FILTERS)[number];

const ZERO_STATS: StoryStats = { total: 0, quantified: 0, starred: 0, categories: 0 };

export default function StoryBankPage() {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [stats, setStats] = useState<StoryStats | null>(null);
  const [filter, setFilter] = useState<Filter>("All");
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demoEmpty, setDemoEmpty] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && window.location.search.includes("demo=empty")) {
      setDemoEmpty(true);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const [list, statsResp] = await Promise.all([
        fetchStories(),
        fetchStoryStats().catch(() => null),
      ]);
      setStories(list);
      setStats(statsResp);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stories");
      setStories([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const effectiveStories = useMemo(
    () => (demoEmpty ? [] : (stories ?? [])),
    [demoEmpty, stories],
  );
  const effectiveStats = useMemo<StoryStats>(() => {
    if (demoEmpty) return ZERO_STATS;
    if (stats) return stats;
    if (!stories) return ZERO_STATS;
    return {
      total: stories.length,
      quantified: stories.filter((s) => s.metrics && Object.keys(s.metrics).length > 0).length,
      starred: stories.filter((s) => s.starred).length,
      categories: new Set(stories.map((s) => s.category ?? "")).size,
    };
  }, [demoEmpty, stats, stories]);

  const visibleStories = useMemo(
    () =>
      filter === "All"
        ? effectiveStories
        : effectiveStories.filter((s) => s.category === filter),
    [effectiveStories, filter],
  );

  const extract = async () => {
    setRunning(true);
    setError(null);
    try {
      await runStoryExtractor();
      setDemoEmpty(false);
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
      setStats(null);
      void load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete story");
    }
  };

  const create = async (input: StoryInput) => {
    const story = await createStory(input);
    setStories((prev) => [story, ...(prev ?? [])]);
    setCreating(false);
    setDemoEmpty(false);
    void load();
  };

  const saveEdit = async (id: string, input: StoryInput) => {
    const updated = await updateStory(id, input);
    setStories((prev) => (prev ?? []).map((s) => (s.id === id ? updated : s)));
    setEditingId(null);
  };

  const star = async (story: Story) => {
    try {
      const updated = await toggleStar(story);
      setStories((prev) => (prev ?? []).map((s) => (s.id === story.id ? updated : s)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update story");
    }
  };

  const openCreate = () => {
    setCreating(true);
    setEditingId(null);
    setDemoEmpty(false);
  };

  const showEmpty = stories !== null && effectiveStories.length === 0;

  return (
    <div className="space-y-7">
      {/* Header */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[13px] text-aether-muted">
            <i className="fa-solid fa-book-bookmark text-aether-coral" aria-hidden="true" />
            Story Bank
          </div>
          <h1 className="text-2xl font-bold">Achievement &amp; Narrative Library</h1>
          <p className="mt-1 text-sm text-aether-muted">
            Reusable STAR+R evidence blocks that power your resumes, cover letters and interview answers.
          </p>
        </div>
        <button
          type="button"
          data-testid="add-story-btn"
          onClick={openCreate}
          className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-aether-bg transition hover:bg-[#ff7d4d] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
        >
          <i className="fa-solid fa-plus" aria-hidden="true" />
          New Story
        </button>
      </header>

      {/* Stat strip */}
      <section
        className="grid grid-cols-2 gap-4 lg:grid-cols-4"
        data-testid="story-stats"
        aria-label="Story bank statistics"
      >
        {(
          [
            ["Total Stories", effectiveStats.total, ""],
            ["Quantified w/ Metrics", effectiveStats.quantified, "text-[#34D399]"],
            ["Starred", effectiveStats.starred, "text-[#FBBF24]"],
            ["Categories Covered", effectiveStats.categories, "text-[#A78BFA]"],
          ] as const
        ).map(([label, value, cls]) => (
          <div key={label} className="glass rounded-2xl border border-white/10 p-4">
            <div className="mb-1 text-[11px] text-aether-muted">{label}</div>
            <div className={`mono text-2xl font-bold ${cls}`}>{value}</div>
          </div>
        ))}
      </section>

      {error ? (
        <p
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
        >
          {error}
        </p>
      ) : null}

      {creating ? (
        <div
          className="glass rounded-2xl border border-aether-coral/30 p-5"
          data-testid="create-story-panel"
        >
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
        {/* Left: filters + story list */}
        <section className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter stories by category">
            {FILTERS.map((f) => {
              const active = filter === f;
              return (
                <button
                  key={f}
                  type="button"
                  data-testid={`filter-${f.toLowerCase().replace(/[^a-z]+/g, "-")}`}
                  aria-pressed={active}
                  onClick={() => setFilter(f)}
                  className={`min-h-[36px] rounded-lg px-3 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40 ${
                    active
                      ? "bg-white/10 text-white"
                      : "text-aether-muted hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {f}
                </button>
              );
            })}
          </div>

          {stories === null ? (
            <div className="space-y-4" aria-busy="true" data-testid="stories-loading">
              {[0, 1, 2].map((i) => (
                <div key={i} className="glass h-44 animate-pulse rounded-2xl border border-white/10" />
              ))}
            </div>
          ) : showEmpty ? (
            <div
              className="rounded-2xl border border-dashed border-white/15 p-10 text-center"
              data-testid="stories-empty-state"
            >
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-[#FF6B35]/25 bg-[#FF6B35]/12">
                <i className="fa-solid fa-book-bookmark text-xl text-aether-coral" aria-hidden="true" />
              </div>
              <h3 className="mb-1.5 text-base font-semibold">Your Story Bank is empty</h3>
              <p className="mx-auto mb-5 max-w-md text-sm text-aether-muted">
                Import achievements from your resume and portfolio to build your interview arsenal.
                Aether will auto-extract STAR+R stories you can reuse everywhere.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2.5">
                <button
                  type="button"
                  data-testid="empty-import-resume"
                  onClick={() => void extract()}
                  disabled={running}
                  className="min-h-[44px] rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-aether-bg transition hover:bg-[#ff7d4d] disabled:opacity-50"
                >
                  <i className="fa-solid fa-file-import mr-1.5" aria-hidden="true" />
                  {running ? "Importing…" : "Import from Resume"}
                </button>
                <button
                  type="button"
                  data-testid="empty-import-portfolio"
                  onClick={openCreate}
                  className="min-h-[44px] rounded-xl border border-white/10 bg-white/8 px-4 py-2.5 text-sm font-medium transition hover:bg-white/12"
                >
                  <i className="fa-solid fa-briefcase mr-1.5" aria-hidden="true" />
                  Import from Portfolio
                </button>
                <button
                  type="button"
                  data-testid="empty-add-manual"
                  onClick={openCreate}
                  className="min-h-[44px] rounded-xl border border-white/10 bg-white/8 px-4 py-2.5 text-sm font-medium transition hover:bg-white/12"
                >
                  <i className="fa-solid fa-plus mr-1.5" aria-hidden="true" />
                  Add Manually
                </button>
              </div>
            </div>
          ) : visibleStories.length === 0 ? (
            <div
              className="rounded-2xl border border-dashed border-white/15 p-8 text-center text-sm text-aether-muted"
              data-testid="stories-filter-empty"
            >
              No stories in <span className="font-semibold text-white">{filter}</span> yet.
            </div>
          ) : (
            <div className="space-y-4" data-testid="story-list">
              {visibleStories.map((story) => (
                <StoryCard
                  key={story.id}
                  story={story}
                  editing={editingId === story.id}
                  onStartEdit={() => {
                    setEditingId(story.id);
                    setCreating(false);
                  }}
                  onCancelEdit={() => setEditingId(null)}
                  onSave={(input) => saveEdit(story.id, input)}
                  onDelete={() => void remove(story.id)}
                  onToggleStar={() => void star(story)}
                />
              ))}
            </div>
          )}
        </section>

        {/* Right: insights aside */}
        <StoryAside
          stories={effectiveStories}
          drafting={running}
          onDraftMissing={() => void extract()}
        />
      </div>
    </div>
  );
}
