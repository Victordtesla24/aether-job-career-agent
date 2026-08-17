// @vitest-environment jsdom
/**
 * MF-1 (wave-3.5 adversarial review, blocking finding on 56c9d18 / W-13):
 *
 * The detail panel's on-demand full-body fetch had a race + a silent-failure
 * bug. `fetchedBodyIds.current.add(selectedId)` ran BEFORE the fetch
 * resolved, and neither the `cancelled`-on-switch-away path nor the
 * `body === null` path ever removed the id — so:
 *
 *   reproPathA: select thread A, switch to thread B before A's fetch
 *   resolves -> A's real body is silently discarded and A is marked
 *   "already fetched" forever. Re-selecting A never re-fetches; the detail
 *   panel renders the 120-char snippet as if it were the whole email, with
 *   no indication anything was truncated.
 *
 *   reproPathB: the endpoint returns no match (thread missing / not this
 *   user's) -> same permanent silent-snippet outcome, no error, no retry.
 *
 * This suite drives the REAL EmailCenterPage against a mocked
 * lib/api/workspaces boundary (only fetchEmailInbox / fetchEmailThreadBody
 * are replaced; every pure helper — emailScoreBadge, linkedInSearchUrl, etc.
 * — stays real) and proves both paths now degrade honestly: a labeled
 * loading skeleton while in flight, a labeled "preview only" banner with a
 * WORKING retry on failure, and correct (non-stale) content after a
 * switch-away-then-back once the fetch actually completes.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EmailInbox, EmailMessage } from "../../../../lib/api/workspaces";

const fetchEmailInboxMock = vi.fn();
const fetchEmailThreadBodyMock = vi.fn();

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

// eslint-disable-next-line import/first
import EmailCenterPage from "../page";

function baseMessage(overrides: Partial<EmailMessage>): EmailMessage {
  return {
    id: "thread-x",
    from: "Recruiter",
    fromEmail: "recruiter@example.com",
    company: "Acme",
    subject: "Subject",
    preview: "Snippet…",
    category: "all",
    score: null,
    receivedAt: "2026-07-20",
    account: "me@gmail.com",
    body: "Snippet…",
    bodyTruncated: true,
    intelligence: null,
    draftReply: "",
    ...overrides,
  };
}

function inboxWith(messages: EmailMessage[]): EmailInbox {
  return {
    accounts: [
      { id: "acc-1", email: "me@gmail.com", provider: "Gmail", status: "connected", isPrimary: true, unread: 0 },
    ],
    stats: {
      received: messages.length,
      recruiterEmails: 0,
      autoDrafted: 0,
      sentApproved: 0,
      followUpsSent: 0,
      avgResponseHrs: 0,
    },
    followUps: [],
    messages,
    recruiterProfile: null,
  };
}

/** A controllable fetchEmailThreadBody: each call gets its own resolvable
 * deferred, keyed by thread id, so a test can resolve/reject calls for
 * different threads independently and out of order. */
function deferredThreadBodyMock() {
  const byId: Record<string, { resolve: (v: string | null) => void }> = {};
  fetchEmailThreadBodyMock.mockImplementation((threadId: string) => {
    return new Promise<string | null>((resolve) => {
      byId[threadId] = { resolve };
    });
  });
  return byId;
}

const MSG_A = baseMessage({
  id: "thread-a",
  subject: "Recruiter Alice Thread",
  preview: "Hi, following up on your application…",
  body: "Hi, following up on your application…",
});
const MSG_B = baseMessage({
  id: "thread-b",
  subject: "Recruiter Bob Thread",
  preview: "We would like to schedule a call…",
  body: "We would like to schedule a call…",
});

const FULL_BODY_A = "Hi, following up on your application… " + "A".repeat(200);
const FULL_BODY_B = "We would like to schedule a call… " + "B".repeat(200);

function inboxList() {
  return within(screen.getByTestId("inbox-list"));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MF-1: email detail panel honest full-body loading", () => {
  it(
    "reproPathA — switching away before a fetch resolves does not permanently strand " +
      "the previous thread on the snippet; reselecting shows the real body with no re-fetch",
    async () => {
      const byId = deferredThreadBodyMock();
      fetchEmailInboxMock.mockResolvedValue(inboxWith([MSG_A, MSG_B]));

      render(<EmailCenterPage />);
      await screen.findByTestId("email-center");

      // A is auto-selected on load; its fetch starts but we never resolve it yet.
      await waitFor(() => expect(fetchEmailThreadBodyMock).toHaveBeenCalledWith("thread-a"));
      await screen.findByTestId("email-body-loading");
      expect(screen.queryByTestId("email-body")).toBeNull(); // never a silent snippet stand-in

      // Switch to B before A resolves.
      const cards = inboxList().getAllByTestId("email-card");
      fireEvent.click(cards[1]);
      await waitFor(() => expect(fetchEmailThreadBodyMock).toHaveBeenCalledWith("thread-b"));
      await screen.findByTestId("email-body-loading");

      // A's fetch finally resolves in the background while B is selected —
      // this must NOT be discarded (old bug: `cancelled` guard dropped it).
      byId["thread-a"]!.resolve(FULL_BODY_A);
      byId["thread-b"]!.resolve(FULL_BODY_B);

      await waitFor(() => expect(screen.getByTestId("email-body").textContent).toBe(FULL_BODY_B));

      // Reselect A: fixed behavior renders A's REAL full body immediately —
      // the late-arriving success was recorded keyed by thread id, not
      // discarded and not permanently marked "already fetched" without it.
      fireEvent.click(cards[0]);
      await waitFor(() => expect(screen.getByTestId("email-body").textContent).toBe(FULL_BODY_A));

      // Exactly one fetch per thread — no redundant re-fetch, no lost one.
      expect(fetchEmailThreadBodyMock).toHaveBeenCalledTimes(2);
    },
  );

  it("reproPathB — a missing/failed full-body fetch shows an honest, labeled retry state, never a silent snippet", async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxWith([MSG_A]));
    fetchEmailThreadBodyMock.mockResolvedValueOnce(null); // thread not found / not this user's

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    const errorBanner = await screen.findByTestId("email-body-error");
    expect(errorBanner.textContent).toContain("Preview only");
    expect(errorBanner.textContent).toContain("failed to load");

    // The snippet is shown, but visibly labeled as partial — never passed off
    // as the whole email.
    expect(screen.getByTestId("email-body").textContent).toBe(MSG_A.body);

    // Retry must actually work: a real re-fetch, and success clears the error
    // and replaces the labeled snippet with the real content.
    fetchEmailThreadBodyMock.mockResolvedValueOnce(FULL_BODY_A);
    fireEvent.click(screen.getByTestId("retry-full-body"));

    await waitFor(() => expect(screen.getByTestId("email-body").textContent).toBe(FULL_BODY_A));
    expect(screen.queryByTestId("email-body-error")).toBeNull();
    expect(fetchEmailThreadBodyMock).toHaveBeenCalledTimes(2);
  });

  it("never auto-retries a failed fetch silently on its own — only the explicit Retry click re-fetches", async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxWith([MSG_A, MSG_B]));
    fetchEmailThreadBodyMock.mockResolvedValueOnce(null);

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    await screen.findByTestId("email-body-error");
    expect(fetchEmailThreadBodyMock).toHaveBeenCalledTimes(1);

    // Switching to B and back to A must not silently re-trigger A's failed
    // fetch — the honest error state persists until the user asks again.
    const cards = inboxList().getAllByTestId("email-card");
    fireEvent.click(cards[1]);
    await waitFor(() => expect(fetchEmailThreadBodyMock).toHaveBeenCalledWith("thread-b"));
    fireEvent.click(cards[0]);

    await screen.findByTestId("email-body-error");
    expect(fetchEmailThreadBodyMock).toHaveBeenCalledTimes(2); // thread-a (failed, once) + thread-b
  });

  it("skips the full-body fetch entirely when the list body is already complete (bodyTruncated=false)", async () => {
    const shortMessage = baseMessage({
      id: "thread-short",
      subject: "Quick note",
      preview: "Thanks!",
      body: "Thanks!",
      bodyTruncated: false,
    });
    fetchEmailInboxMock.mockResolvedValue(inboxWith([shortMessage]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    expect((await screen.findByTestId("email-body")).textContent).toBe("Thanks!");
    expect(screen.queryByTestId("email-body-loading")).toBeNull();
    expect(screen.queryByTestId("email-body-error")).toBeNull();
    expect(fetchEmailThreadBodyMock).not.toHaveBeenCalled();
  });
});

describe("REV-U-UI-02: EMAIL-BODY-HORIZONTAL-OVERFLOW-01", () => {
  it("Sync Now re-fetches the inbox with force=true", async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxWith([MSG_A]));
    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    fetchEmailInboxMock.mockClear();
    fireEvent.click(screen.getByTestId("sync-now-btn"));
    await waitFor(() =>
      expect(fetchEmailInboxMock).toHaveBeenCalledWith({ force: true }),
    );
  });

  it("search filters the list by subject without dropping the selected thread's body", async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxWith([MSG_A, MSG_B]));
    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    expect(inboxList().getAllByTestId("email-card")).toHaveLength(2);
    fireEvent.change(screen.getByTestId("inbox-search"), {
      target: { value: "Alice" },
    });
    expect(inboxList().getAllByTestId("email-card")).toHaveLength(1);
    expect(inboxList().getByText("Recruiter Alice Thread")).toBeTruthy();
  });

  it("hydrates a persisted AI draft into the review pane and never claims it was sent", async () => {
    const drafted = baseMessage({
      id: "thread-drafted",
      subject: "Screening call",
      draftReply: "Thank you for reaching out about the role.",
      bodyTruncated: false,
      body: "Are you free Thursday?",
      preview: "Are you free Thursday?",
    });
    fetchEmailInboxMock.mockResolvedValue(inboxWith([drafted]));
    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    expect(screen.getByTestId("draft-ready-badge")).toBeTruthy();
    const textarea = await screen.findByTestId("draft-textarea");
    await waitFor(() =>
      expect((textarea as HTMLTextAreaElement).value).toContain(
        "Thank you for reaching out",
      ),
    );
    expect(screen.queryByTestId("email-sent-notice")).toBeNull();
  });

  it("wraps long unbroken tokens (e.g. a tracking URL) instead of overflowing the page", async () => {
    // Live audit: an unbroken long token in the body pushed scrollWidth to
    // 8x clientWidth with no wrap CSS at all, cascading to a page-wide
    // horizontal scrollbar (body scrollWidth 4714 vs clientWidth 1440).
    // jsdom doesn't lay out text, so this pins the CSS contract that fixes
    // it: `overflow-wrap: break-word` (Tailwind's `break-words`) on the
    // element that renders the raw body text.
    const shortMessage = baseMessage({
      id: "thread-short",
      subject: "Quick note",
      preview: "Thanks!",
      body: "Thanks!",
      bodyTruncated: false,
    });
    fetchEmailInboxMock.mockResolvedValue(inboxWith([shortMessage]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    const body = await screen.findByTestId("email-body");
    expect(body.className).toMatch(/\bbreak-words\b/);
  });
});
