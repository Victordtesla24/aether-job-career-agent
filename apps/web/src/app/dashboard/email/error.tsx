"use client";

/** Route error boundary for Email Center (C-03, QA-v2). */
import { RouteError } from "../../../components/route-error";

export default function EmailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError section="Email Center" error={error} reset={reset} />;
}
