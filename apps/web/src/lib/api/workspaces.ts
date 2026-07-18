/**
 * Typed clients for the workspace endpoints (Interview Center, Networking,
 * Email Center, Offers, Settings) plus the analytics market-pulse panel data.
 */
import { apiRequest, type RequestOptions } from "./client";

/* ----------------------------- Interview Center ----------------------------- */

export interface InterviewPrep {
  session: { role: string; company: string; round: string; scheduledFor: string; format: string } | null;
  compliance: { message: string; level: string };
  brief: { columns: Array<{ title: string; items: string[] }>; insight: string } | null;
  questions: Array<{ question: string; likelihood: "High" | "Medium" | "Low"; mappedStory: string; angle: string }>;
  liveAssist: {
    enabled: boolean;
    fillerWordsPerMin: number;
    wordsPerMin: number;
    talkListenRatio: { talk: number; listen: number };
    coachingCue: string;
  };
  debrief: { company: string; round: string; score: number; strengths: string[]; warnings: string[] } | null;
}

export const fetchInterviewPrep = (options: RequestOptions = {}) =>
  apiRequest<InterviewPrep>("/workspaces/interviews/prep", options);

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

export interface NetworkingContactCreateInput {
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
  score: number;
  receivedAt: string;
  account: string;
  body: string;
  // The inbox API returns `null` until a real AI-scoring backend is wired
  // (GAP-P4-041): the intelligence panel must render an honest empty state
  // rather than dereferencing a null object.
  intelligence: EmailIntelligence | null;
  draftReply: string;
  voiceDna: number;
}

/**
 * View-model for the AI-intelligence panel. Discriminated on `available` so the
 * UI cannot dereference a missing intelligence object (GAP-P4-041): when the
 * backend has no score yet (`intelligence: null`), the panel shows an honest
 * "not available yet" state instead of crashing.
 */
export type EmailIntelligenceView =
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

export interface EmailInbox {
  accounts: Array<{
    id: string | null;
    email: string;
    provider: string;
    status: string;
    isPrimary: boolean;
    unread: number;
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

export const fetchEmailInbox = (options: RequestOptions = {}) =>
  apiRequest<EmailInbox>("/workspaces/emails/inbox", options);

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

export interface DraftPayload {
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
  resume: { activeFile: string; uploadedAt: string; versions: number };
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
  probability: { score: number; label: string; note: string; factors: Array<{ label: string; value: number }> };
  employerActivity: Array<{ company: string; event: string; when: string; signal: string }>;
  recruiterTrends: { series: number[]; rows: Array<{ label: string; delta: string }> };
  marketVsYou: {
    /** False until a real external market-benchmark data provider is wired up. */
    marketDataConnected: boolean;
    comparisons: Array<{ label: string; market: number | null; you: number; unit?: string }>;
    summary: string;
  };
  trendIndicators: Array<{ label: string; delta: string; direction: string; series: number[] }>;
}

export const fetchMarketPulse = (options: RequestOptions = {}) =>
  apiRequest<MarketPulse>("/analytics/market-pulse", options);
