// @vitest-environment jsdom
/**
 * /dashboard/networking page — Stage 2 Cluster E manual-verification fixes.
 *
 * MV-networking-001 (BLOCKER): "Add Contact" was client-side fake — it
 * mutated local state and never called POST /networking/contacts, so new
 * contacts vanished on reload. This must now really call the endpoint, only
 * show success once the backend confirms it, and surface an honest error
 * (no fake success) when the call fails.
 *
 * MV-networking-002 (HIGH): Outreach Queue + Communication Log rendered
 * blank/garbled because the cards read `to`/`preview`/`tone` and
 * `when`/`who`/`channel`/`note` — fields GET /workspaces/networking/summary
 * never sends. The real payload carries contactName/company/subject/kind/
 * status/scheduledAt/sentAt (app/routers/workspaces.py networking_summary).
 *
 * MV-networking-003 (HIGH): "Import from LinkedIn" opened the plain manual
 * Add-Contact modal with no LinkedIn integration behind it — dishonest
 * label. There is no LinkedIn OAuth backend, so the control must be honestly
 * relabeled instead of pretending to import anything.
 *
 * MV-networking-005 (HIGH): contact cards were inert — no way to see a
 * contact's stored details. Cards must now open a detail view sourced from
 * GET /networking/contacts/{id}.
 *
 * MV-networking-004 (MED): "Review all drafts" had no click handler and no
 * destination screen exists — must not remain a dead control.
 *
 * MV-networking-009 / -010 (LOW): Cancel must reset the Add Contact form;
 * Escape must close the modal regardless of DOM focus.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";
import type { NetworkingContactRecord, NetworkingSummary } from "../../../../lib/api/workspaces";

const fetchNetworkingSummaryMock = vi.fn();
const createNetworkingContactMock = vi.fn();
const fetchNetworkingContactMock = vi.fn();

vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchNetworkingSummary: (...args: unknown[]) => fetchNetworkingSummaryMock(...args),
    createNetworkingContact: (...args: unknown[]) => createNetworkingContactMock(...args),
    fetchNetworkingContact: (...args: unknown[]) => fetchNetworkingContactMock(...args),
  };
});

// eslint-disable-next-line import/first
import NetworkingPage from "../page";

function summary(overrides: Partial<NetworkingSummary> = {}): NetworkingSummary {
  return {
    stats: { contacts: 1, activeConversations: 1, referralsInFlight: 0, responseRate: 40 },
    pipeline: [
      {
        stage: "New",
        count: 1,
        contacts: [
          { id: "c-1", name: "Sarah L.", role: "Recruiter", company: "Atlassian", warmth: 1 },
        ],
      },
      { stage: "Warm", count: 0, contacts: [] },
      { stage: "Active", count: 0, contacts: [] },
      { stage: "Scheduled", count: 0, contacts: [] },
      { stage: "Placed", count: 0, contacts: [] },
    ],
    outreachQueue: [
      {
        id: "ot-1",
        kind: "follow_up",
        status: "pending",
        contactName: "Mark K.",
        company: "Canva",
        subject: "Follow Up — Canva",
        scheduledAt: "2026-07-20 09:00:00+00:00",
        sentAt: null,
      },
    ],
    communicationLog: [
      {
        id: "ot-2",
        kind: "message",
        status: "sent",
        contactName: "Priya R.",
        company: "ANZ",
        subject: "Message — ANZ",
        scheduledAt: null,
        sentAt: "2026-07-15 08:00:00+00:00",
      },
    ],
    crmSummary: { activeConversations: 1, followUpsDueToday: 0, warmIntrosPending: 0 },
    ...overrides,
  };
}

const CONTACT_RECORD: NetworkingContactRecord = {
  id: "c-1",
  userId: "u-1",
  name: "Sarah L.",
  title: "Recruiter",
  company: "Atlassian",
  stage: "identified",
  email: "sarah@example.com",
  linkedinUrl: "https://linkedin.com/in/sarahl",
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:00:00Z",
};

afterEach(() => {
  cleanup();
  fetchNetworkingSummaryMock.mockReset();
  createNetworkingContactMock.mockReset();
  fetchNetworkingContactMock.mockReset();
});

describe("NetworkingPage — Add Contact wiring (MV-networking-001)", () => {
  it("calls POST /networking/contacts (via createNetworkingContact) with the form fields, not just local state", async () => {
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    createNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    fetchNetworkingSummaryMock.mockResolvedValueOnce(
      summary({ stats: { contacts: 2, activeConversations: 1, referralsInFlight: 0, responseRate: 40 } }),
    );

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    fireEvent.change(screen.getByTestId("contact-name-input"), { target: { value: "Jamie Rivera" } });
    fireEvent.change(screen.getByTestId("contact-role-input"), { target: { value: "Eng Manager" } });
    fireEvent.change(screen.getByTestId("contact-company-input"), { target: { value: "Stripe" } });
    fireEvent.click(screen.getByTestId("save-contact-btn"));

    await waitFor(() => {
      expect(createNetworkingContactMock).toHaveBeenCalledTimes(1);
    });
    const [payload] = createNetworkingContactMock.mock.calls[0];
    expect(payload).toMatchObject({ name: "Jamie Rivera", title: "Eng Manager", company: "Stripe" });
  });

  it("refetches the summary and renders the persisted contact after a successful save (no reload-loss)", async () => {
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    createNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    fetchNetworkingSummaryMock.mockResolvedValueOnce(
      summary({
        stats: { contacts: 2, activeConversations: 1, referralsInFlight: 0, responseRate: 40 },
        pipeline: [
          {
            stage: "New",
            count: 2,
            contacts: [
              { id: "c-2", name: "Jamie Rivera", role: "Eng Manager", company: "Stripe", warmth: 1 },
              { id: "c-1", name: "Sarah L.", role: "Recruiter", company: "Atlassian", warmth: 1 },
            ],
          },
          { stage: "Warm", count: 0, contacts: [] },
          { stage: "Active", count: 0, contacts: [] },
          { stage: "Scheduled", count: 0, contacts: [] },
          { stage: "Placed", count: 0, contacts: [] },
        ],
      }),
    );

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    fireEvent.change(screen.getByTestId("contact-name-input"), { target: { value: "Jamie Rivera" } });
    fireEvent.click(screen.getByTestId("save-contact-btn"));

    await waitFor(() => {
      expect(fetchNetworkingSummaryMock).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => screen.getByText("Jamie Rivera"));
    // The modal closes only once the backend-confirmed contact is showing.
    expect(screen.queryByTestId("add-contact-modal")).toBeNull();
  });

  it("does NOT optimistically show success when the create call fails — shows an honest error and keeps the modal open", async () => {
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    createNetworkingContactMock.mockRejectedValue(
      new ApiError("POST /networking/contacts failed (422): invalid stage", 422),
    );

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    fireEvent.change(screen.getByTestId("contact-name-input"), { target: { value: "Broken Contact" } });
    fireEvent.click(screen.getByTestId("save-contact-btn"));

    await waitFor(() => {
      expect(createNetworkingContactMock).toHaveBeenCalledTimes(1);
    });
    // Modal stays open — no fake success.
    expect(screen.getByTestId("add-contact-modal")).toBeTruthy();
    expect(screen.queryByText("Broken Contact")).toBeNull();
    // Only one summary fetch (initial load) — no optimistic refetch on failure.
    expect(fetchNetworkingSummaryMock).toHaveBeenCalledTimes(1);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).toMatch(/invalid stage|failed/);
  });
});

describe("NetworkingPage — Outreach Queue + Communication Log field mismatch (MV-networking-002)", () => {
  it("renders the Outreach Queue from the real contactName/company/subject/kind/status fields", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    const queue = screen.getByTestId("outreach-queue");
    expect(queue.textContent).toContain("Mark K.");
    expect(queue.textContent).toContain("Canva");
    expect(queue.textContent).toContain("Follow Up — Canva");
    expect(queue.textContent?.toLowerCase()).toContain("pending");
    expect(queue.textContent).not.toContain("undefined");
  });

  it("renders the Communication Log from the real contactName/company/subject/kind/sentAt fields", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    const log = screen.getByTestId("communication-log");
    expect(log.textContent).toContain("Priya R.");
    expect(log.textContent).toContain("Message — ANZ");
    expect(log.textContent).toContain("2026-07-15");
    expect(log.textContent).not.toContain("undefined");
  });
});

describe("NetworkingPage — honest LinkedIn control (MV-networking-003)", () => {
  it("does not claim to import LinkedIn connections when no LinkedIn integration exists", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary({ stats: { contacts: 0, activeConversations: 0, referralsInFlight: 0, responseRate: 0 }, pipeline: [] }));
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-empty-state"));

    expect(screen.queryByText(/import from linkedin/i)).toBeNull();
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/import your linkedin connections/i);
  });

  it("the empty-state manual-add control opens the real Add Contact modal (matches what it actually does)", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary({ stats: { contacts: 0, activeConversations: 0, referralsInFlight: 0, responseRate: 0 }, pipeline: [] }));
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-empty-state"));

    fireEvent.click(screen.getByTestId("empty-state-add-contact-btn"));
    expect(screen.getByTestId("add-contact-modal")).toBeTruthy();
  });
});

describe("NetworkingPage — contact detail view (MV-networking-005)", () => {
  it("opens a detail panel showing the stored contact fields when a contact card is clicked", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getAllByTestId("contact-card")[0]);

    await waitFor(() => {
      expect(fetchNetworkingContactMock).toHaveBeenCalledWith("c-1");
    });
    await waitFor(() => screen.getByTestId("contact-detail-modal"));
    const modal = screen.getByTestId("contact-detail-modal");
    expect(modal.textContent).toContain("Sarah L.");
    expect(modal.textContent).toContain("sarah@example.com");
    expect(modal.textContent).toContain("Atlassian");
  });
});

describe("NetworkingPage — dead-control cleanup (MV-networking-004)", () => {
  it("does not render a 'Review all drafts' control with no handler and no destination", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    const reviewButton = screen.queryByText(/review all drafts/i);
    if (reviewButton) {
      // If kept at all, it must be honestly disabled — never a silent no-op.
      expect((reviewButton.closest("button") as HTMLButtonElement).disabled).toBe(true);
    }
  });
});

describe("NetworkingPage — Add Contact modal UX (MV-networking-009, MV-networking-010)", () => {
  it("Cancel resets the form so reopening the modal shows empty fields", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    fireEvent.change(screen.getByTestId("contact-name-input"), { target: { value: "Temp Name" } });
    fireEvent.click(screen.getByText("Cancel"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    expect((screen.getByTestId("contact-name-input") as HTMLInputElement).value).toBe("");
  });

  it("Escape closes the Add Contact modal", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("add-contact-btn"));
    expect(screen.getByTestId("add-contact-modal")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByTestId("add-contact-modal")).toBeNull();
    });
  });
});
