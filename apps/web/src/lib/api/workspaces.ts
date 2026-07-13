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
  name: string;
  role: string;
  company: string;
  warmth: number;
}

export interface NetworkingSummary {
  stats: { contacts: number; activeConversations: number; referralsInFlight: number; responseRate: number };
  pipeline: Array<{ stage: string; count: number; contacts: NetworkingContact[] }>;
  outreachQueue: Array<{ to: string; subject: string; preview: string; tone: string }>;
  communicationLog: Array<{ when: string; who: string; channel: string; note: string }>;
  crmSummary: { activeConversations: number; followUpsDueToday: number; warmIntrosPending: number };
}

export const fetchNetworkingSummary = (options: RequestOptions = {}) =>
  apiRequest<NetworkingSummary>("/workspaces/networking/summary", options);

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
  accounts: Array<{ email: string; provider: string; status: string; unread: number }>;
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
  fitScore: number;
  topPick: boolean;
  deadline: string;
}

export interface OffersPayload {
  offers: Offer[];
  weights: Array<{ key: string; label: string; weight: number }>;
  negotiation: { insight: string; suggestedCounter: number; leverage: string[] };
}

export const fetchOffers = (options: RequestOptions = {}) =>
  apiRequest<OffersPayload>("/workspaces/offers", options);

/* -------------------------------- Settings -------------------------------- */

export interface SettingsPayload {
  profile: { fullName: string; email: string; targetRole: string; location: string };
  resume: { activeFile: string; uploadedAt: string; versions: number };
  portfolio: { url: string; cadence: string; lastSynced: string };
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

/* ------------------------------ Market pulse ------------------------------ */

export interface MarketPulse {
  sources: Array<{ label: string; value: number; color: string }>;
  sourcesTotal: number;
  topSkills: Array<{ skill: string; demand: number }>;
  activityHeatmap: number[][];
  probability: { score: number; label: string; note: string; factors: Array<{ label: string; value: number }> };
  employerActivity: Array<{ company: string; event: string; when: string; signal: string }>;
  recruiterTrends: { series: number[]; rows: Array<{ label: string; delta: string }> };
  marketVsYou: {
    comparisons: Array<{ label: string; market: number; you: number; unit?: string }>;
    summary: string;
  };
  trendIndicators: Array<{ label: string; delta: string; direction: string; series: number[] }>;
}

export const fetchMarketPulse = (options: RequestOptions = {}) =>
  apiRequest<MarketPulse>("/analytics/market-pulse", options);
