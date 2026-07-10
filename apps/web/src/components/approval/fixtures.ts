/**
 * Sample approval request mirroring design/screens/approval-modal.html verbatim.
 * Intended for Storybook/tests/local preview only — never as a live data source
 * (surfacing a fixture in production would be a fixture-as-live gap).
 */

import type { ApprovalRequest } from "./types.js";

export const SAMPLE_APPROVAL_REQUEST: ApprovalRequest = {
  taskId: "task_demo_ml_canva",
  agent: {
    name: "Tailoring Agent",
    action: "wants to submit an application",
  },
  subject: {
    badge: "CV",
    title: "Senior ML Engineer",
    subtitle: "Canva · Sydney · via LinkedIn",
  },
  confidence: 91,
  whyApproval:
    "This role sits above your salary target and the cover letter references a project outside your verified portfolio. Your approval gate for high-stakes applications is on.",
  reasoning: [
    { severity: "positive", text: "7 of 8 required skills matched from your resume" },
    { severity: "positive", text: "ATS score of 96 after tailoring" },
    {
      severity: "warning",
      text: "One claim (35% latency gain) is inferred, not verified",
    },
  ],
  preview: {
    label: "Generated cover letter",
    body: "Dear Canva Hiring Team, I'm excited to apply for the Senior ML Engineer role. Over six years I've built recommendation systems serving 40M+ users and fine-tuned transformer models that cut inference latency by 35%…",
  },
};
