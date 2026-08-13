/**
 * Typed clients for the workspace endpoints (Interview Center, Networking,
 * Email Center, Offers, Settings) plus the analytics market-pulse panel data.
 */
import { apiRequest, type RequestOptions } from "./client";

/* ----------------------------- Interview Center ----------------------------- */


/* ------------------------------- Networking ------------------------------- */

export interface NetworkingContact {
  /** Present on every contact GET /workspaces/networking/summary returns —
   * optional here only so existing fixture literals without it still type-check. */
  id?: string;
  name: string;
  role: string;
  company: string;
  warmth: number;
  email?: string;
  linkedinUrl?: string;
}

/**
 * One row from GET /workspaces/networking/summary's `outreachQueue` /
 * `communicationLog` arrays. The backend (app/routers/workspaces.py
 * `networking_summary`) builds these from real `OutreachTask` rows and sends
 * `contactName`/`company`/`subject`/`kind`/`status`/`scheduledAt`/`sentAt` —
 * NOT the `to`/`preview`/`tone`/`when`/`who`/`channel`/`note` fields the UI
 * used to assume (MV-networking-002).
 */
export interface NetworkingOutreachEntry {
  id: string;
  kind: string;
  status: string;
  contactName: string;
  company: string;
  subject: string;
  scheduledAt: string | null;
  sentAt: string | null;
}

export interface NetworkingSummary {
  stats: { contacts: number; activeConversations: number; referralsInFlight: number; responseRate: number };
  pipeline: Array<{ stage: string; count: number; contacts: NetworkingContact[] }>;
  outreachQueue: NetworkingOutreachEntry[];
  communicationLog: NetworkingOutreachEntry[];
  crmSummary: { activeConversations: number; followUpsDueToday: number; warmIntrosPending: number };
}

export const fetchNetworkingSummary = (options: RequestOptions = {}) =>
  apiRequest<NetworkingSummary>("/workspaces/networking/summary", options);

/** A persisted Contact row exactly as GET/POST /networking/contacts return it
 * (app/routers/networking.py `_CONTACT_COLUMNS`). */
export interface NetworkingContactRecord {
  id: string;
  userId: string;
  name: string;
  title: string | null;
  company: string | null;
  stage: string;
  email: string | null;
  linkedinUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

interface NetworkingContactCreateInput {
  name: string;
  title?: string;
  company?: string;
  email?: string;
  linkedinUrl?: string;
  /** Defaults to "identified" server-side (ContactStage enum) when omitted. */
  stage?: string;
}

/** POST /networking/contacts (MV-networking-001) — the real create endpoint;
 * previously the "Add Contact" form only mutated client-side state. */
export const createNetworkingContact = (
  input: NetworkingContactCreateInput,
  options: RequestOptions = {},
) =>
  apiRequest<NetworkingContactRecord>("/networking/contacts", {
    ...options,
    method: "POST",
    body: {
      name: input.name,
      title: input.title || undefined,
      company: input.company || undefined,
      email: input.email || undefined,
      linkedin_url: input.linkedinUrl || undefined,
      stage: input.stage,
    },
  });

/** GET /networking/contacts/{id} (MV-networking-005 contact-detail view). */
export const fetchNetworkingContact = (contactId: string, options: RequestOptions = {}) =>
  apiRequest<NetworkingContactRecord>(`/networking/contacts/${contactId}`, options);

/** DELETE /networking/contacts/{id} (ML-networking-001) — the backend delete
 * endpoint existed but had NO UI affordance; the contact-detail panel now
 * wires it up. Returns 204 (no body). */
export const deleteNetworkingContact = (contactId: string, options: RequestOptions = {}) =>
  apiRequest<void>(`/networking/contacts/${contactId}`, { ...options, method: "DELETE" });

/* ------------------------------- Email Center ------------------------------ */

export interface EmailIntelligence {
  score: number;
  breakdown: Array<{ label: string; value: number }>;
  summary: string;
}

export interface EmailMessage {
  id: string;
  from: string;
  fromEmail: string;
  company: string;
  subject: string;
  preview: string;
  category: "priority" | "all" | "followup" | "auto" | "trashed";
  // REAL per-thread triage score (0-100), or `null` when the thread has never
  // been triaged (MV-email-center-001). Never a fabricated 0 — an un-triaged
  // thread genuinely has no score and the badge shows an em-dash.
  score: number | null;
  receivedAt: string;
  account: string;
  body: string;
  // Honest, server-computed marker (MF-1, wave-3.5 adversarial review fix):
  // true only when `body` above is genuinely NOT the complete content (the
  // bounded list response truncated it). The client must never guess this
  // from `body.length` — the server already knows definitively, including
  // the case where the real body was short enough that truncating it would
  // have been a no-op (bodyTruncated stays false there too).
  bodyTruncated: boolean;
  // The inbox API returns `null` here on load; deep intelligence (breakdown +
  // summary) is computed ON DEMAND per thread via POST /agents/email/run so the
  // inbox load never triggers 64 LLM calls.
  intelligence: EmailIntelligence | null;
  draftReply: string;
}

/**
 * View-model for the AI-intelligence panel. Discriminated on `available` so the
 * UI cannot dereference a missing intelligence object (GAP-P4-041): when no
 * intelligence has been computed yet (`intelligence: null`), the panel shows an
 * honest "not analyzed yet" state instead of crashing.
 */
type EmailIntelligenceView =
  | { available: false }
  | { available: true; score: number; breakdown: EmailIntelligence["breakdown"]; summary: string };

export function emailIntelligenceView(
  message: Pick<EmailMessage, "intelligence">,
): EmailIntelligenceView {
  const intel = message.intelligence;
  if (!intel) return { available: false };
  return {
    available: true,
    score: intel.score,
    breakdown: intel.breakdown ?? [],
    summary: intel.summary ?? "",
  };
}

/**
 * Display model for the per-thread score badge (MV-email-center-001). A thread
 * that has never been triaged has NO score (`null`) → an honest em-dash, never a
 * fabricated 0 that would read as a real "irrelevant" verdict.
 */
export function emailScoreBadge(score: number | null): { text: string; scored: boolean } {
  if (typeof score !== "number") return { text: "—", scored: false };
  return { text: String(score), scored: true };
}

/**
 * Lift the REAL insights object out of a POST /agents/email/run (mode=insights)
 * response. Returns `null` (honest empty state) when the agent produced no
 * usable score — never a fabricated 0. Malformed breakdown rows are dropped.
 */
export function parseEmailInsights(resp: Record<string, unknown>): EmailIntelligence | null {
  const raw = resp?.insights;
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (typeof obj.score !== "number") return null;
  const breakdown = Array.isArray(obj.breakdown)
    ? obj.breakdown.filter(
        (b): b is { label: string; value: number } =>
          !!b &&
          typeof b === "object" &&
          typeof (b as { label?: unknown }).label === "string" &&
          typeof (b as { value?: unknown }).value === "number",
      )
    : [];
  return {
    score: obj.score,
    breakdown,
    summary: typeof obj.summary === "string" ? obj.summary : "",
  };
}

/**
 * Lift the REAL draft text out of a POST /agents/email/run (mode=draft_reply)
 * response. Returns "" when the agent produced no draft.
 */
export function parseEmailDraft(resp: Record<string, unknown>): string {
  return typeof resp?.draft === "string" ? resp.draft : "";
}

/**
 * The fabrication-guard flags the emailAgent attached to a draft (claims with no
 * evidence in the resume / incoming email). Surfaced honestly so the user knows
 * to double-check, never silently swallowed.
 */
export function parseEmailDraftFlags(resp: Record<string, unknown>): string[] {
  return Array.isArray(resp?.flagged)
    ? (resp.flagged as unknown[]).filter((f): f is string => typeof f === "string")
    : [];
}

/**
 * An honest per-sender LinkedIn *search* URL (MV-email-center-007) — a people
 * search by the sender's name (+ company), NOT a fabricated "profile" link that
 * always pointed at linkedin.com/. Returns `null` when there is no real name to
 * search, so the caller omits the link entirely.
 */
export function linkedInSearchUrl(name: string, company?: string): string | null {
  const trimmed = (name || "").trim();
  if (!trimmed || trimmed.toLowerCase() === "unknown") return null;
  const keywords = [trimmed, (company || "").trim()].filter(Boolean).join(" ");
  return `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(keywords)}`;
}

export interface EmailInbox {
  accounts: Array<{
    id: string | null;
    email: string;
    provider: string;
    status: string;
    isPrimary: boolean;
    unread: number;
    // GMV4-email-001. The API has always sent these (routers/workspaces.py) —
    // `actionRequired` plus a human-readable `note` explaining an expired or
    // revoked Gmail grant. They were simply never declared here, so the
    // backend's own honest wording was discarded before any component saw it.
    // Optional because the shape predates them.
    actionRequired?: boolean;
    note?: string | null;
  }>;
  stats: {
    received: number;
    recruiterEmails: number;
    autoDrafted: number;
    sentApproved: number;
    followUpsSent: number;
    avgResponseHrs: number;
  };
  followUps: Array<{ company: string; role: string; dueIn: string; status: string }>;
  messages: EmailMessage[];
  recruiterProfile: { name: string; role: string; history: string; notes: string } | null;
}

/** One linked mailbox, exactly as the inbox endpoint reports it. Named so
 *  components and tests can talk about a single account without restating the
 *  inline shape (and drifting from it). */
export type EmailInboxAccount = EmailInbox["accounts"][number];

export const fetchEmailInbox = (options: RequestOptions = {}) =>
  apiRequest<EmailInbox>("/workspaces/emails/inbox", options);

/**
 * Fetch ONE thread's real, full (untruncated) body on demand (W-13 / QA #2).
 * The default GET /workspaces/emails/inbox response is now bounded to the
 * most recent threads with `body` truncated to a snippet, so the list
 * payload stays small regardless of inbox size (was 723KB/~148 full bodies
 * on every load). The detail panel calls this when a thread is selected to
 * get its real content — never the truncated snippet passed off as the
 * whole email. Returns `null` if the thread doesn't exist (or isn't this
 * user's), so the caller can fall back to whatever it already has.
 */
export async function fetchEmailThreadBody(
  threadId: string,
  options: RequestOptions = {},
): Promise<string | null> {
  const data = await apiRequest<EmailInbox>(
    `/workspaces/emails/inbox?thread_id=${encodeURIComponent(threadId)}`,
    options,
  );
  return data.messages.find((m) => m.id === threadId)?.body ?? null;
}

export const sendEmailReply = (messageId: string, body: string, options: RequestOptions = {}) =>
  apiRequest<{ status: string; messageId: string }>("/workspaces/emails/send", {
    ...options,
    method: "POST",
    body: { message_id: messageId, body },
  });

/**
 * Turn a failed send into an honest, human-facing message (GAP-P4-042).
 * The API returns `409 {"detail": {"error": ..., "message": ...}}` when no
 * email provider is connected; `ApiError.message` embeds that JSON, so we lift
 * out the `detail.message` when present and fall back to the raw error text.
 */
export function emailSendErrorMessage(error: unknown): string {
  const fallback = error instanceof Error ? error.message : "Send failed";
  if (!(error instanceof Error)) return fallback;
  const match = error.message.match(/\{[\s\S]*\}$/);
  if (!match) return fallback;
  try {
    const parsed = JSON.parse(match[0]) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) return message;
    }
  } catch {
    // Not JSON — surface the raw error text.
  }
  return fallback;
}

interface DraftPayload {
  subject: string;
  body: string;
  application_id?: string;
  contact_id?: string;
  classification?: string;
}

export const createEmailDraft = (payload: DraftPayload, options: RequestOptions = {}) =>
  apiRequest<Record<string, unknown>>("/emails/draft", {
    ...options,
    method: "POST",
    body: payload,
  });

/* --------------------------------- Offers --------------------------------- */

export interface Offer {
  id: string;
  company: string;
  role: string;
  total: number;
  base: number;
  bonus: number;
  equity: number;
  location: string;
  /** ISO currency code the figures are in (e.g. "AUD") — MV-offer-comparison-006. */
  currency: string;
  /** null for manually-added offers with no agent fit score yet ("Pending"). */
  fitScore: number | null;
  topPick: boolean;
  deadline: string;
  /** "application" = derived from an Application(status='offer'); "manual" =
   * user-entered via Add Offer (deletable). MV-offer-comparison-001/005. */
  source: "application" | "manual";
}

export interface OffersPayload {
  offers: Offer[];
  weights: Array<{ key: string; label: string; weight: number }>;
  /** suggestedCounter is null when there is no base to anchor on — the coach
   * then shows an honest "add an offer" state (never a fabricated $0). */
  negotiation: { insight: string; suggestedCounter: number | null; leverage: string[] };
}

/** Fields the Add-Offer form persists via POST /workspaces/offers. */
export interface OfferCreateInput {
  company: string;
  role?: string;
  base: number;
  bonus: number;
  equity: number;
  location: string;
  currency: string;
}

export const fetchOffers = (options: RequestOptions = {}) =>
  apiRequest<OffersPayload>("/workspaces/offers", options);

/** MV-offer-comparison-001 — persist a user-entered offer (real backend write,
 * replacing the old client-only mock). */
export const createOffer = (input: OfferCreateInput, options: RequestOptions = {}) =>
  apiRequest<Offer>("/workspaces/offers", {
    ...options,
    method: "POST",
    body: {
      company: input.company,
      role: input.role || undefined,
      base: input.base,
      bonus: input.bonus,
      equity: input.equity,
      location: input.location,
      currency: input.currency,
    },
  });

/** Delete one of the user's own manually-added offers. */
export const deleteOffer = (offerId: string, options: RequestOptions = {}) =>
  apiRequest<void>(`/workspaces/offers/${offerId}`, { ...options, method: "DELETE" });

/* -------------------------------- Settings -------------------------------- */

export interface SettingsPayload {
  profile: { fullName: string; email: string; targetRole: string; location: string };
  resume: {
    /** `null` when the user has no resume at all (see workspaces.py's
     * `_build_settings` — never coerced to `""`). F-3 refix: this used to be
     * typed as a plain `string`, which forced a `null as unknown as string`
     * cast into the no-resume test fixture — the exact suppression pattern
     * PLAN.md bans. */
    activeFile: string | null;
    uploadedAt: string | null;
    versions: number;
    /** U2a (R-F1), re-refixed 2026-08-13 per the ORCHESTRATOR RULING
     * (NEW-2/F-2): whether the user's BASELINE résumé — the most recent
     * root upload (`parentId IS NULL`) with stored original bytes, NOT
     * necessarily `activeFile` above — has its original upload bytes
     * stored (immutable baseline). A tailored child is never the baseline,
     * so a tailoring run never flips this to false; false for accounts
     * with no byte-stored root upload at all (pre-feature uploads, or no
     * resume yet). See workspaces.py's `_build_settings`/`base_resume_row`. */
    originalStored: boolean;
  };
  portfolio: { url: string | null; cadence: string | null; lastSynced: string | null; status?: string };
  agentConfig: { autoApply: boolean; approvalGate: boolean; matchThreshold: number };
  integrations: Array<{ name: string; status: string; detail: string }>;
  connectedAccounts: Array<{ name: string; detail: string; status: string }>;
}

export const fetchSettings = (options: RequestOptions = {}) =>
  apiRequest<SettingsPayload>("/workspaces/settings", options);

export const saveSettings = (
  profile: SettingsPayload["profile"],
  agentConfig: SettingsPayload["agentConfig"],
  options: RequestOptions = {},
) =>
  apiRequest<SettingsPayload>("/workspaces/settings", {
    ...options,
    method: "PUT",
    body: { profile, agentConfig },
  });

/* ------------------------------ Career Data ------------------------------ */

/** One consolidated career-data source (GAP-P4-047 · ADR D-0031). */
export type CareerSourceName = "github" | "portfolio" | "linkedin";

export interface CareerDataSource {
  source: CareerSourceName;
  status: "ok" | "empty" | "error" | "not_configured" | "pending" | string;
  url: string | null;
  summary: string | null;
  error: string | null;
  lastSynced: string | null;
}

export interface CareerData {
  sources: CareerDataSource[];
  linkedinNote: string;
}

/**
 * Refresh inputs. An omitted field reuses the previously stored value for that
 * source; an explicit empty string clears it (matches the API contract in
 * `app.services.career_data.refresh_career_data`).
 */
export interface CareerDataRefreshInput {
  githubUsername?: string;
  portfolioUrl?: string;
  linkedinSummary?: string;
}

export const fetchCareerData = (options: RequestOptions = {}) =>
  apiRequest<CareerData>("/workspaces/career-data", options);

export const refreshCareerData = (input: CareerDataRefreshInput, options: RequestOptions = {}) =>
  apiRequest<CareerData>("/workspaces/career-data/refresh", {
    ...options,
    method: "POST",
    body: input,
  });

/* ------------------------------ Market pulse ------------------------------ */

export interface MarketPulse {
  sources: Array<{ label: string; value: number; color: string }>;
  sourcesTotal: number;
  /** Honest caption for sourcesTotal (a Job-source count, not applications). */
  sourcesLabel: string;
  topSkills: Array<{ skill: string; demand: number }>;
  activityHeatmap: number[][];
  /**
   * Job-search progress index. The wire key is historical — this is NOT a
   * probability of anything (PROD-UAT-2026-08-03 F-04): it is the unweighted
   * average of whichever of the user's OWN measured signals have data.
   *
   * `score` and every `factors[].value` are `number | null`, and `strict`
   * mode makes that the enforcement: `score / 100` and `` `${value}%` `` on a
   * possibly-null value are compile errors, so a consumer physically cannot
   * render a not-measured signal as a number the way the old
   * `{ score: number; value: number }` shape invited.
   */
  probability: {
    /** null when no factor has data yet — render "not measured", never 0. */
    score: number | null;
    measured: boolean;
    label: string;
    note: string;
    /** Full derivation, including what this number explicitly is not. */
    methodology: string;
    /** Populated exactly when `score` is null. */
    unmeasuredReason: string | null;
    /**
     * DECOUPLED from `marketVsYou` (D-0042 / R5, I2 slice): the probability
     * model uses zero market evidence and this stays a flat `false`
     * regardless of whether Market vs. You has real, live, connected rows —
     * the two panels are explicitly allowed to disagree once Market vs. You
     * has live Adzuna data. This flag governs ONLY this panel's own caveat.
     */
    marketDataConnected: boolean;
    factors: Array<{ label: string; value: number | null; measured: boolean }>;
  };
  employerActivity: Array<{ company: string; event: string; when: string; signal: string }>;
  recruiterTrends: { series: number[]; rows: Array<{ label: string; delta: string }> };
  marketVsYou: {
    /**
     * TRANSITIONAL (I1→I3, D-0042 / R5): the backend still sends this global
     * flag for one more slice so an old deployed frontend's amber banner
     * honestly disappears once real data shows. It is unread by this UI —
     * every row now carries its own `connected`/`dataAsOf` provenance below.
     * Removed from the payload in I3; kept optional here so this type still
     * matches the live wire shape without the UI depending on it.
     */
    marketDataConnected?: boolean;
    comparisons: Array<{
      label: string;
      market: number | null;
      you: number | null;
      unit?: string;
      /** Per-row provenance (D-0042 / R2-R5) — replaces the old global flag. */
      connected: boolean;
      /** ISO-8601 timestamp of the fetch behind `market`, or `null` when
       * `connected` is false. */
      dataAsOf: string | null;
      /** Honest one-line explanation of what `market` actually measures
       * (e.g. postings-count scope), present only on connected rows that
       * warrant it. */
      marketNote?: string;
      /** Honest caveat rendered under the row regardless of `connected`
       * (e.g. "no benchmark provider exists" / "no disclosed salary data"). */
      footnote?: string;
    }>;
    summary: string;
  };
  trendIndicators: Array<{
    label: string;
    delta: string;
    direction: string;
    /**
     * R-04/RULING-C (AX re-review round 2): whether `delta` is a genuine
     * computable percentage, a zero-base rise with no honest magnitude
     * ("new" — e.g. this user's first-ever scored week), or not enough
     * complete-period data to compare at all ("insufficient-data" — e.g.
     * an average series with a null gap on one side). The FE must never
     * run "new"/"insufficient-data" values through percent styling/copy.
     */
    deltaKind: "percent" | "new" | "insufficient-data";
    /**
     * `null` entries are real, honestly-absent weeks (RULING-B: an AVERAGE
     * series — e.g. "Avg job fit score" — never fabricates 0 for a week
     * with nothing measured). COUNT/SUM series are zero-filled and never
     * contain `null`.
     */
    series: Array<number | null>;
  }>;
  /**
   * MON-015: the IANA zone the activity heatmap / weekly trend day-and-week
   * boundaries are bucketed in (e.g. "Australia/Melbourne"). Optional so an
   * older cached payload shape still satisfies this type; absent entirely
   * only if the backend has not deployed the fix yet.
   */
  timezone?: string;
}

export const fetchMarketPulse = (options: RequestOptions = {}) =>
  apiRequest<MarketPulse>("/analytics/market-pulse", options);
