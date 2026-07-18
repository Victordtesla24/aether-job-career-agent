// @vitest-environment jsdom
/**
 * MV-story-bank-008 — Interview Question Mapper (StoryAside) must truncate
 * `match.title` the same way the story-card header already truncates
 * `story.title` (MV-story-bank-002 sibling fix). Without a truncate/ellipsis
 * treatment, a long unbroken story title renders in full and can overflow
 * its fixed-width card, risking the same page-wide layout blowout that
 * MV-story-bank-002 fixed on the STAR fields.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StoryAside } from "../../components/stories/story-aside";
import type { Story } from "../../lib/api/stories";

const noop = () => {
  /* no-op */
};

function makeStory(overrides: Partial<Story>): Story {
  return {
    id: "cstory00000000000000000001",
    title: "Reduced onboarding time by 47%",
    situation: "New hires took 6 weeks to reach full productivity.",
    task: "Redesign the onboarding program end to end.",
    action: "Built a self-serve onboarding portal with guided checklists.",
    result: "Ramp time dropped from 6 weeks to 3 weeks.",
    metrics: {},
    tags: ["Delivery"],
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    category: "Delivery",
    starred: false,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("StoryAside — Interview Question Mapper title truncation (MV-story-bank-008)", () => {
  it("truncates a long unbroken matched story title instead of rendering it in full", () => {
    const hugeUnbrokenTitle = "A".repeat(500);
    const story = makeStory({ title: hugeUnbrokenTitle, category: "Delivery" });

    render(<StoryAside stories={[story]} onDraftMissing={noop} />);

    // A single story becomes the "best match" for every mapper question
    // (bestStory() falls back to the full story list when no category
    // matches), so the title renders more than once — assert every
    // occurrence is truncated.
    const titleEls = screen.getAllByText(hugeUnbrokenTitle);
    expect(titleEls.length).toBeGreaterThan(0);
    for (const titleEl of titleEls) {
      // Tailwind's `truncate` = overflow:hidden + text-overflow:ellipsis +
      // white-space:nowrap — the same class the already-fixed story-card
      // header (h3.truncate, MV-story-bank-002) uses for story.title.
      expect(titleEl.className).toMatch(/\btruncate\b/);
      // Flexbox/Grid items default to `min-width: auto` (content-sized), so
      // truncate alone does not stop the row from stretching — an explicit
      // min-w-0 escape hatch is required (mirrors story-card.tsx's pattern).
      expect(titleEl.className).toMatch(/\bmin-w-0\b/);
    }
  });
});
