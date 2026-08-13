"use client";

/**
 * Dashboard-wide route error boundary (C-03, QA-v2). Catches render errors in
 * any /dashboard/* segment that lacks its own error.tsx so a workspace crash
 * degrades to a recoverable card instead of a blank pane.
 */
import { RouteError } from "../../components/route-error";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError section="This page" error={error} reset={reset} />;
}
