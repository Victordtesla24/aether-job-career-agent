/**
 * U5d-3 — the Answer Bank page's honesty-bearing logic.
 *
 * ADR-SUB-AUTON-1 Pillar 1 promises the user can *"see where each was used"*.
 * These tests pin that the page reports RECORDED usage and never fills a gap:
 * an answer nobody has needed yet says so, and the "will this be sent
 * automatically?" verdict is read from the server rather than re-derived.
 */
import { describe, expect, it } from "vitest";

import type { AnswerBankItem } from "../../../../lib/api/answer-bank";
import {
  applyFilter,
  confidencePercent,
  distinctApplications,
  statusLabel,
  summarise,
  unansweredConcepts,
  usageSummary,
} from "../answer-bank-lib";

function item(overrides: Partial<AnswerBankItem> = {}): AnswerBankItem {
  return {
    id: "itm_1",
    questionText: "What is your notice period?",
    semanticKey: "concept:notice_period",
    answer: "4 weeks",
    scope: "global",
    scopeValue: "",
    provenance: "onboarding",
    provenanceDetail: null,
    sensitivity: "factual",
    staleDays: 180,
    expiresAt: null,
    expired: false,
    autoAnswerOptIn: false,
    autoAnswers: true,
    canOptIn: true,
    gateReason: "Answer it once and Aether can answer it for you next time.",
    timesUsed: 0,
    lastUsedAt: null,
    createdAt: null,
    updatedAt: null,
    usedOn: [],
    ...overrides,
  };
}

describe("summarise", () => {
  it("counts automatic, gated and expired answers separately", () => {
    const summary = summarise([
      item({ id: "a", autoAnswers: true, timesUsed: 3 }),
      item({ id: "b", autoAnswers: false, sensitivity: "sensitive", timesUsed: 0 }),
      item({ id: "c", autoAnswers: false, expired: true, timesUsed: 1 }),
    ]);
    expect(summary).toEqual({
      total: 3,
      automatic: 1,
      gated: 1,
      expired: 1,
      timesUsed: 4,
    });
  });

  it("reports an empty bank as empty, never as seeded", () => {
    expect(summarise([])).toEqual({
      total: 0,
      automatic: 0,
      gated: 0,
      expired: 0,
      timesUsed: 0,
    });
  });
});

describe("statusLabel", () => {
  it("puts expiry ahead of the class, because an expired answer is not sent", () => {
    expect(statusLabel(item({ autoAnswers: true, expired: true }))).toBe("Needs refreshing");
  });

  it("reads the server's verdict rather than re-deriving it from the class", () => {
    // A judgement answer the user explicitly switched ON: the class alone
    // would say "asks you first", the server says otherwise, and the server wins.
    expect(
      statusLabel(item({ sensitivity: "judgment", autoAnswerOptIn: true, autoAnswers: true })),
    ).toBe("Sent automatically");
    expect(statusLabel(item({ sensitivity: "sensitive", autoAnswers: false }))).toBe(
      "Asks you first",
    );
  });
});

describe("usageSummary", () => {
  it("says an unused answer is unused instead of inventing a count", () => {
    expect(usageSummary(item({ timesUsed: 0 }))).toBe("Not used yet");
  });

  it("counts distinct applications from the recorded audit", () => {
    const used = item({
      timesUsed: 3,
      usedOn: [
        {
          applicationId: "app_1",
          jobId: "j1",
          questionAsSeen: "Notice period?",
          matchConfidence: 1,
          matchMethod: "exact",
          usedAt: "2026-08-14T00:00:00Z",
        },
        {
          applicationId: "app_1",
          jobId: "j1",
          questionAsSeen: "Notice period?",
          matchConfidence: 1,
          matchMethod: "exact",
          usedAt: "2026-08-14T01:00:00Z",
        },
        {
          applicationId: "app_2",
          jobId: "j2",
          questionAsSeen: "How much notice must you give?",
          matchConfidence: 0.93,
          matchMethod: "concept",
          usedAt: "2026-08-14T02:00:00Z",
        },
      ],
    });
    expect(distinctApplications(used)).toBe(2);
    expect(usageSummary(used)).toBe("Used 3 times across 2 applications");
  });
});

describe("applyFilter", () => {
  const items = [
    item({ id: "auto", autoAnswers: true }),
    item({ id: "gated", autoAnswers: false }),
    item({ id: "stale", autoAnswers: false, expired: true }),
  ];

  it("splits the bank the way the user thinks about it", () => {
    expect(applyFilter(items, "all").map((i) => i.id)).toEqual(["auto", "gated", "stale"]);
    expect(applyFilter(items, "automatic").map((i) => i.id)).toEqual(["auto"]);
    expect(applyFilter(items, "gated").map((i) => i.id)).toEqual(["gated"]);
    expect(applyFilter(items, "expired").map((i) => i.id)).toEqual(["stale"]);
  });
});

describe("confidencePercent", () => {
  it("rounds the recorded match confidence for display", () => {
    expect(confidencePercent(0.934)).toBe(93);
    expect(confidencePercent(1)).toBe(100);
  });
});

describe("unansweredConcepts", () => {
  it("counts a concept answered on a real application as answered", () => {
    const questions = [{ concept: "work_rights" }, { concept: "notice_period" }];
    expect(unansweredConcepts(questions, ["notice_period"])).toEqual(["work_rights"]);
  });
});
