// @vitest-environment jsdom
/**
 * §22 STEP 2 (GOLD-MASTER-V4) — GMV4-apps-004 (HIGH), failing-test evidence.
 *
 * An adversarial reviewer found the Applications kanban drag-and-drop fires
 * NO request and moves nothing on a genuine (real mouse gesture) drag. This
 * corrects an earlier tester who reported DnD "working" — that result came
 * only from a synthetic Playwright `new DragEvent(...)` dispatched directly
 * at the handlers, bypassing the browser's real native drag-initiation path;
 * the tester honestly filed the genuine-gesture case as UNSURE rather than
 * asserting it worked.
 *
 * DnD mechanism actually implemented by the component (read first, per
 * brief): the HTML5 native drag-and-drop API — NOT dnd-kit / react-beautiful-
 * dnd / pointer events. See apps/web/src/app/dashboard/applications/page.tsx:
 *   - card:   `draggable` + `onDragStart={(e) => onCardDragStart(e, card, stage.key)}`
 *             (page.tsx:891-892), handler at page.tsx:620-626 —
 *             `e.dataTransfer.setData("application/json", JSON.stringify({cardId, fromStage}))`.
 *   - column: `onDragOver` (preventDefault + dropEffect, page.tsx:864-867) and
 *             `onDrop={(e) => onColumnDrop(e, stage.key)}` (page.tsx:868),
 *             handler at page.tsx:628-646 — reads back
 *             `e.dataTransfer.getData("application/json")`, looks the card up
 *             in the CURRENT `stages` closure, and calls `moveCard`
 *             (page.tsx:579-617), which does the real
 *             `POST /applications/{id}/move` via `moveApplication()`
 *             (components/applications/tracker-api.ts:58-73).
 *
 * These tests drive the browser-level DOM events (`dragstart` / `dragover` /
 * `drop`) with a stateful `dataTransfer` object that persists data across the
 * sequence exactly the way a real drag session does — the same mechanism a
 * genuine mouse gesture uses in production, as opposed to a hand-rolled
 * `new DragEvent(...)` dispatched straight at one handler.
 *
 * Per brief: if these pass, that means the JS-level handler chain IS wired
 * correctly and the production defect must live at the browser/native-drag-
 * initiation layer (something jsdom cannot model, since jsdom has no real
 * native drag session — see UNSURE note in the final report). This suite
 * reports its actual observed result rather than forcing red.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string, unknown])),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

const APP_FIXTURE = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: null,
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://boards.example.com/acme/1",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
  answers: {},
  fitScore: 88,
};

const MOVE_PATH = `/applications/${APP_FIXTURE.id}/move`;

/** Base handler: 1 submitted application, no pipeline jobs, no approvals. */
function baseApiMock(moveImpl: (body: unknown) => unknown) {
  apiRequest.mockImplementation(async (path: string, opts?: { body?: unknown }) => {
    if (path === "/applications") return [APP_FIXTURE];
    if (path === "/jobs") return [];
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") {
      return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
    }
    if (path === MOVE_PATH) return moveImpl(opts?.body);
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

/** A stateful dataTransfer stub that persists data across the dragstart ->
 * dragover -> drop sequence, exactly as a real browser's native drag session
 * does (the same object instance is reused by the browser throughout one
 * drag operation). */
function createDataTransfer() {
  const store = new Map<string, string>();
  return {
    setData: (fmt: string, val: string) => {
      store.set(fmt, val);
    },
    getData: (fmt: string) => store.get(fmt) ?? "",
    clearData: () => store.clear(),
    effectAllowed: "",
    dropEffect: "",
  };
}

async function dragCardTo(cardEl: HTMLElement, columnEl: HTMLElement) {
  const dataTransfer = createDataTransfer();
  fireEvent.dragStart(cardEl, { dataTransfer });
  fireEvent.dragEnter(columnEl, { dataTransfer });
  fireEvent.dragOver(columnEl, { dataTransfer });
  fireEvent.drop(columnEl, { dataTransfer });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("GMV4-apps-004: kanban drag-and-drop must dispatch a real stage-move request", () => {
  it("dispatches a stage-move request when a card is dropped on another column", async () => {
    baseApiMock(() => ({ ...APP_FIXTURE, status: "screening" }));

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    const submittedColumn = screen.getByTestId("kanban-column-submitted");
    const card = within(submittedColumn).getByTestId("application-card");
    expect(card.textContent).toContain("Senior Product Owner");

    const targetColumn = screen.getByTestId("kanban-column-in-review");

    await dragCardTo(card, targetColumn);

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        MOVE_PATH,
        expect.objectContaining({ method: "POST", body: { to_stage: "in-review" } }),
      ),
    );
  });

  it("does not move the card optimistically when the drop is rejected", async () => {
    baseApiMock(() => {
      throw new Error("422 illegal transition");
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    const submittedColumn = screen.getByTestId("kanban-column-submitted");
    const card = within(submittedColumn).getByTestId("application-card");
    const targetColumn = screen.getByTestId("kanban-column-in-review");

    await dragCardTo(card, targetColumn);

    // Honest rollback: an error surfaces, and the card must still be in
    // "Submitted" — never left sitting (optimistically) in "In Review".
    await screen.findByText(/failed to move card|422 illegal transition/i);
    expect(
      within(screen.getByTestId("kanban-column-submitted")).queryByText("Senior Product Owner"),
    ).not.toBeNull();
    expect(
      within(screen.getByTestId("kanban-column-in-review")).queryByText("Senior Product Owner"),
    ).toBeNull();
  });

  it("the accessible Move-to menu still dispatches the same request (positive control)", async () => {
    baseApiMock(() => ({ ...APP_FIXTURE, status: "screening" }));

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    const submittedColumn = screen.getByTestId("kanban-column-submitted");
    fireEvent.click(within(submittedColumn).getByTestId("move-menu-btn"));
    fireEvent.click(within(submittedColumn).getByTestId("move-option-in-review"));

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        MOVE_PATH,
        expect.objectContaining({ method: "POST", body: { to_stage: "in-review" } }),
      ),
    );
  });
});
