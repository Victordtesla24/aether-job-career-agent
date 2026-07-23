/**
 * Health check utilities for the Aether web app.
 * Kept intentionally tiny — this exists to anchor the test harness (P1-S00).
 */

interface HealthStatus {
  status: "ok";
  service: "web";
  version: string;
}

export function getHealth(version = "0.0.0"): HealthStatus {
  return { status: "ok", service: "web", version };
}
