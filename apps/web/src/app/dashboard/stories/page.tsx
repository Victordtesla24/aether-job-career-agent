"use client";

/**
 * Story Bank — STAR stories extracted from the base resume with evidence-backed
 * metrics. Backed by GET /stories and POST /agents/story-extractor/run.
 */
import { useCallback, useEffect, useState } from "react";

import { deleteStory, fetchStories, runStoryExtractor, type Story } from "../../../lib/api/stories";

export default function StoryBankPage() {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [running, setRunning] = useState(false);
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

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Story Bank</h1>
          <p className="text-sm text-aether-muted">
            STAR stories mined from your resume — metrics must trace to evidence.
          </p>
        </div>
        <button
          type="button"
          data-testid="run-extractor-btn"
          onClick={() => void extract()}
          disabled={running}
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {running ? "Extracting..." : "Extract Stories"}
        </button>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
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
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-semibold">{story.title}</h2>
                <button
                  type="button"
                  onClick={() => void remove(story.id)}
                  className="text-xs text-aether-muted-dim hover:text-red-300"
                  title="Delete story"
                >
                  ✕
                </button>
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
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
