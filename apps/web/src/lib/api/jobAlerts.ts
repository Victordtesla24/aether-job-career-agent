/**
 * Job-alert email intake — the client half of the email agent's `job_alerts`
 * mode (`apps/api/app/agents/email_agent.py::EmailAgent._job_alerts`).
 *
 * The backend reads the candidate's OWN automated job-alert mail across every
 * connected mailbox with a deterministic regex/HTML parser (no LLM, by design)
 * and persists each complete posting through the ordinary `JobRepository.create`
 * upsert, so the board treats an alert-sourced listing exactly like a
 * board-adapter one. It returns a dataclass of REAL counts; the router
 * `asdict`s it, so the wire shape is snake_case.
 *
 * This module is the ONLY place that reads that shape. Two rules it enforces:
 *
 * 1. NOTHING IS INVENTED. A body that is not a job-alert result — wrong mode,
 *    missing counts, a non-numeric count — parses to `null`, so the UI says it
 *    could not read the result instead of rendering a zero-filled summary that
 *    looks like a real scan that found nothing.
 * 2. NO CLAIM BEYOND THE COUNTS. `jobAlertHeadline` derives its sentence from
 *    the numbers alone, and only `jobsCreated > 0` earns success wording. Zero
 *    alerts, alerts-with-no-complete-posting, everything-already-known, and
 *    read-but-not-saved each have their own honest phrasing.
 */
import { runAgent } from "./agents";
import type { RequestOptions } from "./client";

/** One mailbox's slice of a scan. Counts are `null` when the server did not
 *  report them — never silently 0. */
export interface JobAlertMailbox {
  accountId: string | null;
  /** Server-masked address (the backend masks it before persisting). */
  email: string | null;
  messagesScanned: number | null;
  alertEmails: number | null;
  postingsExtracted: number | null;
  postingsSkipped: number | null;
  jobsCreated: number | null;
  jobsUpdated: number | null;
  /** The real exception text when this mailbox could not be read. */
  error: string | null;
}

export interface JobAlertIntakeSummary {
  connected: boolean;
  degraded: boolean;
  /** The server's own sentence, rendered verbatim. */
  message: string;
  accountsScanned: number;
  messagesScanned: number;
  alertEmails: number;
  postingsExtracted: number;
  postingsSkipped: number;
  jobsCreated: number;
  jobsUpdated: number;
  /** `{platform: alertEmailCount}` flattened, highest first. */
  platforms: Array<{ platform: string; count: number }>;
  mailboxes: JobAlertMailbox[];
  /** Mailboxes whose scan errored — the count behind the "incomplete" wording. */
  failedMailboxes: number;
  /** Plain-English parser notes (why an alert produced nothing). */
  notes: string[];
}

const JOB_ALERT_MODES = new Set(["job_alerts", "job-alerts"]);

/** A real, non-negative integer count — or `null` for anything else. */
function count(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  return Math.trunc(value);
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function parseMailbox(raw: unknown): JobAlertMailbox | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  return {
    accountId: text(row.accountId),
    email: text(row.email),
    messagesScanned: count(row.messagesScanned),
    alertEmails: count(row.alertEmails),
    postingsExtracted: count(row.postingsExtracted),
    postingsSkipped: count(row.postingsSkipped),
    jobsCreated: count(row.jobsCreated),
    jobsUpdated: count(row.jobsUpdated),
    error: text(row.error),
  };
}

/**
 * Read a POST /agents/email/run body produced by `mode: "job_alerts"`.
 * Returns `null` when the body is not a readable job-alert result.
 */
export function parseJobAlertIntake(raw: unknown): JobAlertIntakeSummary | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const body = raw as Record<string, unknown>;
  if (typeof body.mode !== "string" || !JOB_ALERT_MODES.has(body.mode)) return null;

  const accountsScanned = count(body.accounts_scanned);
  const messagesScanned = count(body.messages_scanned);
  const alertEmails = count(body.alert_emails);
  const postingsExtracted = count(body.postings_extracted);
  const postingsSkipped = count(body.postings_skipped);
  const jobsCreated = count(body.jobs_created);
  const jobsUpdated = count(body.jobs_updated);
  const core = [
    accountsScanned,
    messagesScanned,
    alertEmails,
    postingsExtracted,
    postingsSkipped,
    jobsCreated,
    jobsUpdated,
  ];
  // A missing core count means we do not know what the run did. Saying so is
  // the honest outcome; back-filling 0 would render as a completed empty scan.
  if (core.some((v) => v === null)) return null;

  const platformsRaw =
    body.platforms && typeof body.platforms === "object" && !Array.isArray(body.platforms)
      ? (body.platforms as Record<string, unknown>)
      : {};
  const platforms = Object.entries(platformsRaw)
    .map(([platform, value]) => ({ platform, count: count(value) }))
    .filter((p): p is { platform: string; count: number } => p.count !== null)
    .sort((a, b) => b.count - a.count || a.platform.localeCompare(b.platform));

  const mailboxes = (Array.isArray(body.per_account) ? body.per_account : [])
    .map(parseMailbox)
    .filter((m): m is JobAlertMailbox => m !== null);

  const notes = (Array.isArray(body.notes) ? body.notes : [])
    .map(text)
    .filter((n): n is string => n !== null);

  return {
    connected: body.connected === true,
    degraded: body.degraded === true,
    message: typeof body.message === "string" ? body.message : "",
    accountsScanned: accountsScanned!,
    messagesScanned: messagesScanned!,
    alertEmails: alertEmails!,
    postingsExtracted: postingsExtracted!,
    postingsSkipped: postingsSkipped!,
    jobsCreated: jobsCreated!,
    jobsUpdated: jobsUpdated!,
    platforms,
    mailboxes,
    failedMailboxes: mailboxes.filter((m) => m.error !== null).length,
    notes,
  };
}

function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many;
}

/**
 * The one-line verdict, derived from the counts alone. Ordered so the WORST
 * true statement wins: a scan that could not read a mailbox is never summarised
 * by what the other mailbox happened to find.
 */
export function jobAlertHeadline(s: JobAlertIntakeSummary): string {
  if (!s.connected) return "No Gmail mailbox connected — nothing could be scanned";
  if (s.failedMailboxes > 0) {
    return `Scan incomplete — ${s.failedMailboxes} ${plural(s.failedMailboxes, "mailbox", "mailboxes")} could not be read`;
  }
  if (s.alertEmails === 0) return "No job-alert emails in the scanned window";
  if (s.postingsExtracted === 0) {
    return `${s.alertEmails} job-alert ${plural(s.alertEmails, "email")} read, but no posting had a title, company and apply link`;
  }
  if (s.jobsCreated === 0) {
    if (s.jobsUpdated > 0) {
      return `No new jobs — ${s.jobsUpdated} ${plural(s.jobsUpdated, "posting")} were already on your board`;
    }
    return `${s.postingsExtracted} ${plural(s.postingsExtracted, "posting")} were read but none could be saved — see the notes below`;
  }
  return `${s.jobsCreated} new ${plural(s.jobsCreated, "job")} added to your board`;
}

/** How the result should read: only a real import is a success. */
export function jobAlertTone(s: JobAlertIntakeSummary): "success" | "neutral" | "warning" {
  if (!s.connected || s.failedMailboxes > 0) return "warning";
  if (s.postingsExtracted > 0 && s.jobsCreated === 0 && s.jobsUpdated === 0) return "warning";
  if (s.jobsCreated > 0) return "success";
  return "neutral";
}

/** Raised when the run returned a body this client cannot read as a scan. */
export class JobAlertResultUnreadable extends Error {
  constructor() {
    super(
      "The scan ran but the server returned a result this screen could not read — " +
        "no counts are shown because none can be trusted.",
    );
    this.name = "JobAlertResultUnreadable";
  }
}

export interface JobAlertIntakeParams {
  /** How far back to scan each mailbox (server clamps to 1–30; default 7). */
  days?: number;
  /** Per-mailbox message budget (server clamps to 1–500; default 200). */
  maxMessages?: number;
  /** Restrict to ONE connected mailbox. Omit to scan them all. */
  accountId?: string;
}

/**
 * Run the intake. Sends exactly the params the backend's `EmailAgentRequest`
 * declares — `mode: "job_alerts"` is what routes to `EmailAgent._job_alerts`.
 */
export async function runJobAlertIntake(
  params: JobAlertIntakeParams = {},
  options: RequestOptions = {},
): Promise<JobAlertIntakeSummary> {
  const payload: Record<string, unknown> = { mode: "job_alerts" };
  if (params.days !== undefined) payload.days = params.days;
  if (params.maxMessages !== undefined) payload.max_messages = params.maxMessages;
  if (params.accountId !== undefined) payload.account_id = params.accountId;
  const summary = parseJobAlertIntake(await runAgent("email", payload, options));
  if (!summary) throw new JobAlertResultUnreadable();
  return summary;
}
