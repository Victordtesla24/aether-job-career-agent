"use client";

/** Route error boundary for the Answer Bank (C-03, QA-v2). */
import { RouteError } from "../../../components/route-error";

export default function AnswerBankError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError section="Answer Bank" error={error} reset={reset} />;
}
