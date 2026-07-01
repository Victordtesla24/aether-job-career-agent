import { describe, it, expect } from "vitest";
import { authorizeCredentials } from "../../src/lib/auth/credentials";
import { authConfig, SESSION_MAX_AGE_SECONDS } from "../../src/lib/auth/options";

describe("authorizeCredentials (P1-S03)", () => {
  it("returns a user for a valid lookup", async () => {
    const user = await authorizeCredentials(
      { email: "vik@example.com", password: "hunter2-correct" },
      async (email) => ({
        id: "user_1",
        email,
        name: "Vik",
        passwordHash: "hunter2-correct",
      }),
      async (plain, hash) => plain === hash,
    );
    expect(user).not.toBeNull();
    expect(user?.id).toBe("user_1");
    expect(user?.email).toBe("vik@example.com");
    // The password hash must never leak into the returned user object.
    expect(user as unknown as Record<string, unknown>).not.toHaveProperty(
      "passwordHash",
    );
  });

  it("returns null when the user does not exist", async () => {
    const user = await authorizeCredentials(
      { email: "ghost@example.com", password: "whatever" },
      async () => null,
      async () => true,
    );
    expect(user).toBeNull();
  });

  it("returns null when the password does not match", async () => {
    const user = await authorizeCredentials(
      { email: "vik@example.com", password: "wrong" },
      async (email) => ({ id: "user_1", email, passwordHash: "right" }),
      async (plain, hash) => plain === hash,
    );
    expect(user).toBeNull();
  });

  it("returns null for malformed credentials", async () => {
    const noEmail = await authorizeCredentials(
      { email: "", password: "x" },
      async () => ({ id: "u", email: "x", passwordHash: "x" }),
      async () => true,
    );
    expect(noEmail).toBeNull();
  });
});

describe("authConfig (P1-S03)", () => {
  it("uses a stateless JWT session strategy", () => {
    expect(authConfig.session.strategy).toBe("jwt");
    expect(authConfig.session.maxAge).toBe(SESSION_MAX_AGE_SECONDS);
  });

  it("exposes a credentials provider", () => {
    const provider = authConfig.providers.find((p) => p.id === "credentials");
    expect(provider).toBeDefined();
    expect(provider?.type).toBe("credentials");
    expect(provider?.credentials).toHaveProperty("email");
    expect(provider?.credentials).toHaveProperty("password");
  });

  it("names the secret env var and a sign-in page", () => {
    expect(authConfig.secretEnvVar).toBe("NEXTAUTH_SECRET");
    expect(authConfig.pages.signIn).toBe("/login");
  });
});
