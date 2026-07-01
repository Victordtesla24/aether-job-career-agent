import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { SESSION_MAX_AGE_SECONDS } from "./index";
import { loginWithCredentials } from "../api/auth";

/**
 * Live NextAuth options (P1-S06, wired to real auth in P2-S01) — this file
 * connects the sign-in route to the FastAPI backend, fulfilling DECISIONS
 * D-0006.
 *
 * The credentials provider delegates verification to the backend's
 * `/auth/login` endpoint (see {@link loginWithCredentials}). The backend owns
 * the bcrypt hashes and never returns them, so the hash never crosses the auth
 * boundary. The pure `authorizeCredentials` primitive (P1-S03) remains the
 * unit-tested contract for the underlying decision, while runtime credential
 * checks are performed server-side where the hashes live.
 */
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
        const user = await loginWithCredentials(
          credentials.email,
          credentials.password,
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
