"use client";

/**
 * Root-level route error boundary (O-5, S-FIX slice C). Catches render
 * errors anywhere outside a segment that has its own error.tsx — in
 * practice, the public marketing/auth routes (/, /login, /signup, /pricing,
 * /terms, /privacy-policy, /forgot-password), since every /dashboard/* route
 * is already covered by dashboard/error.tsx. Before this, such an error fell
 * through to Next.js's stock, unbranded 500 page. See app-error-screen.tsx.
 */
import { AppErrorScreen } from "../components/app-error-screen";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <AppErrorScreen error={error} reset={reset} />;
}
