/**
 * Pure, unit-testable helpers for the Story Bank screen (no React/DOM).
 *
 * GAP-P4-063: the story-extractor trigger ("Draft missing stories" in
 * StoryAside, and the empty state's "Import from Resume") must give
 * immediate pending feedback backed by the real in-flight run — never a
 * fake spinner-timer — and must resolve back to idle once the real
 * POST /agents/story-extractor/run request actually completes (success or
 * failure). Both call sites shared duplicated inline ternaries for this;
 * centralizing it here also gives the pending state itself unit coverage,
 * since the component tree isn't otherwise exercised by the node vitest
 * environment.
 */
export interface ExtractorTriggerState {
  label: string;
  disabled: boolean;
}

/**
 * Immediate pending-state affordance for a story-extractor trigger button.
 * `drafting` must reflect a real in-flight `runStoryExtractor()` call (set
 * true before the request starts, reset in a `finally` after it settles) —
 * never a `setTimeout`-based approximation.
 */
export function extractorTriggerState(
  drafting: boolean,
  idleLabel: string,
  activeLabel: string,
): ExtractorTriggerState {
  return { label: drafting ? activeLabel : idleLabel, disabled: drafting };
}
