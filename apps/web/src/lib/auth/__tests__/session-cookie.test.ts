// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  persistSessionToken,
  persistSessionTokenFromStorage,
  SESSION_COOKIE_NAME,
} from "../session-cookie";

afterEach(() => {
  window.localStorage.clear();
  document.cookie = `${SESSION_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Lax`;
});

describe("persistSessionToken", () => {
  it("mirrors the JWT into localStorage and a same-origin cookie", () => {
    persistSessionToken("jwt.token.value");
    expect(window.localStorage.getItem(SESSION_COOKIE_NAME)).toBe("jwt.token.value");
    expect(document.cookie).toContain(`${SESSION_COOKIE_NAME}=jwt.token.value`);
  });

  it("rehydrates the cookie from an existing localStorage session", () => {
    window.localStorage.setItem(SESSION_COOKIE_NAME, "stored.jwt");
    persistSessionTokenFromStorage();
    expect(document.cookie).toContain(`${SESSION_COOKIE_NAME}=stored.jwt`);
  });
});
