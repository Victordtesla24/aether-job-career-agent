import { describe, it, expect } from "vitest";
import { getHealth } from "../src/health";

describe("web health harness (P1-S00)", () => {
  // GREEN: harness proven; assert a true statement.
  it("sanity: arithmetic", () => {
    expect(1 + 1).toBe(2);
  });

  it("getHealth returns an ok status for the web service", () => {
    const health = getHealth("1.2.3");
    expect(health.status).toBe("ok");
    expect(health.service).toBe("web");
    expect(health.version).toBe("1.2.3");
  });
});
