/**
 * lib/api/auth.ts — register + login HTTP client (feat/auth-fe).
 *
 * RED first: lib/api/auth.ts does not exist yet. Exercises the honest
 * 409 (duplicate email) / 429 (rate limit, with Retry-After) handling the
 * FEATURE CONTRACT requires the /signup flow to surface, plus the 401 path
 * /login already relies on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthApiError, login, registerAccount } from "../../lib/api/auth";

function jsonResponse(body: unknown, status: number, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("registerAccount", () => {
  it("returns the created user on 201", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "u1", email: "new@example.com", createdAt: "2026-07-14T00:00:00" }, 201));
    vi.stubGlobal("fetch", fetchMock);

    const result = await registerAccount(
      { email: "new@example.com", password: "abcdefg1" },
      "http://api.test",
    );

    expect(result).toEqual({ id: "u1", email: "new@example.com", createdAt: "2026-07-14T00:00:00" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/auth/register",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("surfaces a 409 duplicate email honestly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "An account with this email already exists" }, 409)),
    );

    await expect(
      registerAccount({ email: "dup@example.com", password: "abcdefg1" }, "http://api.test"),
    ).rejects.toMatchObject({ status: 409, message: expect.stringMatching(/already exists/i) });
  });

  it("surfaces a 429 with the Retry-After seconds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: "Too many registration attempts for this email. Please wait and try again." },
          429,
          { "Retry-After": "3600" },
        ),
      ),
    );

    try {
      await registerAccount({ email: "spam@example.com", password: "abcdefg1" }, "http://api.test");
      expect.unreachable("registerAccount should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(AuthApiError);
      const authErr = err as AuthApiError;
      expect(authErr.status).toBe(429);
      expect(authErr.retryAfterSeconds).toBe(3600);
      expect(authErr.message).toMatch(/too many attempts/i);
    }
  });

  it("does not rate-limit a different email after one identifier is capped (client just forwards the server response)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "u2", email: "other@example.com", createdAt: "2026-07-14T00:00:00" }, 201));
    vi.stubGlobal("fetch", fetchMock);

    const result = await registerAccount(
      { email: "other@example.com", password: "abcdefg1" },
      "http://api.test",
    );
    expect(result.email).toBe("other@example.com");
  });
});

describe("login", () => {
  it("returns the token on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ access_token: "jwt-123", token_type: "bearer", userId: "u1", email: "a@example.com" }, 200),
      ),
    );

    const result = await login("a@example.com", "abcdefg1", "http://api.test");
    expect(result).toEqual({ accessToken: "jwt-123", userId: "u1", email: "a@example.com" });
  });

  it("surfaces invalid credentials as a constant-shape 401 message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Invalid email or password" }, 401)));

    await expect(login("a@example.com", "wrong", "http://api.test")).rejects.toMatchObject({
      status: 401,
      message: expect.stringMatching(/invalid email or password/i),
    });
  });

  it("surfaces a 429 lockout with Retry-After", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: "Too many failed login attempts for this account. Please wait and try again." },
          429,
          { "Retry-After": "120" },
        ),
      ),
    );

    try {
      await login("a@example.com", "wrong", "http://api.test");
      expect.unreachable("login should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(AuthApiError);
      expect((err as AuthApiError).status).toBe(429);
      expect((err as AuthApiError).retryAfterSeconds).toBe(120);
    }
  });

  it("accepts a bare username identifier (not just an email shape)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ access_token: "jwt-admin", token_type: "bearer", userId: "u0", email: "admin@aether.local" }, 200),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await login("admin", "admin123", "http://api.test");
    expect(result.accessToken).toBe("jwt-admin");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ email: "admin", password: "admin123" });
  });
});

describe("register 422 message hygiene (MV-signup-003)", () => {
  it("replaces the raw email_validator message with a clean, non-technical line", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: [
              {
                msg: "value is not a valid email address: The email address is too long (65 characters too many).",
                type: "value_error",
              },
            ],
          },
          422,
        ),
      ),
    );

    await expect(
      registerAccount({ email: "x".repeat(300) + "@ex.dev", password: "abcdefg1" }, "http://api.test"),
    ).rejects.toMatchObject({ status: 422, message: "Please enter a valid email address." });
  });

  it("strips the pydantic 'Value error,' wrapper from an honest policy message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: [{ msg: "Value error, password must be at most 72 bytes", type: "value_error" }] },
          422,
        ),
      ),
    );

    await expect(
      registerAccount({ email: "a@example.com", password: "z".repeat(80) }, "http://api.test"),
    ).rejects.toMatchObject({ status: 422, message: "password must be at most 72 bytes" });
  });
});
