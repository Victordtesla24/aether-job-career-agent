// @vitest-environment jsdom
/**
 * MV-story-bank-001 — the Story Bank empty state must not offer a control
 * that claims to do something it doesn't. "Import from Portfolio" fired zero
 * network requests and silently opened the identical blank manual-entry form
 * as "Add Manually" — there is no portfolio/GitHub import pipeline wired to
 * this screen. The fix removes the misleading control; "Import from Resume"
 * (a real POST /agents/story-extractor/run trigger) and "Add Manually" (the
 * real, honestly-labeled manual form) remain.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchStoriesMock = vi.hoisted(() => vi.fn());
const fetchStoryStatsMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/stories", async () => {
  const actual =
    await vi.importActual<typeof import("../../lib/api/stories")>("../../lib/api/stories");
  return {
    ...actual,
    fetchStories: fetchStoriesMock,
    fetchStoryStats: fetchStoryStatsMock,
  };
});

import StoryBankPage from "../../app/dashboard/stories/page";

afterEach(() => {
  cleanup();
  fetchStoriesMock.mockReset();
  fetchStoryStatsMock.mockReset();
});

describe("Story Bank empty state — honest controls only (MV-story-bank-001)", () => {
  it("does not render a misleading 'Import from Portfolio' button", async () => {
    fetchStoriesMock.mockResolvedValue([]);
    fetchStoryStatsMock.mockResolvedValue({ total: 0, quantified: 0, starred: 0, categories: 0 });

    render(<StoryBankPage />);

    await waitFor(() => expect(screen.getByTestId("stories-empty-state")).toBeTruthy());
    // The two real, honest entry points remain...
    expect(screen.getByTestId("empty-import-resume")).toBeTruthy();
    expect(screen.getByTestId("empty-add-manual")).toBeTruthy();
    // ...but the no-op "import" control that only opened a blank form is gone.
    expect(screen.queryByTestId("empty-import-portfolio")).toBeNull();
    expect(screen.queryByText(/import from portfolio/i)).toBeNull();
  });
});
