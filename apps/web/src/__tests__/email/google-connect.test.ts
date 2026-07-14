/**
 * Gmail connect callback helper (Email Agent). Locks in the honest mapping of
 * the OAuth callback query params (…/dashboard/email?gmail_connected=1|0&error=)
 * to a success/error banner, and that a normal visit (no flag) shows nothing.
 */
import { describe, expect, it } from "vitest";

import { gmailConnectResultFromParams } from "../../lib/api/google";

describe("gmailConnectResultFromParams", () => {
  it("returns null when the callback flag is absent (normal visit)", () => {
    expect(gmailConnectResultFromParams(new URLSearchParams(""))).toBeNull();
  });

  it("maps gmail_connected=1 to a success result", () => {
    expect(gmailConnectResultFromParams(new URLSearchParams("gmail_connected=1"))).toEqual({
      kind: "success",
    });
  });

  it("maps gmail_connected=0 with the server-supplied error message", () => {
    expect(
      gmailConnectResultFromParams(
        new URLSearchParams("gmail_connected=0&error=access_denied"),
      ),
    ).toEqual({ kind: "error", message: "access_denied" });
  });

  it("falls back to a default message when the error param is missing", () => {
    expect(gmailConnectResultFromParams(new URLSearchParams("gmail_connected=0"))).toEqual({
      kind: "error",
      message: "Google sign-in was cancelled or failed.",
    });
  });
});
