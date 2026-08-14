// @vitest-environment jsdom
/**
 * S-UI-B2 regression guard — ML-SUI-B2-CRUSH-01.
 *
 * THE DEFECT. B2 gave each kanban column its own scroll container so the board
 * would stop stretching the document to 6,598px (X-1 / D-ε). The column body is
 *
 *     display:flex; flex-direction:column;  max-height: <BOARD_COLUMN_VIEWPORT>
 *
 * and every card is therefore a FLEX ITEM. A flex item's initial `flex-shrink`
 * is `1`, so once the cards' natural height exceeded the column the browser
 * COMPRESSED every card to fit instead of letting the column scroll — and
 * because the `listCard` recipe carries `overflow-hidden`, the compressed cards
 * clipped their own contents.
 *
 * What it looked like in production-shaped data: the deep columns (Evaluating
 * 3,642 rows, Ready to Apply 253, Submitted) rendered every card as a ~100px
 * sliver with the job title and company sliced through the middle of the
 * glyphs, while the shallow columns (Tailoring 6, Discovered 7) looked correct
 * because they never had to shrink. That asymmetry is what makes this class of
 * bug survive review: the screen looks fine exactly where a reviewer with a
 * small test fixture would look.
 *
 * WHY THIS TEST IS A CLASS ASSERTION, NOT A PIXEL ASSERTION. jsdom has no
 * layout engine — `getBoundingClientRect()` is all zeroes and `flex-shrink`
 * resolves nothing — so a height-based assertion here would pass no matter how
 * broken the CSS is. The honest, mechanically-checkable contract is therefore
 * the one the repo already uses for this exact situation (see
 * `analytics/__tests__/roi-mobile-grid.test.tsx`, which asserts on
 * `grid-cols-3` rather than on measured columns): assert the class that governs
 * the behaviour, and state in the test why that class is the contract.
 *
 * The guard is deliberately two-sided:
 *   1. every card must be non-shrinking, and
 *   2. the column body must still be the scroll container it claims to be.
 * Removing `shrink-0` re-crushes the cards; removing `overflow-y-auto` makes
 * the column overflow its band instead of scrolling. Either alone reopens the
 * defect, so both are asserted.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

/**
 * Enough pipeline jobs that a real browser would have to shrink them: the
 * board caps a column at 25 cards, so 25 is the worst case the UI can produce.
 */
const PIPELINE_JOBS = Array.from({ length: 25 }, (_, i) => ({
  id: `pipeline-job-${i}`,
  title: `Senior Platform Engineer, Distributed Systems ${i}`,
  company: `Sourced Co ${i}`,
  location: "Melbourne, VIC",
  remote: true,
  description: "",
  requirements: [],
  source: "seek",
  sourceUrl: null,
  status: "discovered",
  fitScore: 62,
  atsScore: 58,
  saved: false,
  postedAt: null,
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:00:00Z",
}));

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("Kanban column scroll containment (ML-SUI-B2-CRUSH-01)", () => {
  it("cards never shrink to fit the column — the column scrolls instead", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [];
      if (path === "/jobs") return PIPELINE_JOBS;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    const cards = screen.getAllByTestId("application-card");
    expect(cards.length).toBeGreaterThan(0);

    for (const card of cards) {
      const classes = card.className.split(/\s+/);
      expect(
        classes.includes("shrink-0") || classes.includes("flex-none"),
        "a kanban card is a flex item in a max-height column; without shrink-0 the " +
          "browser compresses it and listCard's overflow-hidden clips the title",
      ).toBe(true);
    }

    // The other half of the contract: the body the cards sit in is genuinely a
    // scroll container, so not-shrinking produces scrolling rather than spill.
    const body = cards[0].parentElement as HTMLElement;
    const bodyClasses = body.className.split(/\s+/);
    expect(bodyClasses).toContain("overflow-y-auto");
    expect(bodyClasses).toContain("flex-col");
    expect(body.style.maxHeight).not.toBe("");
  });
});
