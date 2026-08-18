// @vitest-environment jsdom
/**
 * Production 2026-08-18: Triage 503'd on user-pinned Claude HTTP 429.
 * ADR-ML-3 forbids a silent model swap. After a rate-limit warn/error the
 * Email Center must offer an explicit "Retry with a lighter model" control
 * that posts `{ mode: "triage", light_retry: true }`.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EmailInbox } from "../../../../lib/api/workspaces";

const fetchEmailInboxMock = vi.fn();
const fetchEmailThreadBodyMock = vi.fn();
const runAgentMock = vi.fn();

vi.mock("../../../../lib/api/workspaces", async () => {
  const actual =
    await vi.importActual<typeof import("../../../../lib/api/workspaces")>(
      "../../../../lib/api/workspaces",
    );
  return {
    ...actual,
    fetchEmailInbox: (...args: unknown[]) => fetchEmailInboxMock(...args),
    fetchEmailThreadBody: (...args: unknown[]) => fetchEmailThreadBodyMock(...args),
  };
});

vi.mock("../../../../lib/api/agents", async () => {
  const actual =
    await vi.importActual<typeof import("../../../../lib/api/agents")>(
      "../../../../lib/api/agents",
    );
  return { ...actual, runAgent: (...args: unknown[]) => runAgentMock(...args) };
});

vi.mock("../../../../hooks/useRealtime", async () => {
  const actual =
    await vi.importActual<typeof import("../../../../hooks/useRealtime")>(
      "../../../../hooks/useRealtime",
    );
  return {
    ...actual,
    useRealtimeResources: () => undefined,
  };
});

// eslint-disable-next-line import/first
import EmailCenterPage from "../page";

function inbox(): EmailInbox {
  return {
    accounts: [
      {
        id: "acc-1",
        email: "me@gmail.com",
        provider: "Gmail",
        status: "connected",
        isPrimary: true,
        unread: 0,
      },
    ],
    stats: {
      received: 1,
      recruiterEmails: 1,
      autoDrafted: 0,
      sentApproved: 0,
      followUpsSent: 0,
      avgResponseHrs: 0,
    },
    followUps: [],
    messages: [
      {
        id: "t1",
        from: "Ada Recruiter",
        fromEmail: "ada@acme.com",
        company: "Acme",
        subject: "Intro call",
        preview: "Are you free Tuesday?",
        category: "all",
        score: null,
        receivedAt: "2026-08-18",
        account: "me@gmail.com",
        body: "Are you free Tuesday?",
        bodyTruncated: false,
        intelligence: null,
        draftReply: "",
      },
    ],
    recruiterProfile: null,
  };
}

afterEach(() => {
  cleanup();
  fetchEmailInboxMock.mockReset();
  fetchEmailThreadBodyMock.mockReset();
  runAgentMock.mockReset();
});

describe("triage light-retry control (ADR-ML-3 explicit Haiku)", () => {
  it("posts light_retry only after the user clicks Retry with a lighter model", async () => {
    fetchEmailInboxMock.mockResolvedValue(inbox());
    fetchEmailThreadBodyMock.mockResolvedValue({ body: "Are you free Tuesday?" });
    runAgentMock.mockResolvedValue({
      mode: "triage",
      degraded: true,
      triaged: 1,
      drafted: 0,
      message:
        "Sorted 1 career thread with the career filter (no AI scores this run). The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
    });

    render(<EmailCenterPage />);
    await waitFor(() => expect(fetchEmailInboxMock).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("run-triage-btn"));
    await waitFor(() => expect(screen.getByTestId("triage-notice")).toBeTruthy());
    expect(runAgentMock).toHaveBeenCalledWith("email", { mode: "triage" });

    fireEvent.click(screen.getByTestId("triage-retry-light-btn"));
    await waitFor(() =>
      expect(runAgentMock).toHaveBeenCalledWith("email", {
        mode: "triage",
        light_retry: true,
      }),
    );
  });

  it("does not offer a lighter-model retry when the warning is a Gmail reconnect", async () => {
    fetchEmailInboxMock.mockResolvedValue(inbox());
    fetchEmailThreadBodyMock.mockResolvedValue({ body: "Are you free Tuesday?" });
    runAgentMock.mockResolvedValue({
      mode: "triage",
      degraded: true,
      triaged: 0,
      drafted: 0,
      message: "Gmail sync failed — reconnect your account. (token expired)",
    });

    render(<EmailCenterPage />);
    await waitFor(() => expect(fetchEmailInboxMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("run-triage-btn"));
    await waitFor(() => expect(screen.getByTestId("triage-notice")).toBeTruthy());
    expect(screen.queryByTestId("triage-retry-light-btn")).toBeNull();
  });
});
