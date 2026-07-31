// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §11.2 / W-I items 1, 2, 4 — Story Bank realtime + mutation
 * honesty, /dashboard/stories.
 *
 * MEASURED ground truth (window.fetch instrumentation, this run):
 * /dashboard/stories has NO polling at all — a single `load()` call on
 * mount/filter-change, confirmed by reading `page.tsx`'s single
 * `useEffect(() => { void load(filter); }, [filter, load])` with no
 * `setInterval` anywhere in the file. §11.2 requires every screen to
 * auto-refresh at <= 20s via a shared `usePolling` hook. This is the
 * representative "currently-non-polling screen" the W-I brief asked for.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Story, StoryStats } from "../../../../lib/api/stories";

const fetchStoriesMock = vi.hoisted(() => vi.fn());
const fetchStoryStatsMock = vi.hoisted(() => vi.fn());
const toggleStarMock = vi.hoisted(() => vi.fn());
const runStoryExtractorMock = vi.hoisted(() => vi.fn());
const deleteStoryMock = vi.hoisted(() => vi.fn());
const createStoryMock = vi.hoisted(() => vi.fn());
const updateStoryMock = vi.hoisted(() => vi.fn());

vi.mock("../../../../lib/api/stories", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/stories")>();
  return {
    ...actual,
    fetchStories: (...args: unknown[]) => fetchStoriesMock(...args),
    fetchStoryStats: (...args: unknown[]) => fetchStoryStatsMock(...args),
    toggleStar: (...args: unknown[]) => toggleStarMock(...args),
    runStoryExtractor: (...args: unknown[]) => runStoryExtractorMock(...args),
    deleteStory: (...args: unknown[]) => deleteStoryMock(...args),
    createStory: (...args: unknown[]) => createStoryMock(...args),
    updateStory: (...args: unknown[]) => updateStoryMock(...args),
  };
});

// eslint-disable-next-line import/first
import StoryBankPage from "../page";

function story(overrides: Partial<Story> = {}): Story {
  return {
    id: "story-1",
    title: "Led migration",
    situation: "Legacy system at risk",
    task: "Modernise without downtime",
    action: "Phased cutover with rollback plan",
    result: "Zero downtime, 40% cost cut",
    metrics: { costCutPct: 40 },
    tags: ["leadership"],
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    category: "Leadership",
    impact: "40% cost cut",
    starred: false,
    ...overrides,
  };
}

const STATS: StoryStats = { total: 1, quantified: 1, starred: 0, categories: 1 };

beforeEach(() => {
  fetchStoriesMock.mockResolvedValue([story()]);
  fetchStoryStatsMock.mockResolvedValue(STATS);
});

afterEach(() => {
  cleanup();
  fetchStoriesMock.mockReset();
  fetchStoryStatsMock.mockReset();
  toggleStarMock.mockReset();
  runStoryExtractorMock.mockReset();
  deleteStoryMock.mockReset();
  createStoryMock.mockReset();
  updateStoryMock.mockReset();
});

describe("W-I item 1 — shared usePolling hook adoption (§11.2)", () => {
  it("imports and uses the canonical shared usePolling hook instead of an ad-hoc setInterval", () => {
    const pageSource = readFileSync(join(__dirname, "../page.tsx"), "utf8");
    // Every other polling screen in this repo hand-rolls its own
    // setInterval (sidebar 30s, topbar 60s, applications/jobs 20s). §11.2
    // asks for ONE shared hook instead. Story Bank currently has neither —
    // proving that even after a hook exists elsewhere, screens are not
    // required to adopt it.
    expect(pageSource).toMatch(/usePolling/);
  });
});

describe("W-I item 2 — realtime cadence on a representative non-polling screen (§11.2, <=20s)", () => {
  it("registers a periodic refresh timer at an interval of 20s or less", () => {
    // IMPORTANT: this must NOT use `waitFor`/`findBy*` before inspecting the
    // spy — @testing-library/dom's `waitFor` registers its OWN internal
    // setInterval (default 50ms poll) as a fallback alongside its
    // MutationObserver, which would make this assertion pass for the wrong
    // reason (it did, on a first draft of this test: the spy caught
    // testing-library's polling, not the app's). `render()` already flushes
    // mount-time effects synchronously via `act`, and `load(filter)`'s first
    // statement calls `fetchStories(...)` synchronously (before its first
    // `await`), so no waiting is needed to observe either call.
    const setIntervalSpy = vi.spyOn(window, "setInterval");

    render(<StoryBankPage />);
    expect(fetchStoriesMock).toHaveBeenCalledTimes(1);

    // §11.2: "all screens auto-refresh at <= 20s". Story Bank currently
    // never calls setInterval (or any other periodic mechanism) at all —
    // it is a pure load-once-on-mount screen, matching the MEASURED ground
    // truth ("NO polling at all: /dashboard/stories, ...").
    expect(setIntervalSpy).toHaveBeenCalled();
    const intervalArgs = setIntervalSpy.mock.calls.map((call) => call[1]);
    expect(intervalArgs.some((ms) => typeof ms === "number" && ms <= 20_000)).toBe(true);

    setIntervalSpy.mockRestore();
  });
});

describe("W-I item 4 — optimistic update + honest rollback (Story Bank star toggle)", () => {
  // Mutation surface under test: StoryBankPage.star() (page.tsx `const star =
  // async (story) => { try { const updated = await toggleStar(story); ... }`).
  // Chosen because it is a single, self-contained boolean toggle with an
  // unambiguous rendered signal (`aria-pressed` on [data-testid="star-story-btn"]),
  // making "did the UI update before or after the network call resolved"
  // trivial to observe without racing on unrelated state.
  it("flips the star immediately on click, before the network call resolves (optimistic update)", async () => {
    let resolveToggle!: (value: Story) => void;
    toggleStarMock.mockImplementation(
      () =>
        new Promise<Story>((resolve) => {
          resolveToggle = resolve;
        }),
    );

    render(<StoryBankPage />);
    const btn = await screen.findByTestId("star-story-btn");
    expect(btn.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(btn);

    // Flush the microtask queue up to (but not past) the pending
    // `await toggleStar(story)` inside page.tsx's `star()` handler. If the
    // component set local state optimistically BEFORE awaiting the network
    // call, this would already be "true" here.
    await Promise.resolve();
    await Promise.resolve();

    // §11.2: "mutations update the UI IMMEDIATELY (optimistic)". The
    // current handler does `const updated = await toggleStar(story); setStories(...)`
    // — nothing is set until the network call resolves, so this fails: the
    // button is still unpressed even though the user already clicked it.
    expect(btn.getAttribute("aria-pressed")).toBe("true");

    // Let the pending mock resolve so no unhandled state update leaks into
    // the next test.
    resolveToggle(story({ starred: true }));
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("true"));
  });

  it("on a failed toggle, never leaves the UI silently showing the un-persisted state (honest error, no silent success)", async () => {
    toggleStarMock.mockRejectedValue(new Error("network error"));

    render(<StoryBankPage />);
    const btn = await screen.findByTestId("star-story-btn");
    fireEvent.click(btn);

    // The failure path must surface an honest, visible error — never a
    // silent no-op that leaves the user unsure whether the click "took".
    // page.tsx: `setError(e instanceof Error ? e.message : "Failed to update story")`
    // — the mock rejects with `new Error("network error")`, so that's the
    // exact string that must render.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/network error/i);
    // And because there was no optimistic flip in the first place (see the
    // test above), there is nothing to roll back — the button stays
    // unpressed, which is only "honest" by accident (the immediate-update
    // half of the requirement is what's actually broken).
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });
});
