/**
 * DecisionGuidance — shared "what this tells you / what to do next" affordance (R1.2).
 *
 * Rendered beneath a visualisation or metric panel. Copy must be honest and
 * deterministic: state only what the displayed figure establishes, and give a
 * concrete review action. No predictions, no fabricated interpretation.
 *
 * Mirrors the approved markup of the analytics-page guidance block so the
 * design system stays consistent (border-t divider, two-column on sm+).
 */
type DecisionGuidanceProps = {
  /** Honest statement of what the visible figure establishes. */
  tellsYou: string;
  /** Concrete next action the operator should take based on it. */
  next: string;
  /** Override for test targeting; defaults to the shared testid. */
  testId?: string;
  className?: string;
};

export function DecisionGuidance({
  tellsYou,
  next,
  testId = "decision-guidance",
  className,
}: DecisionGuidanceProps) {
  return (
    <div
      data-testid={testId}
      className={`mt-3 grid gap-2 border-t border-white/10 pt-3 text-[11px] leading-[1.45] text-aether-muted-dim sm:grid-cols-2${
        className ? ` ${className}` : ""
      }`}
    >
      <p>
        <span className="font-semibold text-aether-muted">What this tells you</span>{" "}
        {tellsYou}
      </p>
      <p>
        <span className="font-semibold text-aether-muted">What to do next</span>{" "}
        {next}
      </p>
    </div>
  );
}

export default DecisionGuidance;
