"use client";

/** Route error boundary for Applications (C-03, QA-v2). */
import { RouteError } from "../../../components/route-error";

export default function ApplicationsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError section="Applications" error={error} reset={reset} />;
}
