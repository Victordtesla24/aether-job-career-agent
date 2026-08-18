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
const deleteNetworkingContactMock = vi.fn();
const updateNetworkingContactMock = vi.fn();

const importGmailContactsMock = vi.fn();
const importLinkedInConnectionsMock = vi.fn();
const listContactsMock = vi.fn();
const refreshContactsFromInboxMock = vi.fn();
const createOutreachTaskMock = vi.fn();
const deleteOutreachTaskMock = vi.fn();
const runAgentMock = vi.fn();
vi.mock("../../../../lib/api/networking", () => ({
  importGmailContacts: (...a: unknown[]) => importGmailContactsMock(...a),
  importLinkedInConnections: (...a: unknown[]) => importLinkedInConnectionsMock(...a),
  listContacts: (...a: unknown[]) => listContactsMock(...a),
  refreshContactsFromInbox: (...a: unknown[]) => refreshContactsFromInboxMock(...a),
  createOutreachTask: (...a: unknown[]) => createOutreachTaskMock(...a),
  deleteOutreachTask: (...a: unknown[]) => deleteOutreachTaskMock(...a),
}));
vi.mock("../../../../lib/api/agents", () => ({
  runAgent: (...a: unknown[]) => runAgentMock(...a),
}));

vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchNetworkingSummary: (...args: unknown[]) => fetchNetworkingSummaryMock(...args),
    createNetworkingContact: (...args: unknown[]) => createNetworkingContactMock(...args),
    fetchNetworkingContact: (...args: unknown[]) => fetchNetworkingContactMock(...args),
    deleteNetworkingContact: (...args: unknown[]) => deleteNetworkingContactMock(...args),
    updateNetworkingContact: (...args: unknown[]) => updateNetworkingContactMock(...args),
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
  deleteNetworkingContactMock.mockReset();
  updateNetworkingContactMock.mockReset();
  refreshContactsFromInboxMock.mockReset();
  createOutreachTaskMock.mockReset();
  deleteOutreachTaskMock.mockReset();
  runAgentMock.mockReset();
  listContactsMock.mockReset();
  window.history.replaceState({}, "", "/dashboard/networking");
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
    expect(queue.textContent).toMatch(/Pending/);
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

describe("NetworkingPage — honest LinkedIn control (MV-networking-003, amended by W-NET-1)", () => {
  it("W-NET-1 (2026-08-16): the LinkedIn import control now exists BECAUSE the backend does", async () => {
    // MV-networking-003 removed a dishonest 'Import from LinkedIn' label
    // that had no backend. The honesty rule is unchanged — a control must do
    // what it says. POST /networking/linkedin/import-contacts (R4.1) is now
    // a real upload-only importer (zero LinkedIn network calls), so the
    // control returns as a FILE upload — never an OAuth/connect claim.
    fetchNetworkingSummaryMock.mockResolvedValue(summary({ stats: { contacts: 0, activeConversations: 0, referralsInFlight: 0, responseRate: 0 }, pipeline: [] }));
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-empty-state"));

    const input = screen.getByTestId("import-linkedin-contacts-input");
    expect(input.getAttribute("type")).toBe("file");
    expect(input.getAttribute("accept")).toBe(".zip,.csv");
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/connect (your )?linkedin/i);
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


describe("NetworkingPage — contact delete wiring (ML-networking-001)", () => {
  it("arms on first click, calls DELETE on confirm, closes the panel and refetches", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    deleteNetworkingContactMock.mockResolvedValue(undefined);

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getAllByTestId("contact-card")[0]);
    await waitFor(() => screen.getByTestId("contact-detail-modal"));

    // FAILED before the fix: no delete affordance existed anywhere in the UI
    // even though DELETE /networking/contacts/{id} shipped on the backend.
    const btn = screen.getByTestId("delete-contact-btn");
    expect(btn.textContent).toContain("Delete contact");

    // First click only ARMS — no API call yet (two-click confirm).
    fireEvent.click(btn);
    expect(deleteNetworkingContactMock).not.toHaveBeenCalled();
    expect(btn.textContent).toContain("confirm");

    // Second click deletes, closes the panel, and refetches the summary.
    fireEvent.click(btn);
    await waitFor(() => {
      expect(deleteNetworkingContactMock).toHaveBeenCalledWith("c-1");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("contact-detail-modal")).toBeNull();
    });
    // Initial load + post-delete reconcile.
    expect(fetchNetworkingSummaryMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("surfaces the error and keeps the panel open when the delete fails", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    deleteNetworkingContactMock.mockRejectedValue(
      new ApiError("DELETE /networking/contacts/c-1 failed (500): boom", 500),
    );

    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getAllByTestId("contact-card")[0]);
    await waitFor(() => screen.getByTestId("contact-detail-modal"));

    const btn = screen.getByTestId("delete-contact-btn");
    fireEvent.click(btn); // arm
    fireEvent.click(btn); // confirm → fails

    await waitFor(() => screen.getByTestId("contact-detail-error"));
    expect(screen.getByTestId("contact-detail-error").textContent).toContain("failed (500)");
    expect(screen.getByTestId("contact-detail-modal")).toBeTruthy();
  });
});


describe("NetworkingPage — contact importers (W-NET-1)", () => {
  it("Gmail import reports the server's real counts and refreshes the summary", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    importGmailContactsMock.mockResolvedValue({
      contactsCreated: 27, leadsCreated: 27, duplicates: 53, suppressed: 1, ignored: 19,
    });
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    const before = fetchNetworkingSummaryMock.mock.calls.length;

    fireEvent.click(screen.getByTestId("import-gmail-contacts-btn"));
    await waitFor(() => screen.getByTestId("import-notice"));
    const notice = screen.getByTestId("import-notice").textContent ?? "";
    expect(notice).toMatch(/27 contact\(s\) created/);
    expect(notice).toMatch(/53 duplicate\(s\) skipped/);
    expect(notice).toMatch(/1 suppressed/);
    expect(fetchNetworkingSummaryMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("a failed Gmail import surfaces the honest error, never a fake success", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    importGmailContactsMock.mockRejectedValue(new Error("Gmail account not connected."));
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("import-gmail-contacts-btn"));
    await waitFor(() => screen.getByTestId("import-error"));
    expect(screen.getByTestId("import-error").textContent).toMatch(/not connected/i);
    expect(screen.queryByTestId("import-notice")).toBeNull();
  });

  it("LinkedIn file selection uploads through the importer and reports counts", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    importLinkedInConnectionsMock.mockResolvedValue({
      contactsCreated: 214, duplicates: 6, suppressed: 0,
    });
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    const file = new File(["First Name,Last Name"], "Connections.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("import-linkedin-contacts-input"), {
      target: { files: [file] },
    });
    await waitFor(() => screen.getByTestId("import-notice"));
    expect(importLinkedInConnectionsMock).toHaveBeenCalledWith(file);
    expect(screen.getByTestId("import-notice").textContent).toMatch(/214 contact\(s\) created/);
  });
});


describe("NetworkingPage — full contact browser (W-NET-2)", () => {
  const rows = [
    { id: "c1", name: "Priya Sharma", title: "Recruiter", company: "SEEK", stage: "identified", email: "p@seek.com", linkedinUrl: null },
    { id: "c2", name: "Tom Nguyen", title: "EM", company: "Canva", stage: "contacted", email: null, linkedinUrl: null },
    { id: "c3", name: "Ana Silva", title: null, company: "Atlassian", stage: "identified", email: null, linkedinUrl: null },
  ];

  it("View all opens the browser listing EVERY contact, not the 5-card preview", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    listContactsMock.mockResolvedValue(rows);
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));

    fireEvent.click(screen.getByTestId("view-all-contacts-btn"));
    await waitFor(() => screen.getByTestId("all-contacts-list"));
    expect(listContactsMock).toHaveBeenCalled();
    expect(screen.getByTestId("all-contacts-row-c1")).toBeTruthy();
    expect(screen.getByTestId("all-contacts-row-c3")).toBeTruthy();
  });

  it("search filters by name/company/title client-side", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    listContactsMock.mockResolvedValue(rows);
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getByTestId("view-all-contacts-btn"));
    await waitFor(() => screen.getByTestId("all-contacts-list"));

    fireEvent.change(screen.getByTestId("all-contacts-search"), { target: { value: "canva" } });
    expect(screen.queryByTestId("all-contacts-row-c1")).toBeNull();
    expect(screen.getByTestId("all-contacts-row-c2")).toBeTruthy();
  });

  it("clicking a row opens the existing contact detail panel", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    listContactsMock.mockResolvedValue(rows);
    fetchNetworkingContactMock.mockResolvedValue({
      id: "c2", name: "Tom Nguyen", title: "EM", company: "Canva", stage: "contacted",
      email: null, linkedinUrl: null, outreach: [],
    });
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getByTestId("view-all-contacts-btn"));
    await waitFor(() => screen.getByTestId("all-contacts-list"));

    fireEvent.click(screen.getByTestId("all-contacts-row-c2"));
    expect(screen.queryByTestId("all-contacts-modal")).toBeNull();
    await waitFor(() => expect(fetchNetworkingContactMock).toHaveBeenCalledWith("c2"));
  });

  it("Escape closes the all-contacts browser", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    listContactsMock.mockResolvedValue(rows);
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getByTestId("view-all-contacts-btn"));
    await waitFor(() => screen.getByTestId("all-contacts-modal"));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByTestId("all-contacts-modal")).toBeNull();
    });
  });
});

describe("NetworkingPage — honesty and freshness (NET-HONEST)", () => {
  it("renders 'not measured' when responseRate is null, never a fabricated 0%", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(
      summary({ stats: { contacts: 1, activeConversations: 0, referralsInFlight: 0, responseRate: null } }),
    );
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-stats"));
    const stats = screen.getByTestId("networking-stats").textContent ?? "";
    expect(stats).toMatch(/not measured/i);
    expect(stats).not.toMatch(/0%/);
  });

  it("does not sell stage as relationship-warmth stars", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("contact-card"));
    expect(screen.queryByLabelText(/warmth/i)).toBeNull();
    expect(screen.getByTestId("contact-card").textContent).not.toMatch(/★/);
  });

  it("Add Contact sends email and LinkedIn URL the API already accepts", async () => {
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    createNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getByTestId("add-contact-btn"));
    fireEvent.change(screen.getByTestId("contact-name-input"), { target: { value: "Jamie Rivera" } });
    fireEvent.change(screen.getByTestId("contact-email-input"), { target: { value: "jamie@stripe.test" } });
    fireEvent.change(screen.getByTestId("contact-linkedin-input"), {
      target: { value: "https://linkedin.com/in/jamier" },
    });
    fireEvent.click(screen.getByTestId("save-contact-btn"));
    await waitFor(() => {
      expect(createNetworkingContactMock).toHaveBeenCalledTimes(1);
    });
    expect(createNetworkingContactMock.mock.calls[0][0]).toMatchObject({
      name: "Jamie Rivera",
      email: "jamie@stripe.test",
      linkedinUrl: "https://linkedin.com/in/jamier",
    });
  });

  it("empty state offers Gmail and LinkedIn import, not only manual add", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(
      summary({ stats: { contacts: 0, activeConversations: 0, referralsInFlight: 0, responseRate: null }, pipeline: [] }),
    );
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-empty-state"));
    const empty = screen.getByTestId("networking-empty-state");
    expect(empty.textContent).toMatch(/gmail/i);
    expect(empty.textContent).toMatch(/linkedin/i);
    expect(screen.getByTestId("empty-state-add-contact-btn")).toBeTruthy();
  });

  it("contact detail can PATCH stage via updateNetworkingContact", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    updateNetworkingContactMock.mockResolvedValue({ ...CONTACT_RECORD, stage: "contacted" });
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getAllByTestId("contact-card")[0]);
    await waitFor(() => screen.getByTestId("contact-detail-modal"));
    fireEvent.change(screen.getByTestId("contact-stage-select"), { target: { value: "contacted" } });
    fireEvent.click(screen.getByTestId("save-contact-edits-btn"));
    await waitFor(() => {
      expect(updateNetworkingContactMock).toHaveBeenCalledWith(
        "c-1",
        expect.objectContaining({ stage: "contacted" }),
      );
    });
  });

  it("Refresh from inbox reports the server counts and reloads the board", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    refreshContactsFromInboxMock.mockResolvedValue({
      contactsCreated: 3,
      contactsUpdated: 1,
      threadsLinked: 4,
      ignored: 2,
    });
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    const before = fetchNetworkingSummaryMock.mock.calls.length;
    fireEvent.click(screen.getByTestId("refresh-from-inbox-btn"));
    await waitFor(() => screen.getByTestId("import-notice"));
    expect(refreshContactsFromInboxMock).toHaveBeenCalled();
    expect(screen.getByTestId("import-notice").textContent).toMatch(/3 contact/);
    expect(fetchNetworkingSummaryMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("stage select shows New/Warm labels while persisting enum values", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getAllByTestId("contact-card")[0]);
    await waitFor(() => screen.getByTestId("contact-stage-select"));
    const select = screen.getByTestId("contact-stage-select") as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual(["New", "Warm", "Active", "Scheduled", "Placed"]);
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      "identified",
      "contacted",
      "responded",
      "meeting",
      "referral",
    ]);
  });

  it("page error offers Retry that clears the error and reloads", async () => {
    fetchNetworkingSummaryMock.mockRejectedValueOnce(new Error("network down"));
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-page-error"));
    fireEvent.click(screen.getByTestId("networking-retry-btn"));
    await waitFor(() => screen.getByTestId("networking-crm"));
    expect(screen.queryByTestId("networking-page-error")).toBeNull();
  });

  it("cancels a pending outreach task via DELETE", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    deleteOutreachTaskMock.mockResolvedValue(undefined);
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("cancel-outreach-ot-1"));
    fireEvent.click(screen.getByTestId("cancel-outreach-ot-1"));
    await waitFor(() => expect(deleteOutreachTaskMock).toHaveBeenCalledWith("ot-1"));
  });

  it("Draft outreach runs recruiterOutreach with contact_id", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    fetchNetworkingContactMock.mockResolvedValue(CONTACT_RECORD);
    runAgentMock.mockResolvedValue({ approvalId: "appr-1", message: "Draft queued" });
    fetchNetworkingSummaryMock.mockResolvedValueOnce(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("networking-crm"));
    fireEvent.click(screen.getAllByTestId("contact-card")[0]);
    await waitFor(() => screen.getByTestId("draft-outreach-btn"));
    fireEvent.click(screen.getByTestId("draft-outreach-btn"));
    await waitFor(() => {
      expect(runAgentMock).toHaveBeenCalledWith("recruiterOutreach", { contact_id: "c-1" });
    });
    await waitFor(() => screen.getByTestId("draft-outreach-notice"));
  });

  it("humanises outreach status chips", async () => {
    fetchNetworkingSummaryMock.mockResolvedValue(summary());
    render(<NetworkingPage />);
    await waitFor(() => screen.getByTestId("outreach-queue"));
    expect(screen.getByTestId("outreach-queue").textContent).toMatch(/Pending/);
    expect(screen.getByTestId("outreach-queue").textContent).not.toMatch(/\bpending\b/);
  });
});
