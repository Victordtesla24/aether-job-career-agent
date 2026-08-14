/**
 * /dashboard/answer-bank — server wrapper.
 *
 * The Answer Bank (ADR-SUB-AUTON-1 Pillar 1) is entirely per-user, live data,
 * so the page is a thin dynamic shell over the interactive client; nothing
 * about it can be prerendered.
 */
import AnswerBankClient from "./answer-bank-client";

export const dynamic = "force-dynamic";

export default function AnswerBankPage() {
  return <AnswerBankClient />;
}
