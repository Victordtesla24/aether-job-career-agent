/**
 * GAP-P4-041 / GAP-P4-042 — Email Center safety helpers.
 *
 * The inbox API returns `intelligence: null` for every thread until a real
 * AI-scoring backend is wired, and `POST /emails/send` returns a 409 when no
 * email provider is connected. These tests lock in the honest, crash-free
 * handling of both cases.
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "../../lib/api/client";
import {
  emailIntelligenceView,
  emailSendErrorMessage,
  type EmailIntelligence,
} from "../../lib/api/workspaces";

describe("emailIntelligenceView (GAP-P4-041 null-guard)", () => {
  it("returns an honest 'not available' state when intelligence is null", () => {
    // This is exactly what GET /workspaces/emails/inbox returns today.
    expect(() => emailIntelligenceView({ intelligence: null })).not.toThrow();
    expect(emailIntelligenceView({ intelligence: null })).toEqual({ available: false });
  });

  it("exposes the score/breakdown/summary when intelligence is present", () => {
    const intel: EmailIntelligence = {
      score: 82,
      breakdown: [
        { label: "Urgency", value: 70 },
        { label: "Fit", value: 90 },
      ],
      summary: "Strong recruiter interest — respond within 24h.",
    };
    expect(emailIntelligenceView({ intelligence: intel })).toEqual({
      available: true,
      score: 82,
      breakdown: intel.breakdown,
      summary: intel.summary,
    });
  });
});

describe("emailSendErrorMessage (GAP-P4-042 honest failure surface)", () => {
  it("lifts the human message out of a 409 no-provider ApiError", () => {
    const err = new ApiError(
      'POST /workspaces/emails/send failed (409): {"detail":{"error":"no_email_provider_connected",' +
        '"message":"No email provider connected — connect an account in Settings to send. No email has been sent."}}',
      409,
    );
    expect(emailSendErrorMessage(err)).toBe(
      "No email provider connected — connect an account in Settings to send. No email has been sent.",
    );
  });

  it("handles a plain string detail", () => {
    const err = new ApiError('POST /x failed (409): {"detail":"nope"}', 409);
    expect(emailSendErrorMessage(err)).toBe("nope");
  });

  it("falls back to the raw error text when there is no JSON detail", () => {
    const err = new ApiError("Network request failed", 0);
    expect(emailSendErrorMessage(err)).toBe("Network request failed");
    expect(emailSendErrorMessage("boom")).toBe("Send failed");
  });
});
