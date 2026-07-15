import { describe, expect, it } from "vitest";

import { ApiError } from "../../lib/api/client";
import { parseCoverLetterRejection } from "../../components/cover-letters/rejection";

function fabricationError(): ApiError {
  const detail = "Cover letter rejected by fabrication guard: ['Kubernetes', 'Series B']";
  return new ApiError(
    `POST /agents/cover-letter/run failed (422): ${JSON.stringify({ detail })}`,
    422,
  );
}

function refineFabricationError(): ApiError {
  const detail = "Revision blocked by fabrication guard: ['Kubernetes']";
  return new ApiError(
    `POST /cover-letters/abc-1/refine failed (422): ${JSON.stringify({ detail })}`,
    422,
  );
}

function structuralError(): ApiError {
  const detail =
    'Cover letter rejected — §10.2 format contract not met: [\'the closing paragraph must include a specific call-to-action (invite an interview or conversation)\', \'the generic opener "I am writing to express my interest" is forbidden\']';
  return new ApiError(
    `POST /agents/cover-letter/run failed (422): ${JSON.stringify({ detail })}`,
    422,
  );
}

describe("parseCoverLetterRejection (GAP-E4)", () => {
  it("maps a fabrication-guard 422 to a panel model listing the flagged tokens", () => {
    const model = parseCoverLetterRejection(fabricationError());
    expect(model).not.toBeNull();
    expect(model?.guard).toBe("fabrication");
    expect(model?.items).toEqual(["Kubernetes", "Series B"]);
    expect(model?.title.toLowerCase()).toContain("fabrication");
    expect(model?.remediation.length).toBeGreaterThan(0);
  });

  it("maps the refine endpoint's fabrication-guard 422 the same way", () => {
    const model = parseCoverLetterRejection(refineFabricationError());
    expect(model).not.toBeNull();
    expect(model?.guard).toBe("fabrication");
    expect(model?.items).toEqual(["Kubernetes"]);
  });

  it("maps a structural-contract 422 to a panel model naming the missing element", () => {
    const model = parseCoverLetterRejection(structuralError());
    expect(model).not.toBeNull();
    expect(model?.guard).toBe("structural");
    expect(model?.items).toHaveLength(2);
    expect(model?.items[0]).toContain("call-to-action");
    expect(model?.items[1]).toContain('generic opener "I am writing to express my interest"');
  });

  it("returns null for a non-422 error so callers fall back to the generic alert", () => {
    const notFound = new ApiError("GET /cover-letters/x failed (404): Cover letter not found", 404);
    expect(parseCoverLetterRejection(notFound)).toBeNull();

    const serverErr = new ApiError(
      "POST /agents/cover-letter/run failed (503): LLM backend unavailable",
      503,
    );
    expect(parseCoverLetterRejection(serverErr)).toBeNull();

    expect(parseCoverLetterRejection(new Error("network down"))).toBeNull();
    expect(parseCoverLetterRejection(null)).toBeNull();
  });

  it("returns null for a 422 whose detail doesn't match a known guard shape", () => {
    const unknown422 = new ApiError(
      `POST /cover-letters/abc/refine failed (422): ${JSON.stringify({ detail: "Validation error: instructions too long" })}`,
      422,
    );
    expect(parseCoverLetterRejection(unknown422)).toBeNull();
  });
});
