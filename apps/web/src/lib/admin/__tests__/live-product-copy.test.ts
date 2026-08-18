import { describe, expect, it } from "vitest";

import {
  containsRetiredHost,
  liveProductCopy,
} from "../live-product-copy";

const LIVE = "https://aether.srv1356245.hstgr.cloud";

describe("liveProductCopy", () => {
  it("rewrites the retired Abacus origin and keeps the path", () => {
    const src = "See https://5cb5f0620.abacusai.cloud/signup for the product.";
    expect(liveProductCopy(src, LIVE)).toBe(
      "See https://aether.srv1356245.hstgr.cloud/signup for the product.",
    );
    expect(containsRetiredHost(src)).toBe(true);
    expect(containsRetiredHost(liveProductCopy(src, LIVE))).toBe(false);
  });

  it("leaves historical copy unchanged when no live origin is known", () => {
    const src = "https://5cb5f0620.abacusai.cloud/pricing";
    expect(liveProductCopy(src, "")).toBe(src);
  });
});
