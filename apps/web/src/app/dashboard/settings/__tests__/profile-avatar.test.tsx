// @vitest-environment jsdom
/**
 * Settings profile photo helpers + ProfileAvatar control.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AVATAR_CHANGE_LABEL,
  AVATAR_HELP_TEXT,
  MAX_AVATAR_BYTES,
  validateAvatarFile,
} from "../../../../components/settings/profile-avatar";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("validateAvatarFile", () => {
  it("accepts a small PNG by extension", () => {
    const file = new File([new Uint8Array([1, 2, 3])], "me.png", { type: "image/png" });
    expect(validateAvatarFile(file)).toBeNull();
  });

  it("accepts JPEG by extension when type is empty", () => {
    const file = new File([new Uint8Array([1])], "me.jpeg", { type: "" });
    expect(validateAvatarFile(file)).toBeNull();
  });

  it("rejects oversized files", () => {
    const file = new File([new Uint8Array(MAX_AVATAR_BYTES + 1)], "big.png", {
      type: "image/png",
    });
    expect(validateAvatarFile(file)).toMatch(/2MB/i);
  });

  it("rejects GIF / SVG / PDF", () => {
    for (const [name, type] of [
      ["x.gif", "image/gif"],
      ["x.svg", "image/svg+xml"],
      ["x.pdf", "application/pdf"],
    ] as const) {
      const file = new File([new Uint8Array([1])], name, { type });
      expect(validateAvatarFile(file)).toMatch(/PNG or JPG/);
    }
  });
});

vi.mock("../../../../lib/api/client", () => ({
  apiBaseUrl: () => "http://api.test",
  getToken: async () => "tok",
}));

// eslint-disable-next-line import/first
import { ProfileAvatar } from "../../../../components/settings/ProfileAvatar";

const BASE_SETTINGS = {
  profile: {
    fullName: "Jamie Rivera",
    email: "jamie@example.com",
    targetRole: "Staff Engineer",
    location: "Sydney, AU",
    hasAvatar: false,
    avatarRevision: null as string | null,
  },
  resume: { activeFile: null, uploadedAt: null, versions: 0, originalStored: false },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};

describe("ProfileAvatar", () => {
  it("shows Change avatar, help text, and initials when no photo", () => {
    render(
      <ProfileAvatar
        initials="JR"
        fullName="Jamie Rivera"
        hasAvatar={false}
        avatarRevision={null}
        onChanged={() => undefined}
      />,
    );
    expect(screen.getByTestId("settings-avatar-change").textContent).toBe(AVATAR_CHANGE_LABEL);
    expect(screen.getByText(AVATAR_HELP_TEXT)).toBeTruthy();
    expect(screen.getByTestId("settings-avatar-initials").textContent).toBe("JR");
    expect(screen.queryByTestId("settings-avatar-remove")).toBeNull();
    expect(screen.getByTestId("settings-avatar-input")).toBeTruthy();
  });

  it("uploads a file and surfaces the returned settings payload", async () => {
    const onChanged = vi.fn();
    const updated = {
      ...BASE_SETTINGS,
      profile: {
        ...BASE_SETTINGS.profile,
        hasAvatar: true,
        avatarRevision: "a".repeat(64),
      },
    };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return {
          ok: true,
          json: async () => updated,
          text: async (): Promise<string> => "",
        };
      }
      // GET avatar after onChanged would re-render with hasAvatar — parent
      // owns that; this mount stays hasAvatar=false until parent updates.
      return { ok: false, status: 404, text: async (): Promise<string> => "", blob: async () => new Blob() };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ProfileAvatar
        initials="JR"
        fullName="Jamie Rivera"
        hasAvatar={false}
        avatarRevision={null}
        onChanged={onChanged}
      />,
    );

    const input = screen.getByTestId("settings-avatar-input") as HTMLInputElement;
    const file = new File([new Uint8Array([137, 80, 78, 71])], "me.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(updated));
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/workspaces/settings/avatar",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls DELETE when Remove photo is clicked", async () => {
    const onChanged = vi.fn();
    const cleared = {
      ...BASE_SETTINGS,
      profile: { ...BASE_SETTINGS.profile, hasAvatar: false, avatarRevision: null },
    };
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        return { ok: true, json: async () => cleared, text: async () => "" };
      }
      // Initial GET for the existing photo
      return {
        ok: true,
        blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    // jsdom may lack createObjectURL — polyfill without @ts-expect-error
    // (TypeScript's DOM lib already types these; unused directives fail tsc).
    const urlApi = URL as typeof URL & {
      createObjectURL?: (obj: Blob) => string;
      revokeObjectURL?: (url: string) => void;
    };
    if (typeof urlApi.createObjectURL !== "function") {
      urlApi.createObjectURL = () => "blob:test";
    }
    if (typeof urlApi.revokeObjectURL !== "function") {
      urlApi.revokeObjectURL = () => undefined;
    }

    render(
      <ProfileAvatar
        initials="JR"
        fullName="Jamie Rivera"
        hasAvatar
        avatarRevision={"b".repeat(64)}
        onChanged={onChanged}
      />,
    );

    await waitFor(() => screen.getByTestId("settings-avatar-remove"));
    fireEvent.click(screen.getByTestId("settings-avatar-remove"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(cleared));
  });

  it("shows a bounded client-side error for a GIF without calling the API", async () => {
    const onChanged = vi.fn();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ProfileAvatar
        initials="JR"
        fullName="Jamie Rivera"
        hasAvatar={false}
        avatarRevision={null}
        onChanged={onChanged}
      />,
    );

    const input = screen.getByTestId("settings-avatar-input");
    const file = new File([new Uint8Array([1])], "x.gif", { type: "image/gif" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => screen.getByTestId("settings-avatar-error"));
    expect(screen.getByTestId("settings-avatar-error").textContent).toMatch(/PNG or JPG/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });
});
