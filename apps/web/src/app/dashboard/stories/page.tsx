"use client";

/**
 * Story Bank — Achievement & Narrative Library. Reusable STAR+R evidence blocks
 * that power resumes, cover letters and interview answers. Backed by
 * GET/POST/PUT/DELETE /stories, GET /stories/stats and
 * POST /agents/story-extractor/run. Layout mirrors design/screens/story-bank.html.
 *
 * S-UI B3 (presentation only).
 * --------------------------
 * Two things were measured on production 2026-08-14 and both are fixed here
 * without touching a single request (evidence: b3/before/before-notes.json,
 * b3/diagnosis/STORY-BANK-SECTION-NOT-FOUND.md):
 *
 * 1. **"Section not found"** — NOT a defect of this page. `/dashboard/stories`
 *    renders correctly and the sidebar links to it; the report came from the
 *    WIREFRAME name `/dashboard/story-bank`, which fell through to the
 *    `[...slug]` catch-all. That dead end is fixed in the catch-all itself,
 *    which now names the section a near-miss meant (`lib/navigation-suggest.ts`).
 * 2. **9,071 px tall at 1600 / 18,216 px at 390** — every card printed all four
 *    STAR fields in full. The cards now clamp to three lines each and the full
 *    story opens in an `elev-3` sheet (§5.8 / X-2), so the page ends (D-ε).
 *
 * ARCHIVE / RESTORE / DEDUP: those surfaces belong to the U-STORY workstream
 * and are not on `main` at this commit (`grep -rn "archive\|restore\|dedup"
 * src/components/stories src/lib/api/stories.ts` → no hits). Nothing of theirs
 * was removed here; when they land they slot into the same card footer and the
 * same sheet.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { usePolling } from "../../../hooks/usePolling";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import { extractorTriggerState } from "../../../components/stories/logic";
import { StoryAside } from "../../../components/stories/story-aside";
import { StoryCard } from "../../../components/stories/story-card";
import { StorySheet } from "../../../components/stories/story-sheet";
import { EMPTY_STORY_FORM, StoryForm } from "../../../components/stories/story-form";
import PageHeader from "../../../components/shell/PageHeader";
import SegmentedControl from "../../../components/ui/SegmentedControl";
import Section from "../../../components/ui/Section";
import { button } from "../../../components/ui/recipes";
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
  /** Presentation-only: which story the `elev-3` read sheet is showing. */
  const [readingId, setReadingId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined" && window.location.search.includes("demo=empty")) {
      setDemoEmpty(true);
    }
  }, []);

  const load = useCallback(async (category?: string) => {
    try {
      const [list, statsResp] = await Promise.all([
        fetchStories(category && category !== "All" ? { category } : {}),
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

  // GOLD-MASTER-V2 §11.2 / W-I item 1+2: shared polling hook instead of a
  // bespoke `setInterval` — fires immediately on mount/filter change (via
  // restartKey) and re-fetches every 20s so this screen is no longer
  // load-once (ML-realtime gap).
  usePolling(() => load(filter), 20_000, { restartKey: filter });

  // W-RT — the shared realtime channel, on top of that poll: a story written by
  // the story agent now appears as soon as the server observes the row instead
  // of up to 20s later. The poll stays as the fallback for when the stream is
  // not connected; the status badge says which one is carrying the screen.
  useRealtimeResources(["stories"], () => {
    void load(filter);
  });

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
    // GOLD-MASTER-V2 §11.2 / W-I item 4: flip immediately (optimistic) so
    // the click feels instant, then reconcile with the server response; on
    // failure roll back to the exact prior snapshot and surface an honest
    // error — never leave the UI silently showing an un-persisted change.
    const previous = stories;
    setStories((prev) =>
      (prev ?? []).map((s) => (s.id === story.id ? { ...s, starred: !s.starred } : s)),
    );
    try {
      const updated = await toggleStar(story);
      setStories((prev) => (prev ?? []).map((s) => (s.id === story.id ? updated : s)));
    } catch (e) {
      setStories(previous);
      setError(e instanceof Error ? e.message : "Failed to update story");
    }
  };

  const openCreate = useCallback(() => {
    setCreating(true);
    setEditingId(null);
    setDemoEmpty(false);
  }, []);

  const closeCreate = useCallback(() => setCreating(false), []);

  const showEmpty = stories !== null && effectiveStories.length === 0;
  const importResumeState = extractorTriggerState(running, "Import from Resume", "Importing…");
  const reading = visibleStories.find((s) => s.id === readingId) ?? null;

  /** Per-category counts for the segmented control — computed from the list
   *  already in hand, never a second request. */
  const filterItems = useMemo(
    () =>
      FILTERS.map((f) => ({
        value: f,
        label: f,
        count:
          f === "All"
            ? effectiveStories.length
            : effectiveStories.filter((s) => s.category === f).length,
      })),
    [effectiveStories],
  );

  return (
    <div className="space-y-5">
      <div className="mb-1 flex items-center gap-2 text-[13px] text-aether-muted">
        <i className="fa-solid fa-book-bookmark text-aether-coral" aria-hidden="true" />
        Story Bank
      </div>
      <PageHeader
        title="Achievement & Narrative Library"
        subtitle="Reusable STAR+R evidence blocks that power your resumes, cover letters and interview answers."
        action={
          <button
            type="button"
            data-testid="add-story-btn"
            onClick={openCreate}
            className={button({ tone: "primary", size: "md", class: "h-10 text-aether-bg" })}
          >
            <i className="fa-solid fa-plus" aria-hidden="true" />
            New Story
          </button>
        }
      />

      {/* Stat strip */}
      <section
        className="grid grid-cols-2 gap-3 lg:grid-cols-4"
        data-testid="story-stats"
        aria-label="Story bank statistics"
      >
        {(
          [
            ["Total Stories", effectiveStats.total, "text-aether-text"],
            ["Quantified w/ Metrics", effectiveStats.quantified, "text-state-ok"],
            ["Starred", effectiveStats.starred, "text-aether-coral"],
            ["Categories Covered", effectiveStats.categories, "text-state-info"],
          ] as const
        ).map(([label, value, cls]) => (
          <div key={label} className="elev-1 rounded-xl px-4 py-3">
            <div className="type-section">{label}</div>
            <div className={`mono mt-1.5 text-2xl font-bold leading-none ${cls}`}>{value}</div>
          </div>
        ))}
      </section>

      {error ? (
        <p
          role="alert"
          className="rounded-xl border border-state-danger/30 bg-state-danger/10 p-3 text-sm text-state-danger"
        >
          {error}
        </p>
      ) : null}

      {creating ? (
        <Section eyebrow="New story" testId="create-story-panel" accent>
          <StoryForm
            initial={EMPTY_STORY_FORM}
            submitLabel="Create Story"
            onSubmit={create}
            onCancel={closeCreate}
          />
        </Section>
      ) : null}

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        {/* Left: filters + story list */}
        <section className="min-w-0 flex-1 space-y-4">
          <SegmentedControl
            items={filterItems}
            value={filter}
            onChange={setFilter}
            ariaLabel="Filter stories by category"
            idPrefix="story-filter"
            size="sm"
            testIdFor={(f) => `filter-${f.toLowerCase().replace(/[^a-z]+/g, "-")}`}
          />

          {stories === null ? (
            <div className="space-y-3" aria-busy="true" data-testid="stories-loading">
              {[0, 1, 2].map((i) => (
                <div key={i} className="elev-1 h-40 animate-pulse rounded-[14px]" />
              ))}
            </div>
          ) : showEmpty ? (
            <div
              className="rounded-[14px] border border-dashed border-hairline-strong p-10 text-center"
              data-testid="stories-empty-state"
            >
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-[10px] border border-aether-coral/25 bg-aether-coral/[0.12]">
                <i className="fa-solid fa-book-bookmark text-xl text-aether-coral" aria-hidden="true" />
              </div>
              <h3 className="mb-1.5 text-base font-semibold">Your Story Bank is empty</h3>
              <p className="mx-auto mb-5 max-w-md text-sm text-aether-muted">
                Import achievements from your resume to build your interview arsenal. Aether will
                auto-extract STAR+R stories you can reuse everywhere.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2.5">
                <button
                  type="button"
                  data-testid="empty-import-resume"
                  onClick={() => void extract()}
                  disabled={importResumeState.disabled}
                  aria-busy={running}
                  className={button({
                    tone: "primary",
                    size: "md",
                    class: "min-h-[44px] text-aether-bg",
                  })}
                >
                  <i className="fa-solid fa-file-import" aria-hidden="true" />
                  {importResumeState.label}
                </button>
                <button
                  type="button"
                  data-testid="empty-add-manual"
                  onClick={openCreate}
                  className={button({ tone: "neutral", size: "md", class: "min-h-[44px]" })}
                >
                  <i className="fa-solid fa-plus" aria-hidden="true" />
                  Add Manually
                </button>
              </div>
            </div>
          ) : visibleStories.length === 0 ? (
            <div
              className="rounded-[14px] border border-dashed border-hairline-strong p-8 text-center text-sm text-aether-muted"
              data-testid="stories-filter-empty"
            >
              No stories in <span className="font-semibold text-aether-text">{filter}</span> yet.
            </div>
          ) : (
            /* D-ε: the list scrolls inside its own container so the page ends.
               Before this batch 20 stories made the document 9,071px tall. */
            <div
              className="max-h-[calc(100vh-320px)] space-y-3 overflow-y-auto overscroll-contain pr-1"
              data-testid="story-list"
            >
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
                  onRead={() => setReadingId(story.id)}
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

      <StorySheet story={reading} onClose={() => setReadingId(null)} />
    </div>
  );
}
