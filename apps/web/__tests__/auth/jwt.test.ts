import { describe, it, expect } from "vitest";
import { signSessionToken, verifySessionToken } from "../../src/lib/auth/jwt";

const SECRET = "test-secret-please-change-in-prod-000000000000";

describe("JWT session tokens (P1-S03)", () => {
  it("signs and verifies a round-trip token", async () => {
    const token = await signSessionToken(
      { sub: "user_1", email: "vik@example.com", name: "Vik" },
      SECRET,
    );
    expect(typeof token).toBe("string");
    expect(token.split(".")).toHaveLength(3); // header.payload.signature

    const claims = await verifySessionToken(token, SECRET);
    expect(claims.sub).toBe("user_1");
    expect(claims.email).toBe("vik@example.com");
    expect(claims.name).toBe("Vik");
    expect(claims.exp).toBeGreaterThan(claims.iat);
  });

  it("rejects a token verified with the wrong secret", async () => {
    const token = await signSessionToken({ sub: "u", email: "a@b.co" }, SECRET);
    await expect(
      verifySessionToken(token, "a-completely-different-secret-value-1234567"),
    ).rejects.toThrow();
  });

  it("rejects a tampered token", async () => {
    const token = await signSessionToken({ sub: "u", email: "a@b.co" }, SECRET);
    const tampered = token.slice(0, -2) + (token.endsWith("aa") ? "bb" : "aa");
    await expect(verifySessionToken(tampered, SECRET)).rejects.toThrow();
  });

  it("rejects an already-expired token", async () => {
    const token = await signSessionToken({ sub: "u", email: "a@b.co" }, SECRET, {
      expiresIn: "-1s",
    });
    await expect(verifySessionToken(token, SECRET)).rejects.toThrow();
  });

  it("throws when signing with an empty secret", async () => {
    await expect(
      signSessionToken({ sub: "u", email: "a@b.co" }, ""),
    ).rejects.toThrow();
  });
});
