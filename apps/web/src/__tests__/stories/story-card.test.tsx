// @vitest-environment jsdom
/**
 * MV-story-bank-003 / MV-story-bank-002 — StoryCard destructive-action and
 * long-input layout-containment coverage.
 *
 * - MV-story-bank-003: deleting a story is a permanent, unrecoverable action
 *   (no undo). The trash-can control must gate the DELETE call behind an
 *   explicit confirmation instead of firing immediately on click.
 * - MV-story-bank-002: a STAR field with a single long unbroken token (no
 *   whitespace) must never be allowed to size the surrounding grid/flex
 *   layout to its intrinsic content width — it needs both wrap-safe text CSS
 *   and a `min-width: 0` escape hatch on its grid/flex ancestor (the CSS
 *   Grid/Flexbox default `min-width: auto` is exactly what let a 15-20k char
 *   blob balloon `document.documentElement.scrollWidth` to ~180,000px in
 *   production).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StoryCard } from "../../components/stories/story-card";
import type { Story } from "../../lib/api/stories";

const STORY: Story = {
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
};

const noop = () => {
  /* no-op */
};

function renderCard(story: Story, onDelete: () => void) {
  return render(
    <StoryCard
      story={story}
      editing={false}
      onStartEdit={noop}
      onCancelEdit={noop}
      onSave={async () => {
        /* not exercised in these tests */
      }}
      onDelete={onDelete}
      onToggleStar={noop}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("StoryCard — delete requires confirmation (MV-story-bank-003)", () => {
  it("does NOT delete when the user cancels the confirmation", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onDelete = vi.fn();
    renderCard(STORY, onDelete);

    fireEvent.click(screen.getByTestId("delete-story-btn"));

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("deletes only after the user confirms", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onDelete = vi.fn();
    renderCard(STORY, onDelete);

    fireEvent.click(screen.getByTestId("delete-story-btn"));

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});

describe("StoryCard — long unbroken string cannot blow out the layout (MV-story-bank-002)", () => {
  it("renders STAR field text with wrap-safe CSS inside a min-w-0 ancestor", () => {
    const hugeUnbrokenString = "A".repeat(500);
    const story: Story = { ...STORY, situation: hugeUnbrokenString };
    renderCard(story, noop);

    const situationText = screen.getByText(hugeUnbrokenString);
    // overflow-wrap containment on the paragraph itself: without this, a
    // single unbreakable token expands to its full intrinsic width.
    expect(situationText.className).toMatch(/break-words|break-all/);
    // CSS Grid/Flexbox items default to `min-width: auto` (content-based) —
    // without an explicit min-w-0 override, wrap CSS alone does not stop the
    // grid track (and therefore the whole page) from stretching to fit.
    expect(situationText.parentElement?.className).toMatch(/\bmin-w-0\b/);
  });
});
