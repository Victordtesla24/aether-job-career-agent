/**
 * GAP-P4-063 — the story-extractor trigger ("Draft missing stories" /
 * "Import from Resume") must give an immediate pending state backed by the
 * real in-flight run, and resolve back to idle only once that real request
 * settles — never a fake spinner-timer.
 */
import { describe, expect, it } from "vitest";

import { extractorTriggerState } from "../../components/stories/logic";

describe("extractorTriggerState", () => {
  it("shows the idle label and stays enabled before the run starts", () => {
    const s = extractorTriggerState(false, "Draft missing stories", "Drafting from resume…");
    expect(s).toEqual({ label: "Draft missing stories", disabled: false });
  });

  it("switches to the active label and disables immediately once the run is in flight", () => {
    const s = extractorTriggerState(true, "Draft missing stories", "Drafting from resume…");
    expect(s).toEqual({ label: "Drafting from resume…", disabled: true });
  });

  it("supports the empty-state trigger's distinct copy", () => {
    const idle = extractorTriggerState(false, "Import from Resume", "Importing…");
    const active = extractorTriggerState(true, "Import from Resume", "Importing…");
    expect(idle.label).toBe("Import from Resume");
    expect(active.label).toBe("Importing…");
    expect(active.disabled).toBe(true);
  });
});
