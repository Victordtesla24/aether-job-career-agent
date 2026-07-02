import { describe, it, expect } from "vitest";
import { requireAuth, extractBearerToken } from "../../src/lib/auth/require-auth";
import { SESSION_COOKIE_NAME } from "../../src/lib/auth/session";
import { createTestToken } from "../../src/lib/auth/test-helpers";

const SECRET = "test-secret-please-change-in-prod-000000000000";

function makeRequest(opts: {
  authorization?: string;
  cookie?: string;
}) {
  return {
    headers: {
      get(name: string): string | null {
        if (name.toLowerCase() === "authorization") {
          return opts.authorization ?? null;
        }
        return null;
      },
    },
    cookies: {
      get(name: string) {
        if (name === SESSION_COOKIE_NAME && opts.cookie) {
          return { value: opts.cookie };
        }
        return undefined;
      },
    },
  };
}

describe("extractBearerToken (P1-S03)", () => {
  it("pulls the token out of an Authorization header", () => {
    expect(extractBearerToken("Bearer abc.def.ghi")).toBe("abc.def.ghi");
    expect(extractBearerToken("bearer abc.def.ghi")).toBe("abc.def.ghi");
  });

  it("returns null for missing or malformed headers", () => {
    expect(extractBearerToken(null)).toBeNull();
    expect(extractBearerToken("Basic xyz")).toBeNull();
    expect(extractBearerToken("")).toBeNull();
  });
});

describe("requireAuth guard (P1-S03)", () => {
  it("rejects a request with no credentials", async () => {
    const result = await requireAuth(makeRequest({}), SECRET);
    expect(result.authenticated).toBe(false);
    if (!result.authenticated) {
      expect(result.reason).toBe("no_token");
    }
  });

  it("accepts a valid Bearer token and returns the session", async () => {
    const token = await createTestToken(SECRET, { sub: "user_42", email: "z@y.co" });
    const result = await requireAuth(
      makeRequest({ authorization: `Bearer ${token}` }),
      SECRET,
    );
    expect(result.authenticated).toBe(true);
    if (result.authenticated) {
      expect(result.session.user.id).toBe("user_42");
      expect(result.session.user.email).toBe("z@y.co");
      expect(typeof result.session.expires).toBe("string");
    }
  });

  it("accepts a valid session cookie", async () => {
    const token = await createTestToken(SECRET, { sub: "user_7", email: "c@d.co" });
    const result = await requireAuth(makeRequest({ cookie: token }), SECRET);
    expect(result.authenticated).toBe(true);
    if (result.authenticated) {
      expect(result.session.user.id).toBe("user_7");
    }
  });

  it("rejects an invalid token", async () => {
    const result = await requireAuth(
      makeRequest({ authorization: "Bearer not.a.jwt" }),
      SECRET,
    );
    expect(result.authenticated).toBe(false);
    if (!result.authenticated) {
      expect(result.reason).toBe("invalid_token");
    }
  });
});
