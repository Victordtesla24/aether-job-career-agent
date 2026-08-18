/**
 * U5d-3 — typed client for the Answer Bank (ADR-SUB-AUTON-1 Pillar 1).
 *
 * The bank is the user's own words. Nothing in this module generates,
 * completes or suggests an answer: it reads what the server stored and posts
 * what the user typed. The two honesty facts the UI must never invent —
 * whether an answer will be sent automatically (`autoAnswers`) and WHY NOT
 * (`gateReason`) — are computed on the server and simply rendered here.
 *
 * Every schema is nullish-tolerant on additive fields for the same reason the
 * applications client is: an older API build must degrade to "we don't know",
 * never to a blank page thrown by a parse error.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const SENSITIVITY_LABELS: Record<string, string> = {
  factual: "Stable fact",
  judgment: "Your judgement",
  sensitive: "Sensitive / legal",
};

export const PROVENANCE_LABELS: Record<string, string> = {
  user_answered: "You answered this on an application",
  onboarding: "You answered this in the setup questionnaire",
  profile_confirmed: "Taken from your profile and confirmed by you",
};

export const AnswerBankUsageSchema = z.object({
  applicationId: z.string().nullish(),
  jobId: z.string().nullish(),
  questionAsSeen: z.string(),
  matchConfidence: z.number(),
  matchMethod: z.string(),
  usedAt: z.string(),
});

export type AnswerBankUsage = z.infer<typeof AnswerBankUsageSchema>;

export const AnswerBankItemSchema = z.object({
  id: z.string(),
  questionText: z.string(),
  semanticKey: z.string(),
  answer: z.string(),
  scope: z.string(),
  scopeValue: z.string().nullish(),
  provenance: z.string(),
  provenanceDetail: z.string().nullish(),
  sensitivity: z.string(),
  staleDays: z.number().nullish(),
  expiresAt: z.string().nullish(),
  expired: z.boolean(),
  autoAnswerOptIn: z.boolean(),
  /** Will Aether send this WITHOUT asking? Server-decided; never re-derived. */
  autoAnswers: z.boolean(),
  canOptIn: z.boolean(),
  gateReason: z.string(),
  timesUsed: z.number(),
  lastUsedAt: z.string().nullish(),
  createdAt: z.string().nullish(),
  updatedAt: z.string().nullish(),
  usedOn: z.array(AnswerBankUsageSchema).default([]),
});

export type AnswerBankItem = z.infer<typeof AnswerBankItemSchema>;

const BankListSchema = z.object({
  items: z.array(AnswerBankItemSchema),
  autoAnswerThreshold: z.number(),
});

export type AnswerBankList = z.infer<typeof BankListSchema>;

export const SeedQuestionSchema = z.object({
  concept: z.string(),
  question: z.string(),
  sensitivity: z.string(),
  helper: z.string(),
  placeholder: z.string(),
  staleDays: z.number().nullish(),
  autoAnswerable: z.boolean(),
});

export type SeedQuestion = z.infer<typeof SeedQuestionSchema>;

const QuestionnaireSchema = z.object({
  questions: z.array(SeedQuestionSchema),
  answeredConcepts: z.array(z.string()).default([]),
  autoAnswerThreshold: z.number(),
});

export type Questionnaire = z.infer<typeof QuestionnaireSchema>;

const SeedRemainingSchema = z.object({
  concept: z.string(),
  question: z.string(),
  sensitivity: z.string(),
});

/**
 * SETUP-1 — how far the bank can already act, as counts of stored rows.
 *
 * There is no blended "autonomy score" here on purpose (see
 * `answer_bank.readiness_summary`): every field is a count of something that
 * exists, so the UI states facts instead of scoring them.
 */
const ReadinessSchema = z.object({
  seedTotal: z.number(),
  seedCovered: z.number(),
  seedRemaining: z.array(SeedRemainingSchema).default([]),
  /** The factual subset that decides whether a submission can go out alone. */
  essentialTotal: z.number(),
  essentialCovered: z.number(),
  setupComplete: z.boolean(),
  liveAnswers: z.number(),
  expiredAnswers: z.number(),
  autoAnswerable: z.number(),
  gatedAnswers: z.number(),
  /** Recorded occurrences of the bank answering instead of stopping to ask. */
  timesAnswered: z.number(),
  /** Answers a real application taught the agent — the learning loop's output. */
  learnedFromApplications: z.number(),
  /** Applications standing on an unanswered question right now. */
  applicationsWaiting: z.number(),
  autoAnswerThreshold: z.number(),
});

export type AnswerBankReadiness = z.infer<typeof ReadinessSchema>;

export async function fetchAnswerBankReadiness(
  options: RequestOptions = {},
): Promise<AnswerBankReadiness> {
  return ReadinessSchema.parse(
    await apiRequest<unknown>("/answer-bank/readiness", options),
  );
}

const QuestionnaireResultSchema = z.object({
  banked: z.number(),
  skipped: z.number(),
  items: z.array(AnswerBankItemSchema).default([]),
  detail: z.string(),
});

export type QuestionnaireResult = z.infer<typeof QuestionnaireResultSchema>;

export async function fetchAnswerBank(options: RequestOptions = {}): Promise<AnswerBankList> {
  return BankListSchema.parse(await apiRequest<unknown>("/answer-bank", options));
}

export async function fetchQuestionnaire(
  options: RequestOptions = {},
): Promise<Questionnaire> {
  return QuestionnaireSchema.parse(
    await apiRequest<unknown>("/answer-bank/questionnaire", options),
  );
}

export async function submitQuestionnaire(
  answers: Array<{ question: string; answer: string }>,
  options: RequestOptions = {},
): Promise<QuestionnaireResult> {
  return QuestionnaireResultSchema.parse(
    await apiRequest<unknown>("/answer-bank/questionnaire", {
      ...options,
      method: "POST",
      body: { answers },
    }),
  );
}

export async function bankAnswer(
  question: string,
  answer: string,
  options: RequestOptions = {},
): Promise<AnswerBankItem> {
  return AnswerBankItemSchema.parse(
    await apiRequest<unknown>("/answer-bank", {
      ...options,
      method: "POST",
      body: { question, answer },
    }),
  );
}

export async function updateAnswer(
  id: string,
  patch: { answer?: string; autoAnswerOptIn?: boolean },
  options: RequestOptions = {},
): Promise<AnswerBankItem> {
  return AnswerBankItemSchema.parse(
    await apiRequest<unknown>(`/answer-bank/${id}`, {
      ...options,
      method: "PATCH",
      body: patch,
    }),
  );
}

export async function expireAnswer(
  id: string,
  options: RequestOptions = {},
): Promise<AnswerBankItem> {
  return AnswerBankItemSchema.parse(
    await apiRequest<unknown>(`/answer-bank/${id}/expire`, { ...options, method: "POST" }),
  );
}

export async function deleteAnswer(id: string, options: RequestOptions = {}): Promise<void> {
  await apiRequest<unknown>(`/answer-bank/${id}`, { ...options, method: "DELETE" });
}

const AnswerQuestionResultSchema = z.object({
  applicationId: z.string(),
  banked: z
    .array(
      z.object({
        id: z.string(),
        questionText: z.string(),
        sensitivity: z.string(),
        provenance: z.string(),
        reusable: z.boolean(),
      }),
    )
    .default([]),
  remainingQuestions: z.array(z.string()).default([]),
  /** The paused browser session was NOT resumed — U5d-4 owns that. */
  resumed: z.boolean(),
  transmitted: z.literal(false),
  detail: z.string(),
});

export type AnswerQuestionResult = z.infer<typeof AnswerQuestionResultSchema>;

/**
 * U5d-3 Pillar 4a — answer the employer's question from inside the card.
 *
 * Transmits NOTHING. It banks the answer and records it against this
 * application; the response's `resumed: false` / `transmitted: false` are the
 * server's own words about what did and did not happen, and the card renders
 * them rather than inferring an outcome.
 */
export async function answerApplicationQuestion(
  applicationId: string,
  answers: Array<{ question: string; answer: string }>,
  options: RequestOptions = {},
): Promise<AnswerQuestionResult> {
  return AnswerQuestionResultSchema.parse(
    await apiRequest<unknown>(`/applications/${applicationId}/answer-question`, {
      ...options,
      method: "POST",
      body: { answers },
    }),
  );
}
