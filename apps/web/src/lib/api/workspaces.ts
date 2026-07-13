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
  apiRequest<InterviewPrep>("/interviews/prep", options);

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
  apiRequest<NetworkingSummary>("/networking/summary", options);

/* ------------------------------- Email Center ------------------------------ */

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
  intelligence: { score: number; breakdown: Array<{ label: string; value: number }>; summary: string };
  draftReply: string;
  voiceDna: number;
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
  apiRequest<EmailInbox>("/emails/inbox", options);

export const sendEmailReply = (messageId: string, body: string, options: RequestOptions = {}) =>
  apiRequest<{ status: string; messageId: string }>("/emails/send", {
    ...options,
    method: "POST",
    body: { message_id: messageId, body },
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
  apiRequest<OffersPayload>("/offers", options);

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
