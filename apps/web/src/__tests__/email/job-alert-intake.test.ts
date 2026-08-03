/**
 * Job-alert intake — the pure read/parse layer (BLOCKER: the intake mode was
 * invocable by NO user action anywhere).
 *
 * The backend's `job_alerts` mode returns a dataclass of REAL counts
 * (`app/agents/email_agent.py::JobAlertIntakeResult`). These helpers lift those
 * counts out of the POST /agents/email/run body and derive the honest headline
 * the Email Center renders. The rules under test:
 *
 *  - a response that is not a job-alert result (wrong mode / wrong shape /
 *    missing counts) parses to `null` — never to a zero-filled summary that
 *    would render as "scanned 0, found 0" as if a real scan had happened;
 *  - the headline NEVER claims success that the counts do not support: zero
 *    alerts, alerts-but-no-complete-postings, postings-but-all-already-known
 *    and a mailbox that could not be read each get their own honest wording;
 *  - per-mailbox errors and parser notes survive to the UI verbatim.
 */
import { describe, expect, it } from "vitest";

import {
  jobAlertHeadline,
  jobAlertTone,
  parseJobAlertIntake,
} from "../../lib/api/jobAlerts";

/** A complete, realistic backend body (snake_case — `_to_output` asdict()s the
 *  dataclass, and the router pops only `llm_called`). */
function body(overrides: Record<string, unknown> = {}) {
  return {
    mode: "job_alerts",
    connected: true,
    degraded: false,
    message: "Read 3 job-alert email(s) across 2 mailbox(es): 12 posting(s) extracted, 9 new job(s) added, 2 already known, 1 skipped for missing data.",
    accounts_scanned: 2,
    messages_scanned: 140,
    alert_emails: 3,
    postings_extracted: 12,
    postings_skipped: 1,
    jobs_created: 9,
    jobs_updated: 2,
    platforms: { seek: 2, linkedin: 1 },
    per_account: [
      {
        accountId: "acc-1",
        email: "s•••@gmail.com",
        messagesScanned: 100,
        alertEmails: 3,
        postingsExtracted: 12,
        postingsSkipped: 1,
        jobsCreated: 9,
        jobsUpdated: 2,
        error: null,
      },
      {
        accountId: "acc-2",
        email: "v•••@gmail.com",
        messagesScanned: 40,
        alertEmails: 0,
        postingsExtracted: 0,
        postingsSkipped: 0,
        jobsCreated: 0,
        jobsUpdated: 0,
        error: null,
      },
    ],
    notes: ["seek: alert had no posting blocks."],
    ...overrides,
  };
}

describe("parseJobAlertIntake", () => {
  it("lifts every real count out of a genuine job_alerts response", () => {
    const s = parseJobAlertIntake(body());
    expect(s).not.toBeNull();
    expect(s!.accountsScanned).toBe(2);
    expect(s!.messagesScanned).toBe(140);
    expect(s!.alertEmails).toBe(3);
    expect(s!.postingsExtracted).toBe(12);
    expect(s!.postingsSkipped).toBe(1);
    expect(s!.jobsCreated).toBe(9);
    expect(s!.jobsUpdated).toBe(2);
    expect(s!.connected).toBe(true);
    expect(s!.degraded).toBe(false);
    expect(s!.message).toContain("9 new job(s) added");
    expect(s!.platforms).toEqual([
      { platform: "seek", count: 2 },
      { platform: "linkedin", count: 1 },
    ]);
    expect(s!.mailboxes).toHaveLength(2);
    expect(s!.mailboxes[0]!.email).toBe("s•••@gmail.com");
    expect(s!.mailboxes[0]!.jobsCreated).toBe(9);
    expect(s!.notes).toEqual(["seek: alert had no posting blocks."]);
  });

  it("accepts the hyphenated mode alias the backend also routes", () => {
    expect(parseJobAlertIntake(body({ mode: "job-alerts" }))).not.toBeNull();
  });

  it("returns null — never a zero-filled fake scan — for a non-job-alert body", () => {
    expect(parseJobAlertIntake(null)).toBeNull();
    expect(parseJobAlertIntake({})).toBeNull();
    expect(parseJobAlertIntake({ mode: "triage", triaged: 4 })).toBeNull();
    expect(parseJobAlertIntake("job_alerts")).toBeNull();
  });

  it("returns null when a core count is missing or not a real number", () => {
    expect(parseJobAlertIntake(body({ jobs_created: undefined }))).toBeNull();
    expect(parseJobAlertIntake(body({ messages_scanned: "lots" }))).toBeNull();
    expect(parseJobAlertIntake(body({ alert_emails: NaN }))).toBeNull();
    expect(parseJobAlertIntake(body({ postings_extracted: -1 }))).toBeNull();
  });

  it("keeps a per-mailbox error verbatim and drops garbage rows", () => {
    const s = parseJobAlertIntake(
      body({
        degraded: true,
        per_account: [
          {
            accountId: "acc-2",
            email: "v•••@gmail.com",
            messagesScanned: 0,
            alertEmails: 0,
            postingsExtracted: 0,
            postingsSkipped: 0,
            jobsCreated: 0,
            jobsUpdated: 0,
            error: "RefreshError: invalid_grant",
          },
          "not-a-mailbox",
        ],
      }),
    );
    expect(s!.mailboxes).toHaveLength(1);
    expect(s!.mailboxes[0]!.error).toBe("RefreshError: invalid_grant");
    expect(s!.failedMailboxes).toBe(1);
  });

  it("does not invent a per-mailbox count that the server did not report", () => {
    const s = parseJobAlertIntake(
      body({ per_account: [{ accountId: "acc-1", email: null, error: null }] }),
    );
    expect(s!.mailboxes[0]!.messagesScanned).toBeNull();
    expect(s!.mailboxes[0]!.jobsCreated).toBeNull();
  });
});

describe("the REAL production wire shape", () => {
  /**
   * Captured verbatim from a live `POST /agents/email/run {"mode":"job_alerts",
   * "days":7}` against http://127.0.0.1:8000 as the real user (2026-08-03,
   * run_id c4be34adf6174f6174d615bb0). It carries the router's extra
   * envelope fields (duration_ms / billingAudit / run_id / noLlmCall …) that
   * the dataclass itself does not declare — the parser must read the counts
   * out of THAT body, not just a hand-written fixture.
   */
  const LIVE = {
    mode: "job_alerts",
    connected: true,
    degraded: false,
    message:
      "Read 3 job-alert email(s) across 2 mailbox(es): 46 posting(s) extracted, 23 new job(s) added, 23 already known, 2 skipped for missing data.",
    accounts_scanned: 2,
    messages_scanned: 47,
    alert_emails: 3,
    postings_extracted: 46,
    postings_skipped: 2,
    jobs_created: 23,
    jobs_updated: 23,
    platforms: { michaelpage: 1, seek: 2 },
    per_account: [
      {
        accountId: "c1691e908087d4baa736a2919",
        email: "s***********m@gmail.com",
        messagesScanned: 18,
        alertEmails: 1,
        postingsExtracted: 0,
        postingsSkipped: 2,
        jobsCreated: 0,
        jobsUpdated: 0,
        error: null,
      },
      {
        accountId: "c257c66246854158ba216e787",
        email: "m**********e@gmail.com",
        messagesScanned: 29,
        alertEmails: 2,
        postingsExtracted: 46,
        postingsSkipped: 0,
        jobsCreated: 23,
        jobsUpdated: 23,
        error: null,
      },
    ],
    notes: [
      "No postings could be read from this michaelpage alert without inventing a field (2 link(s) carried no job title). Nothing was fabricated.",
    ],
    duration_ms: 13125,
    approvalRequired: false,
    billingAudit: {
      credentialSource: "database",
      authMode: "api_key",
      provider: "openrouter",
      quotaPath: "metered_api",
    },
    model: null,
    tokensIn: 0,
    tokensOut: 0,
    costUsd: 0.0,
    noLlmCall: true,
    run_id: "c4be34adf6174f6174d615bb0",
  };

  it("reads the live response the deployed endpoint actually returns", () => {
    const s = parseJobAlertIntake(LIVE)!;
    expect(s).not.toBeNull();
    expect(s.jobsCreated).toBe(23); // matched a real +23 on the Job table
    expect(s.jobsUpdated).toBe(23);
    expect(s.postingsExtracted).toBe(46);
    expect(s.postingsSkipped).toBe(2);
    expect(s.accountsScanned).toBe(2);
    expect(s.mailboxes).toHaveLength(2);
    expect(s.failedMailboxes).toBe(0);
    expect(s.platforms).toEqual([
      { platform: "seek", count: 2 },
      { platform: "michaelpage", count: 1 },
    ]);
    expect(jobAlertHeadline(s)).toBe("23 new jobs added to your board");
    expect(jobAlertTone(s)).toBe("success");
    // The parser-honesty note survives to the UI verbatim.
    expect(s.notes[0]).toContain("Nothing was fabricated.");
  });
});

describe("jobAlertHeadline / jobAlertTone — never claim more than the counts support", () => {
  it("no mailbox connected", () => {
    const s = parseJobAlertIntake(
      body({ connected: false, degraded: true, accounts_scanned: 0, messages_scanned: 0, alert_emails: 0, postings_extracted: 0, postings_skipped: 0, jobs_created: 0, jobs_updated: 0, per_account: [] }),
    )!;
    expect(jobAlertHeadline(s)).toBe("No Gmail mailbox connected — nothing could be scanned");
    expect(jobAlertTone(s)).toBe("warning");
  });

  it("a mailbox that could not be read is called out, not averaged away", () => {
    const s = parseJobAlertIntake(
      body({
        degraded: true,
        per_account: [
          { accountId: "a", email: "a", messagesScanned: 0, alertEmails: 0, postingsExtracted: 0, postingsSkipped: 0, jobsCreated: 0, jobsUpdated: 0, error: "RefreshError: invalid_grant" },
        ],
      }),
    )!;
    expect(jobAlertHeadline(s)).toBe("Scan incomplete — 1 mailbox could not be read");
    expect(jobAlertTone(s)).toBe("warning");
  });

  it("zero alert emails reads as zero — not as a successful import", () => {
    const s = parseJobAlertIntake(
      body({ alert_emails: 0, postings_extracted: 0, postings_skipped: 0, jobs_created: 0, jobs_updated: 0, platforms: {} }),
    )!;
    expect(jobAlertHeadline(s)).toBe("No job-alert emails in the scanned window");
    expect(jobAlertTone(s)).toBe("neutral");
  });

  it("alerts found but nothing complete enough to keep", () => {
    const s = parseJobAlertIntake(
      body({ postings_extracted: 0, postings_skipped: 4, jobs_created: 0, jobs_updated: 0 }),
    )!;
    expect(jobAlertHeadline(s)).toBe(
      "3 job-alert emails read, but no posting had a title, company and apply link",
    );
    expect(jobAlertTone(s)).toBe("neutral");
  });

  it("everything found was already on the board", () => {
    const s = parseJobAlertIntake(body({ jobs_created: 0, jobs_updated: 12, postings_skipped: 0 }))!;
    expect(jobAlertHeadline(s)).toBe("No new jobs — 12 postings were already on your board");
    expect(jobAlertTone(s)).toBe("neutral");
  });

  it("postings extracted but none persisted is a problem, not a success", () => {
    const s = parseJobAlertIntake(body({ jobs_created: 0, jobs_updated: 0 }))!;
    expect(jobAlertHeadline(s)).toBe("12 postings were read but none could be saved — see the notes below");
    expect(jobAlertTone(s)).toBe("warning");
  });

  it("only a real jobs_created > 0 gets the success wording", () => {
    const s = parseJobAlertIntake(body())!;
    expect(jobAlertHeadline(s)).toBe("9 new jobs added to your board");
    expect(jobAlertTone(s)).toBe("success");
    const one = parseJobAlertIntake(body({ jobs_created: 1 }))!;
    expect(jobAlertHeadline(one)).toBe("1 new job added to your board");
  });
});
