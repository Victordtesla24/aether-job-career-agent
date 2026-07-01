/**
 * NextAuth.js configuration surface (P1-S03).
 *
 * This object is shaped to be handed straight to `NextAuth(authConfig)` when
 * Next.js is introduced in the dashboard shell (P1-S06). Until then it is a
 * fully-typed, unit-tested contract describing a Credentials provider backed by
 * the stateless JWT session strategy implemented in `./jwt`. Keeping it
 * framework-free lets us assert the auth contract without booting Next.js and
 * avoids pulling the `next`/`react` peer dependencies before the UI slice.
 *
 * See DECISIONS D-0006 for the rationale behind deferring the route-handler
 * wiring to P1-S06.
 */

export type SessionStrategy = "jwt" | "database";

export interface CredentialField {
  label: string;
  type: "text" | "email" | "password";
}

export interface AuthProviderConfig {
  id: string;
  name: string;
  type: "credentials" | "oauth";
  credentials?: Record<string, CredentialField>;
}

export interface AuthConfig {
  providers: AuthProviderConfig[];
  session: { strategy: SessionStrategy; maxAge: number };
  pages: { signIn: string };
  /** Name of the env var holding the signing secret (never the value). */
  secretEnvVar: string;
}

/** 30 days, in seconds — mirrors the JWT default expiry. */
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

export const authConfig: AuthConfig = {
  providers: [
    {
      id: "credentials",
      name: "Email and Password",
      type: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
    },
  ],
  session: { strategy: "jwt", maxAge: SESSION_MAX_AGE_SECONDS },
  pages: { signIn: "/login" },
  secretEnvVar: "NEXTAUTH_SECRET",
};
