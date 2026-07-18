// @vitest-environment jsdom
/**
 * MV-interview-center-001 / -003 regression guard (/dashboard/interviews).
 *
 * The screen was a static "No interview scheduled" placeholder that never
 * called any of its 7 backend endpoints, and there was no UI anywhere to
 * schedule an interview. These tests render the REAL InterviewCenterPage
 * against a mocked apiRequest and assert:
 *   1. it GETs /interviews and renders the real rows (role/company/status), and
 *   2. the "Schedule interview" form POSTs to /interviews and the new interview
 *      round-trips into the list, then a status transition (complete) hits the
 *      real endpoint and updates the card.
 *
 * A regression that reverts the page to a static placeholder fails here.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import InterviewCenterPage from "../page";

const APP_FIXTURE = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "interview",
  coverLetter: null,
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: null,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
};

interface WireInterview {
  id: string;
  user_id: string;
  application_id: string | null;
  type: string;
  status: string;
  scheduled_at: string;
  duration_minutes: number;
  location: string | null;
  meeting_link: string | null;
  notes: string | null;
  contact_name: string | null;
  contact_email: string | null;
  created_at: string;
  updated_at: string;
}

let interviews: WireInterview[] = [];
let seq = 0;

function makeInterview(body: Record<string, unknown>): WireInterview {
  seq += 1;
  return {
    id: `iv-${seq}`,
    user_id: "u-1",
    application_id: (body.application_id as string) ?? null,
    type: (body.type as string) ?? "video",
    status: "scheduled",
    scheduled_at: (body.scheduled_at as string) ?? "2026-08-01T15:00:00.000Z",
    duration_minutes: (body.duration_minutes as number) ?? 60,
    location: (body.location as string) ?? null,
    meeting_link: (body.meeting_link as string) ?? null,
    notes: (body.notes as string) ?? null,
    contact_name: (body.contact_name as string) ?? null,
    contact_email: (body.contact_email as string) ?? null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

beforeEach(() => {
  interviews = [];
  seq = 0;
  apiRequest.mockReset();
  apiRequest.mockImplementation(async (path: string, options: { method?: string; body?: unknown } = {}) => {
    const method = options.method ?? "GET";
    if (path === "/applications") return [APP_FIXTURE];
    if (path === "/interviews" && method === "GET") return [...interviews];
    if (path === "/interviews" && method === "POST") {
      const iv = makeInterview((options.body ?? {}) as Record<string, unknown>);
      interviews.push(iv);
      return iv;
    }
    const complete = path.match(/^\/interviews\/(.+)\/complete$/);
    if (complete && method === "POST") {
      interviews = interviews.map((i) =>
        i.id === complete[1] ? { ...i, status: "completed" } : i,
      );
      return interviews.find((i) => i.id === complete[1]);
    }
    const cancel = path.match(/^\/interviews\/(.+)\/cancel$/);
    if (cancel && method === "POST") {
      interviews = interviews.map((i) =>
        i.id === cancel[1] ? { ...i, status: "cancelled" } : i,
      );
      return interviews.find((i) => i.id === cancel[1]);
    }
    throw new Error(`unexpected apiRequest(${method} ${path})`);
  });
});

afterEach(() => cleanup());

describe("Interview Center — real backend wiring (MV-interview-center-001/003)", () => {
  it("GETs /interviews and renders real rows (role, company, status)", async () => {
    interviews = [
      makeInterview({
        application_id: "app-1",
        type: "onsite",
        scheduled_at: "2026-08-02T09:30:00.000Z",
        notes: "Research the payments org.",
      }),
    ];

    render(<InterviewCenterPage />);

    const card = await screen.findByTestId("interview-card");
    expect(apiRequest).toHaveBeenCalledWith("/interviews", expect.anything());
    // Real fields render — not a hardcoded empty state.
    expect(within(card).getByText(/Senior Product Owner/)).not.toBeNull();
    expect(within(card).getByText(/Acme Corp/)).not.toBeNull();
    expect(within(card).getByText(/Research the payments org\./)).not.toBeNull();
    expect(within(card).getByTestId("interview-status").textContent).toContain("scheduled");
    // The old static placeholder copy is gone.
    expect(screen.queryByTestId("interviews-empty-state")).toBeNull();
  });

  it("schedules an interview that round-trips into the list, then completes it", async () => {
    render(<InterviewCenterPage />);

    // Starts empty (honest empty state after a real fetch that returned []).
    await screen.findByTestId("interviews-empty-state");

    // Open the create affordance and fill the form.
    fireEvent.click(screen.getByTestId("schedule-interview-btn"));
    const form = await screen.findByTestId("schedule-interview-form");
    fireEvent.change(within(form).getByTestId("interview-application-select"), {
      target: { value: "app-1" },
    });
    fireEvent.change(within(form).getByTestId("interview-scheduled-at"), {
      target: { value: "2026-08-01T15:00" },
    });
    fireEvent.click(within(form).getByTestId("interview-submit-btn"));

    // Round-trip: the new interview now appears in the list.
    const card = await screen.findByTestId("interview-card");
    expect(within(card).getByText(/Senior Product Owner/)).not.toBeNull();

    // A real POST /interviews fired with the scoped application id + ISO time.
    const post = apiRequest.mock.calls.find(
      ([p, o]) => p === "/interviews" && (o as { method?: string })?.method === "POST",
    );
    expect(post).toBeDefined();
    const body = (post![1] as { body: Record<string, unknown> }).body;
    expect(body.application_id).toBe("app-1");
    expect(typeof body.scheduled_at).toBe("string");
    expect(body.scheduled_at as string).toMatch(/T.*Z$/);

    // Status transition: mark complete -> real endpoint -> card updates.
    fireEvent.click(within(card).getByTestId("interview-complete-btn"));
    const status = await screen.findByTestId("interview-status");
    expect(status.textContent).toContain("completed");
    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringMatching(/^\/interviews\/iv-1\/complete$/),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
