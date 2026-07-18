// @vitest-environment jsdom
/**
 * clearClientSession — user-initiated logout teardown (MV-login-003).
 * RED first: lib/auth/logout.ts does not exist yet.
 */
import { afterEach, describe, expect, it } from "vitest";

import { clearClientSession } from "../logout";

afterEach(() => {
  window.localStorage.clear();
});

describe("clearClientSession", () => {
  it("removes the aether_token from localStorage", () => {
    window.localStorage.setItem("aether_token", "jwt-123");
    clearClientSession();
    expect(window.localStorage.getItem("aether_token")).toBeNull();
  });

  it("clears an aether_token cookie", () => {
    document.cookie = "aether_token=jwt-123; path=/";
    clearClientSession();
    expect(document.cookie).not.toContain("jwt-123");
  });
});
