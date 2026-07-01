import NextAuth from "next-auth";
import { authOptions } from "@/lib/auth/next-auth-options";

/**
 * NextAuth route handler for the App Router (P1-S06). This is the concrete
 * wiring deferred in DECISIONS D-0006 — a single handler serves both GET and
 * POST for all /api/auth/* endpoints.
 */
const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
