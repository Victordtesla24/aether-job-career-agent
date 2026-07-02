/**
 * JWT primitives for Aether's stateless session strategy (P1-S03).
 *
 * These wrap `jose` (the same library NextAuth.js uses internally) so the
 * session-token format is identical to what NextAuth will issue once it is
 * wired into the Next.js app shell (P1-S06). Keeping them here means the
 * security-critical signing/verification path is unit-testable without booting
 * a framework.
 *
 * SECURITY: the signing secret is passed in explicitly and is never logged.
 */
import { SignJWT, jwtVerify } from "jose";

/** HMAC-SHA256 — the default NextAuth JWT algorithm for symmetric secrets. */
const ALG = "HS256";

/** Default session lifetime, mirrored by {@link "./options".SESSION_MAX_AGE_SECONDS}. */
const DEFAULT_EXPIRY = "30d";

export interface SessionTokenPayload {
  /** Stable user id (JWT `sub` claim). */
  sub: string;
  /** User email. */
  email: string;
  /** Optional display name. */
  name?: string;
}

export interface VerifiedSessionClaims extends SessionTokenPayload {
  /** Issued-at (epoch seconds). */
  iat: number;
  /** Expiry (epoch seconds). */
  exp: number;
}

function encodeSecret(secret: string): Uint8Array {
  if (!secret) {
    throw new Error("JWT secret must be a non-empty string");
  }
  return new TextEncoder().encode(secret);
}

/**
 * Sign a session token. `options.expiresIn` accepts any `jose` time string
 * (e.g. "30d", "2h", "-1s" for an already-expired token in tests).
 */
export async function signSessionToken(
  payload: SessionTokenPayload,
  secret: string,
  options: { expiresIn?: string } = {},
): Promise<string> {
  const key = encodeSecret(secret);
  return new SignJWT({ email: payload.email, name: payload.name })
    .setProtectedHeader({ alg: ALG })
    .setSubject(payload.sub)
    .setIssuedAt()
    .setExpirationTime(options.expiresIn ?? DEFAULT_EXPIRY)
    .sign(key);
}

/**
 * Verify a session token and return its claims. Throws if the signature is
 * invalid, the token is tampered with, or it has expired.
 */
export async function verifySessionToken(
  token: string,
  secret: string,
): Promise<VerifiedSessionClaims> {
  const key = encodeSecret(secret);
  const { payload } = await jwtVerify(token, key, { algorithms: [ALG] });

  if (typeof payload.sub !== "string" || typeof payload.email !== "string") {
    throw new Error("Invalid session token: missing required claims");
  }

  return {
    sub: payload.sub,
    email: payload.email,
    name: typeof payload.name === "string" ? payload.name : undefined,
    iat: payload.iat as number,
    exp: payload.exp as number,
  };
}
