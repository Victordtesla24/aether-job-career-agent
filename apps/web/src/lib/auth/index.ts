/**
 * Aether authentication module (P1-S03).
 *
 * Public surface: JWT session tokens, session resolution, the `requireAuth`
 * guard, the credentials authorizer, and the NextAuth-shaped config.
 */
export {
  signSessionToken,
  verifySessionToken,
  type SessionTokenPayload,
  type VerifiedSessionClaims,
} from "./jwt";

export {
  getSessionFromToken,
  SESSION_COOKIE_NAME,
  type AetherSession,
  type AetherSessionUser,
} from "./session";

export {
  requireAuth,
  extractBearerToken,
  type AuthResult,
  type AuthFailureReason,
  type RequestLike,
} from "./require-auth";

export {
  authorizeCredentials,
  type Credentials,
  type StoredUser,
  type AuthorizedUser,
  type UserLookup,
  type PasswordVerifier,
} from "./credentials";

export {
  authConfig,
  SESSION_MAX_AGE_SECONDS,
  type AuthConfig,
  type AuthProviderConfig,
  type SessionStrategy,
  type CredentialField,
} from "./options";

export { createTestToken, createTestSession } from "./test-helpers";
