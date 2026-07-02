import { redirect } from "next/navigation";

/**
 * The root route currently forwards straight to the dashboard. Authentication
 * gating is wired via NextAuth (see src/app/api/auth/[...nextauth]/route.ts) and
 * will be enforced with middleware in a later slice.
 */
export default function HomePage() {
  redirect("/dashboard");
}
