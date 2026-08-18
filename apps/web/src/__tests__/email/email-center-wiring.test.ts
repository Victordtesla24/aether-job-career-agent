/**
 * MV-email-center — pure helpers that keep the Email Command Center HONEST once
 * the real emailAgent is wired in:
 *
 * - `emailScoreBadge`: a never-triaged thread has NO score → an em-dash
 *   placeholder, never a fabricated 0 that reads like a real "irrelevant" verdict
 *   (MV-email-center-001).
 * - `parseEmailInsights` / `parseEmailDraft`: read the REAL score/breakdown/draft
 *   out of a POST /agents/email/run response, and degrade to an honest empty
 *   state when the agent returned nothing usable (MV-email-center-001/002).
 * - `linkedInSearchUrl`: an honest per-sender LinkedIn *search* link (not a
 *   fabricated "profile" link), omitted entirely when there is no real name
 *   (MV-email-center-007).
 */
import { describe, expect, it } from "vitest";

import {
  emailAgentErrorMessage,
  emailAgentRateLimited,
  emailAutomationStatus,
  emailReplySentNotice,
  emailScoreBadge,
  emailToneBars,
  emailTriageNotice,
  gmailConnectedSuccessNotice,
  linkedInSearchUrl,
  parseEmailDraft,
  parseEmailDraftTone,
  parseEmailInsights,
  sortEmailInboxMessages,
  type EmailInbox,
  type EmailMessage,
} from "../../lib/api/workspaces";

describe("emailScoreBadge (MV-001 honest no-score)", () => {
  it("shows an em-dash for a never-triaged thread (null), not a fabricated 0", () => {
    expect(emailScoreBadge(null)).toEqual({ text: "—", scored: false });
  });
  it("shows the real number once a thread has a triage score", () => {
    expect(emailScoreBadge(88)).toEqual({ text: "88", scored: true });
    expect(emailScoreBadge(0)).toEqual({ text: "0", scored: true });
  });
});

describe("parseEmailInsights (MV-001 real intelligence)", () => {
  it("lifts a real insights object out of the agent response", () => {
    const resp = {
      insights: {
        score: 74,
        breakdown: [
          { label: "Recruiter Engagement", value: 80 },
          { label: "Urgency", value: 65 },
        ],
        summary: "Engaged recruiter — respond within 24h.",
      },
    };
    expect(parseEmailInsights(resp)).toEqual({
      score: 74,
      breakdown: [
        { label: "Recruiter Engagement", value: 80 },
        { label: "Urgency", value: 65 },
      ],
      summary: "Engaged recruiter — respond within 24h.",
    });
  });
  it("returns null (honest empty state) when there is no usable score", () => {
    expect(parseEmailInsights({})).toBeNull();
    expect(parseEmailInsights({ insights: null })).toBeNull();
    expect(parseEmailInsights({ insights: { summary: "x" } })).toBeNull();
  });
  it("drops malformed breakdown rows rather than rendering garbage", () => {
    const parsed = parseEmailInsights({
      insights: { score: 50, breakdown: [{ label: "ok", value: 10 }, { bad: true }, null] },
    });
    expect(parsed?.breakdown).toEqual([{ label: "ok", value: 10 }]);
  });
});

describe("parseEmailDraft (MV-002 real draft)", () => {
  it("returns the real draft text", () => {
    expect(parseEmailDraft({ draft: "Thank you for advancing my application." })).toBe(
      "Thank you for advancing my application.",
    );
  });
  it("returns empty string when the agent produced no draft", () => {
    expect(parseEmailDraft({})).toBe("");
    expect(parseEmailDraft({ draft: 123 })).toBe("");
  });
});

describe("linkedInSearchUrl (MV-007 honest search, not fake profile)", () => {
  it("builds an encoded people-search URL from sender name + company", () => {
    expect(linkedInSearchUrl("Sarah Chen", "Acme Corp")).toBe(
      "https://www.linkedin.com/search/results/people/?keywords=Sarah%20Chen%20Acme%20Corp",
    );
  });
  it("works with just a name", () => {
    expect(linkedInSearchUrl("Sarah Chen", "")).toBe(
      "https://www.linkedin.com/search/results/people/?keywords=Sarah%20Chen",
    );
  });
  it("returns null when there is no real sender name", () => {
    expect(linkedInSearchUrl("", "Acme")).toBeNull();
    expect(linkedInSearchUrl("Unknown", "")).toBeNull();
  });
});

function msg(overrides: Partial<EmailMessage>): EmailMessage {
  return {
    id: "t",
    from: "Recruiter",
    fromEmail: "r@example.com",
    company: "Acme",
    subject: "Role",
    preview: "Hi",
    category: "priority",
    score: null,
    receivedAt: "2026-01-01T00:00:00Z",
    account: "me@gmail.com",
    body: "Hi",
    bodyTruncated: false,
    intelligence: null,
    draftReply: "",
    ...overrides,
  };
}

describe("sortEmailInboxMessages", () => {
  const olderHigh = msg({
    id: "high",
    score: 90,
    receivedAt: "2026-01-01T00:00:00Z",
    category: "priority",
  });
  const mid = msg({
    id: "mid",
    score: 50,
    receivedAt: "2026-06-01T00:00:00Z",
    category: "priority",
  });
  const newestUnscored = msg({
    id: "new",
    score: null,
    receivedAt: "2026-08-18T00:00:00Z",
    category: "priority",
  });

  it("priority: score descending, null last, then recency", () => {
    const sorted = sortEmailInboxMessages(
      [newestUnscored, mid, olderHigh],
      "priority",
    );
    expect(sorted.map((m) => m.id)).toEqual(["high", "mid", "new"]);
  });

  it("followup: same score-first order", () => {
    const sorted = sortEmailInboxMessages(
      [newestUnscored, olderHigh],
      "followup",
    );
    expect(sorted.map((m) => m.id)).toEqual(["high", "new"]);
  });

  it("all: recency only — does not bury new unscored mail", () => {
    const sorted = sortEmailInboxMessages(
      [olderHigh, mid, newestUnscored],
      "all",
    );
    expect(sorted.map((m) => m.id)).toEqual(["new", "mid", "high"]);
  });

  it("explicit recency sort overrides priority score-first default", () => {
    const sorted = sortEmailInboxMessages(
      [olderHigh, mid, newestUnscored],
      "priority",
      "recency",
    );
    expect(sorted.map((m) => m.id)).toEqual(["new", "mid", "high"]);
  });

  it("career potential uses Role Fit, never a fabricated third metric", () => {
    const fitLow = msg({
      id: "fit-low",
      score: 90,
      intelligence: {
        score: 40,
        breakdown: [{ label: "Role Fit Signals", value: 20 }],
        summary: "Weak fit.",
      },
    });
    const fitHigh = msg({
      id: "fit-high",
      score: 10,
      intelligence: {
        score: 80,
        breakdown: [{ label: "Role Fit Signals", value: 95 }],
        summary: "Strong fit.",
      },
    });
    const sorted = sortEmailInboxMessages([fitLow, fitHigh], "all", "potential");
    expect(sorted.map((m) => m.id)).toEqual(["fit-high", "fit-low"]);
  });
});

describe("draft tone bars (MV-006)", () => {
  it("shows not measured when the agent returned no tone", () => {
    expect(parseEmailDraftTone({})).toBeNull();
    expect(emailToneBars(null).map((row) => row.value)).toEqual([null, null, null]);
    expect(emailToneBars(null).map((row) => row.label)).toEqual([
      "Enthusiasm",
      "Formality",
      "Detail",
    ]);
  });

  it("lifts real 0-100 tone scores", () => {
    expect(
      parseEmailDraftTone({ tone: { enthusiasm: 55, formality: 80, detail: 40 } }),
    ).toEqual({ enthusiasm: 55, formality: 80, detail: 40 });
  });
});

describe("automation status (MV-006)", () => {
  const emptyInbox: EmailInbox = {
    accounts: [
      {
        id: "a1",
        email: "me@gmail.com",
        provider: "Gmail",
        status: "connected",
        isPrimary: true,
        unread: 0,
        lastSyncedAt: "2026-08-18T06:00:00+00:00",
      },
    ],
    stats: {
      received: 2,
      recruiterEmails: 1,
      autoDrafted: 0,
      sentApproved: 0,
      followUpsSent: 0,
      avgResponseHrs: null,
      automatedCount: 3,
      personalHidden: 4,
    },
    followUps: [{ company: "Acme", role: "PM", dueIn: "Needs a follow-up draft", status: "queued" }],
    messages: [],
    recruiterProfile: null,
  };

  it("uses the real last sync stamp and never claims auto-send", () => {
    const status = emailAutomationStatus(emptyInbox);
    expect(status.lastScan).toBe("2026-08-18T06:00:00+00:00");
    expect(status.nextScan).toMatch(/On demand/);
    expect(status.autoReply).toBe("Draft for Review");
    expect(status.followUpsQueued).toBe(1);
    expect(status.personalHidden).toBe(4);
    expect(status.automatedCount).toBe(3);
  });

  it("says not measured when no mailbox has ever synced", () => {
    const status = emailAutomationStatus({
      ...emptyInbox,
      accounts: [{ ...emptyInbox.accounts[0], lastSyncedAt: null }],
      stats: { ...emptyInbox.stats, automatedCount: undefined, personalHidden: undefined },
    });
    expect(status.lastScan).toBe("not measured");
    expect(status.personalHidden).toBeNull();
    expect(status.automatedCount).toBeNull();
  });
});

describe("Email Center copy (no emoji / checkmarks)", () => {
  it("Gmail connected notice has no checkmark", () => {
    const text = gmailConnectedSuccessNotice();
    expect(text).toMatch(/Gmail connected/);
    expect(text).not.toMatch(/[✓✔✅]/);
  });

  it("sent notice names the recipient and has no checkmark", () => {
    const text = emailReplySentNotice("Pat Lee");
    expect(text).toContain("Pat Lee");
    expect(text).not.toMatch(/[✓✔✅]/);
  });
});

describe("emailTriageNotice", () => {
  it("success copy names scores only when the run was not degraded", () => {
    const notice = emailTriageNotice({
      degraded: false,
      triaged: 4,
      drafted: 1,
    });
    expect(notice.kind).toBe("success");
    expect(notice.message).toMatch(/Triaged 4 threads — scores and tabs updated/);
    expect(notice.message).toMatch(/1 recruiter reply drafted for review/);
  });

  it("429 degrade is a warn, uses the backend sentence, never claims scores", () => {
    const notice = emailTriageNotice({
      degraded: true,
      triaged: 12,
      drafted: 0,
      message:
        "Sorted 12 career threads with the career filter (no AI scores this run). The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
    });
    expect(notice.kind).toBe("warn");
    expect(notice.message).toContain("no AI scores");
    expect(notice.message).toContain("rate-limited");
    expect(notice.message).not.toMatch(/scores and tabs updated/i);
  });
});

describe("emailAgentErrorMessage", () => {
  it("lifts the FastAPI string detail out of an apiRequest 503 wrapper", () => {
    const err = new Error(
      'POST /agents/email/run failed (503): {"detail":"The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings."}',
    );
    expect(emailAgentErrorMessage(err, "Could not run AI triage.")).toBe(
      "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
    );
  });

  it("passes through a job-poll error that is already the honest sentence", () => {
    const err = new Error(
      "The selected model did not return a usable result. Try a different model in Agent Settings, or try again shortly.",
    );
    expect(emailAgentErrorMessage(err, "Could not run AI triage.")).toBe(err.message);
  });
});

describe("emailAgentRateLimited", () => {
  it("is true only for the honest provider rate-limit sentence", () => {
    expect(
      emailAgentRateLimited(
        "Sorted 2 career threads with the career filter (no AI scores this run). The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
      ),
    ).toBe(true);
    expect(emailAgentRateLimited("Gmail sync failed — reconnect your account.")).toBe(
      false,
    );
  });
});
