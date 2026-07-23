/**
 * Test helpers for the auth layer (P1-S03).
 *
 * These are intentionally shipped in `src` (not under `__tests__`) so that both
 * unit tests and, later, Playwright E2E setup can mint valid session tokens
 * against the same signing path the app uses in production.
 */
import { signSessionToken, type SessionTokenPayload } from "./jwt";

/** Mint a signed session token for tests. */
export async function createTestToken(
  secret: string,
  overrides: Partial<SessionTokenPayload> = {},
): Promise<string> {
  const payload: SessionTokenPayload = {
    sub: overrides.sub ?? "test-user",
    email: overrides.email ?? "test@aether.dev",
    name: overrides.name ?? "Test User",
  };
  return signSessionToken(payload, secret);
}
