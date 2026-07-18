/**
 * deriveChip — header avatar initials + chip name (MV-signup-004).
 * RED first: deriveChip is not exported from components/topbar.tsx yet, and
 * the current logic garbles a name containing markup/emoji tokens ('M日' /
 * 'MV 日.').
 */
import { describe, expect, it } from "vitest";

import { deriveChip } from "../../components/topbar";

describe("deriveChip (MV-signup-004 initials robustness)", () => {
  it("derives sane initials from a plain two-part name", () => {
    const chip = deriveChip("Vikram Sarkar", "Technical Program Manager");
    expect(chip.initials).toBe("VS");
    expect(chip.chipName).toBe("Vikram S.");
  });

  it("degrades gracefully for a name with markup and emoji tokens", () => {
    // Previously rendered 'M日' avatar / 'MV 日.' label.
    const chip = deriveChip("MV Signup <script>alert(1)</script> 日本語🎉", "");
    expect(chip.initials).toBe("MS");
    expect(chip.chipName).toBe("MV S.");
  });

  it("uses the first two letters for a single-token name", () => {
    expect(deriveChip("Madonna", "").initials).toBe("MA");
  });

  it("keeps apostrophe/hyphen names intact", () => {
    expect(deriveChip("O'Brien", "").initials).toBe("OB");
    expect(deriveChip("Jean-Paul Sartre", "").initials).toBe("JS");
  });

  it("supports non-Latin letter names", () => {
    const chip = deriveChip("田中 太郎", "");
    expect(chip.initials).toBe("田太");
    expect(chip.chipName).toBe("田中 太.");
  });

  it("falls back to AE when the name has no usable letters", () => {
    expect(deriveChip("🎉 <b>", "").initials).toBe("AE");
  });
});
