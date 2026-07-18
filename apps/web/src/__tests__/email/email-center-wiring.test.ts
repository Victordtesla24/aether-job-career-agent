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
  emailScoreBadge,
  linkedInSearchUrl,
  parseEmailDraft,
  parseEmailInsights,
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
