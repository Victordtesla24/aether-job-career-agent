/**
 * Small env-var loader shared by the e2e auth flow (GAP-P4-051 / C-15).
 *
 * Playwright specs run outside Next's own env loading, so LOGIN_EMAIL /
 * LOGIN_PASSWORD (used to drive the real /login form) are read from the
 * process environment first and fall back to parsing the repo-root `.env`
 * directly — the same file/keys `uat/api_sweep.py` and
 * `apps/api/scripts/seed_demo.py` already use. Never hardcodes a credential;
 * throws if neither source has the key so a missing/misconfigured env fails
 * loudly instead of silently running against empty credentials.
 */
import fs from "node:fs";
import path from "node:path";

// apps/web has "type": "module" (no __dirname); Playwright always runs from
// apps/web (per playwright.config.ts / the repo's e2e script), so resolve
// the repo-root .env from process.cwd() instead.
const REPO_ROOT_ENV = path.resolve(process.cwd(), "../../.env");

let cachedEnvFile: Record<string, string> | null = null;

function readEnvFile(): Record<string, string> {
  if (cachedEnvFile) return cachedEnvFile;
  cachedEnvFile = {};
  if (fs.existsSync(REPO_ROOT_ENV)) {
    for (const rawLine of fs.readFileSync(REPO_ROOT_ENV, "utf-8").split("\n")) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const idx = line.indexOf("=");
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
      cachedEnvFile[key] = value;
    }
  }
  return cachedEnvFile;
}

/** Required env var: process env, else repo-root `.env`, else throws. */
export function requireEnv(key: string): string {
  const fromProcess = process.env[key];
  if (fromProcess) return fromProcess;
  const fromFile = readEnvFile()[key];
  if (fromFile) return fromFile;
  throw new Error(
    `${key} is required for the e2e login flow. Export it or set it in the repo .env ` +
      `(see .env.example) before running the Playwright suite.`,
  );
}
