"use client";

/** Route error boundary for Resume Studio (C-03, QA-v2). */
import { RouteError } from "../../../components/route-error";

export default function ResumeError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError section="Resume Studio" error={error} reset={reset} />;
}
