/**
 * RFMT-2 — the Download button asks for the CLEAN file; only the Studio
 * preview asks for the tinted one.
 *
 * The tailoring highlight (peach behind a spliced bullet, coral behind a
 * branded one) is a Résumé Studio affordance: it shows the subscriber which
 * lines were reworded. It is not part of their résumé. Live production shipped
 * it on nine bullets across all three pages of a tailored download, so a
 * recruiter opening that file saw an annotated draft.
 *
 * The server render is clean by default and marks up only for `?diff=true`
 * (apps/api/app/routers/resumes.py). These tests pin the CLIENT half of that
 * contract: `downloadResume` must never send the flag, and the preview call
 * must always send it.
 */
import { describe, expect, it, vi } from "vitest";

import { downloadResume, previewTailoredResume } from "../../lib/api/resumes";

const OPTIONS = { token: "test-token", baseUrl: "https://api.test" } as const;

function pdfResponse(): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "Content-Type": "application/pdf" }),
    blob: async () => new Blob(["%PDF-fake"], { type: "application/pdf" }),
    text: async () => "",
  } as unknown as Response;
}

function mockFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async () => pdfResponse());
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("RFMT-2 — download is clean, preview is tinted", () => {
  it("downloadResume never asks for the diff-tinted variant", async () => {
    const fetchMock = mockFetch();
    await downloadResume("r1", OPTIONS);
    const [url] = fetchMock.mock.calls[0]! as unknown as [string];
    expect(String(url)).toContain("/resumes/r1/download");
    expect(String(url)).not.toContain("diff");
  });

  it("previewTailoredResume asks for the diff-tinted variant", async () => {
    const fetchMock = mockFetch();
    const preview = await previewTailoredResume("r1", OPTIONS);
    const [url] = fetchMock.mock.calls[0]! as unknown as [string];
    expect(String(url)).toContain("/resumes/r1/download?diff=true");
    expect(preview.url).toBeTruthy();
    expect(typeof preview.revoke).toBe("function");
    preview.revoke();
  });

  it("a failed preview throws instead of returning an empty document", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        headers: new Headers({ "Content-Type": "application/json" }),
        text: async () => '{"detail":"Resume not found"}',
      }) as unknown as Response),
    );
    await expect(previewTailoredResume("missing", OPTIONS)).rejects.toThrow(
      /Resume not found/,
    );
  });
});
