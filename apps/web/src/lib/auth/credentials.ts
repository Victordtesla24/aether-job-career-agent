/**
 * Credentials authorization (P1-S03).
 *
 * `authorizeCredentials` is the callback NextAuth's Credentials provider will
 * invoke on sign-in. It is written as a pure function with its data-access and
 * password-verification dependencies injected, so it is fully unit-testable
 * without a live database and can be wired to `UserRepository` + a real hash
 * comparison (bcrypt/argon2) in P1-S06.
 *
 * SECURITY: the returned user object NEVER carries the password hash.
 */
export interface Credentials {
  email: string;
  password: string;
}

/** A user record as loaded from persistence, including the stored hash. */
export interface StoredUser {
  id: string;
  email: string;
  name?: string;
  passwordHash: string;
}

/** The safe, hash-free user returned to the session layer. */
export interface AuthorizedUser {
  id: string;
  email: string;
  name?: string;
}

export type UserLookup = (email: string) => Promise<StoredUser | null>;
export type PasswordVerifier = (
  plain: string,
  hash: string,
) => Promise<boolean>;

export async function authorizeCredentials(
  credentials: Credentials,
  lookupUser: UserLookup,
  verifyPassword: PasswordVerifier,
): Promise<AuthorizedUser | null> {
  const email = credentials.email?.trim().toLowerCase();
  const password = credentials.password;

  if (!email || !password) {
    return null;
  }

  const user = await lookupUser(email);
  if (!user) {
    return null;
  }

  const ok = await verifyPassword(password, user.passwordHash);
  if (!ok) {
    return null;
  }

  // Strip the hash — never let it escape the auth boundary.
  return { id: user.id, email: user.email, name: user.name };
}
