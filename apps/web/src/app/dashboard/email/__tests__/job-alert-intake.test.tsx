// @vitest-environment jsdom
/**
 * BLOCKER — the job-alert email intake was invocable by NO user action anywhere.
 *
 * `apps/web/src/app/dashboard/agents/page.tsx` hardcoded `emailAgent: { mode:
 * "triage" }` and the Email Center only ever sent `triage` / `insights` /
 * `draft_reply`, so `mode: "job_alerts"` — a fully built, 35-test backend that
 * turns the candidate's own job-alert mail into real Job rows — could not be
 * reached from the product at all. The only reason 45 seek-alert Job rows exist
 * is that an agent called the code directly.
 *
 * This suite drives the REAL EmailCenterPage against a mocked API boundary and
 * proves:
 *   1. REACHABILITY — a real, visible control sends exactly `mode: "job_alerts"`
 *      to POST /agents/email/run.
 *   2. HONEST RESULT — the panel renders the server's REAL counts (emails
 *      scanned, postings extracted, cards created), never a fabricated summary.
 *   3. HONEST STATES — no Gmail connected, zero alerts found, partial
 *      extraction and an unreadable response never imply success.
 *   4. LIVE BOARD — the run does not depend on a page reload: the Email Center
 *      joins the shared realtime channel for `jobs`, which is what makes the
 *      board update live.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EmailInbox, EmailInboxAccount } from "../../../../lib/api/workspaces";

const fetchEmailInboxMock = vi.fn();
const fetchEmailThreadBodyMock = vi.fn();
const runAgentMock = vi.fn();
const useRealtimeResourcesMock = vi.fn();

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
    useRealtimeResources: (...args: unknown[]) => {
      useRealtimeResourcesMock(...args);
    },
  };
});

// eslint-disable-next-line import/first
import EmailCenterPage from "../page";

const CONNECTED: EmailInboxAccount = {
  id: "acc-1",
  email: "me@gmail.com",
  provider: "Gmail",
  status: "connected",
  isPrimary: true,
  unread: 0,
};

function inbox(accounts: EmailInboxAccount[] = [CONNECTED]): EmailInbox {
  return {
    accounts,
    stats: {
      received: 0,
      recruiterEmails: 0,
      autoDrafted: 0,
      sentApproved: 0,
      followUpsSent: 0,
      avgResponseHrs: 0,
    },
    followUps: [],
    messages: [],
    recruiterProfile: null,
  };
}

/** The real backend shape for `job_alerts` (asdict of JobAlertIntakeResult). */
function intakeBody(overrides: Record<string, unknown> = {}) {
  return {
    mode: "job_alerts",
    connected: true,
    degraded: false,
    message: "Read 3 job-alert email(s) across 1 mailbox(es): 12 posting(s) extracted, 9 new job(s) added, 2 already known, 1 skipped for missing data.",
    accounts_scanned: 1,
    messages_scanned: 140,
    alert_emails: 3,
    postings_extracted: 12,
    postings_skipped: 1,
    jobs_created: 9,
    jobs_updated: 2,
    platforms: { seek: 3 },
    per_account: [
      {
        accountId: "acc-1",
        email: "m•••@gmail.com",
        messagesScanned: 140,
        alertEmails: 3,
        postingsExtracted: 12,
        postingsSkipped: 1,
        jobsCreated: 9,
        jobsUpdated: 2,
        error: null,
      },
    ],
    notes: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openCenter(accounts: EmailInboxAccount[] = [CONNECTED]) {
  fetchEmailInboxMock.mockResolvedValue(inbox(accounts));
  fetchEmailThreadBodyMock.mockResolvedValue(null);
  render(<EmailCenterPage />);
  await screen.findByTestId("email-center");
}

describe("BLOCKER: the job-alert intake is reachable from the product", () => {
  it("a real control on the Email Center runs mode job_alerts and shows the REAL counts", async () => {
    runAgentMock.mockResolvedValue(intakeBody());
    await openCenter();

    const btn = screen.getByTestId("run-job-alerts-btn");
    expect(btn).toBeTruthy();
    expect((btn as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(btn);

    // The exact call the backend routes to EmailAgent._job_alerts.
    await waitFor(() => expect(runAgentMock).toHaveBeenCalled());
    const [name, params] = runAgentMock.mock.calls[0]!;
    expect(name).toBe("email");
    expect((params as Record<string, unknown>).mode).toBe("job_alerts");

    const panel = await screen.findByTestId("job-alerts-result");
    expect(panel.textContent).toContain("9 new jobs added to your board");
    // Every real count is on screen — nothing rounded away, nothing invented.
    expect(screen.getByTestId("job-alerts-messages-scanned").textContent).toContain("140");
    expect(screen.getByTestId("job-alerts-alert-emails").textContent).toContain("3");
    expect(screen.getByTestId("job-alerts-postings-extracted").textContent).toContain("12");
    expect(screen.getByTestId("job-alerts-jobs-created").textContent).toContain("9");
    expect(screen.getByTestId("job-alerts-jobs-updated").textContent).toContain("2");
    expect(screen.getByTestId("job-alerts-postings-skipped").textContent).toContain("1");
    // The server's own sentence is shown verbatim, not paraphrased.
    expect(panel.textContent).toContain("12 posting(s) extracted");
  });

  it("shows honest in-flight progress while the scan is running, and never a fake result", async () => {
    let resolveRun: (v: unknown) => void = () => {};
    runAgentMock.mockImplementation(
      () => new Promise((resolve) => { resolveRun = resolve; }),
    );
    await openCenter();

    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));

    const progress = await screen.findByTestId("job-alerts-progress");
    expect(progress.textContent).toMatch(/scanning/i);
    expect((screen.getByTestId("run-job-alerts-btn") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("job-alerts-result")).toBeNull();

    resolveRun(intakeBody());
    await screen.findByTestId("job-alerts-result");
    expect(screen.queryByTestId("job-alerts-progress")).toBeNull();
  });

  it("refetches the inbox after a run so the screen reflects what the scan did", async () => {
    runAgentMock.mockResolvedValue(intakeBody());
    await openCenter();
    const before = fetchEmailInboxMock.mock.calls.length;
    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));
    await screen.findByTestId("job-alerts-result");
    expect(fetchEmailInboxMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("joins the shared realtime channel for jobs, so the board updates live without a reload", async () => {
    await openCenter();
    const watched = useRealtimeResourcesMock.mock.calls.flatMap(
      (call) => (call[0] as string[]) ?? [],
    );
    expect(watched).toContain("jobs");
  });
});

describe("honest states", () => {
  it("no Gmail connected: the control does not pretend it can scan", async () => {
    await openCenter([]);
    const btn = screen.getByTestId("run-job-alerts-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("job-alerts-unavailable").textContent).toMatch(/connect gmail/i);
    fireEvent.click(btn);
    expect(runAgentMock).not.toHaveBeenCalled();
  });

  it("every mailbox needs re-auth: says THAT, not 'connect Gmail'", async () => {
    await openCenter([
      { ...CONNECTED, status: "needs_reauth", note: "Gmail authorization expired." },
    ]);
    expect((screen.getByTestId("run-job-alerts-btn") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("job-alerts-unavailable").textContent).toMatch(/reconnect/i);
  });

  it("zero alerts found never reads as an import", async () => {
    runAgentMock.mockResolvedValue(
      intakeBody({
        message: "Scanned 140 message(s) across 1 mailbox(es) from the last 7 day(s) — no job-alert emails were found.",
        alert_emails: 0,
        postings_extracted: 0,
        postings_skipped: 0,
        jobs_created: 0,
        jobs_updated: 0,
        platforms: {},
        per_account: [
          { accountId: "acc-1", email: "m•••@gmail.com", messagesScanned: 140, alertEmails: 0, postingsExtracted: 0, postingsSkipped: 0, jobsCreated: 0, jobsUpdated: 0, error: null },
        ],
      }),
    );
    await openCenter();
    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));

    const panel = await screen.findByTestId("job-alerts-result");
    expect(panel.textContent).toContain("No job-alert emails in the scanned window");
    expect(panel.textContent).not.toMatch(/added to your board/i);
    expect(panel.getAttribute("data-tone")).toBe("neutral");
  });

  it("partial extraction: skipped postings, parser notes and a dead mailbox are all surfaced", async () => {
    runAgentMock.mockResolvedValue(
      intakeBody({
        degraded: true,
        accounts_scanned: 2,
        postings_extracted: 5,
        postings_skipped: 7,
        jobs_created: 5,
        jobs_updated: 0,
        notes: ["seek: 7 posting blocks had no apply link and were dropped."],
        per_account: [
          { accountId: "acc-1", email: "m•••@gmail.com", messagesScanned: 140, alertEmails: 3, postingsExtracted: 5, postingsSkipped: 7, jobsCreated: 5, jobsUpdated: 0, error: null },
          { accountId: "acc-2", email: "v•••@gmail.com", messagesScanned: 0, alertEmails: 0, postingsExtracted: 0, postingsSkipped: 0, jobsCreated: 0, jobsUpdated: 0, error: "RefreshError: invalid_grant" },
        ],
      }),
    );
    await openCenter();
    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));

    const panel = await screen.findByTestId("job-alerts-result");
    expect(panel.getAttribute("data-tone")).toBe("warning");
    expect(panel.textContent).toContain("1 mailbox could not be read");
    expect(screen.getByTestId("job-alerts-postings-skipped").textContent).toContain("7");
    expect(panel.textContent).toContain("RefreshError: invalid_grant");
    expect(panel.textContent).toContain("7 posting blocks had no apply link");
  });

  it("an unreadable response is reported as such — never rendered as a zero scan", async () => {
    runAgentMock.mockResolvedValue({ mode: "triage", triaged: 4 });
    await openCenter();
    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));

    const err = await screen.findByTestId("job-alerts-error");
    expect(err.textContent).toMatch(/could not read/i);
    expect(screen.queryByTestId("job-alerts-result")).toBeNull();
  });

  it("a failed request shows the real server error", async () => {
    runAgentMock.mockRejectedValue(new Error("Gmail token exchange failed"));
    await openCenter();
    fireEvent.click(screen.getByTestId("run-job-alerts-btn"));

    const err = await screen.findByTestId("job-alerts-error");
    expect(err.textContent).toContain("Gmail token exchange failed");
    expect(screen.queryByTestId("job-alerts-result")).toBeNull();
  });
});
