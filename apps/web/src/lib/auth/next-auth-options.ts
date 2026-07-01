import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import {
  authorizeCredentials,
  type StoredUser,
  SESSION_MAX_AGE_SECONDS,
} from "./index";

/**
 * Live NextAuth options (P1-S06) — this file wires the framework-free auth
 * contract from P1-S03 into the actual `next-auth` runtime, fulfilling
 * DECISIONS D-0006.
 *
 * The credentials provider delegates to `authorizeCredentials` with its data
 * dependencies injected. Until the user store is seeded (Phase 2, backed by
 * UserRepository + a real password hash comparison), `lookupUser` returns null
 * and `verifyPassword` returns false, so no credentials can succeed yet — but
 * the sign-in route, JWT session strategy, and callbacks are fully functional
 * and testable.
 */

// Placeholder dependencies until the persistence layer is wired in Phase 2.
async function lookupUser(_email: string): Promise<StoredUser | null> {
  return null;
}

async function verifyPassword(_plain: string, _hash: string): Promise<boolean> {
  return false;
}

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt", maxAge: SESSION_MAX_AGE_SECONDS },
  pages: { signIn: "/login" },
  secret: process.env.NEXTAUTH_SECRET,
  providers: [
    CredentialsProvider({
      id: "credentials",
      name: "Email and Password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null;
        }
        const user = await authorizeCredentials(
          { email: credentials.email, password: credentials.password },
          lookupUser,
          verifyPassword,
        );
        return user ? { id: user.id, email: user.email, name: user.name } : null;
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.id) {
        (session.user as { id?: string }).id = token.id as string;
      }
      return session;
    },
  },
};
