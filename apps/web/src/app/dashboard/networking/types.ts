/**
 * Networking CRM — domain types (AGT-NTWRK).
 *
 * Derived element-by-element from the wireframe `design/screens/networking.html`
 * and reconciled with the deployed production contract at `/networking/summary`
 * (component test-ids: networking-crm, networking-stats, contact-pipeline,
 * contact-card, outreach-queue, communication-log, networking-empty-state).
 *
 * This is the framework-agnostic logic layer the React/Next page consumes; it
 * carries no rendering concerns so it stays testable under the existing
 * vitest/tsc/eslint harness (see health.ts for the same convention).
 */

/** Ordered pipeline stages, matching the five wireframe columns (nw07). */
export type PipelineStage =
  | "new"
  | "warm"
  | "active"
  | "scheduled"
  | "placed";

/** How a contact relates to the search — drives the card subtitle (e.g. "Recruiter · Atlassian"). */
export type RelationshipKind = "recruiter" | "referral" | "hiring-manager" | "peer";

/** 0–3 filled stars, matching the wireframe warmth indicator on each contact card. */
export type Warmth = 0 | 1 | 2 | 3;

export interface Contact {
  id: string;
  name: string;
  /** Avatar monogram shown in the card (e.g. "SL" for Sarah L.). */
  initials: string;
  role: string;
  company: string;
  relationship: RelationshipKind;
  stage: PipelineStage;
  warmth: Warmth;
}

export interface PipelineColumn {
  stage: PipelineStage;
  label: string;
  /** Authoritative count for the stage (wireframe badge), independent of how many
   *  sample cards are materialised into `contacts`. */
  count: number;
  contacts: Contact[];
}

export interface CrmStats {
  totalContacts: number;
  activeThreads: number;
  referralsSecured: number;
  /** Whole-number percentage 0–100. */
  responseRate: number;
}

/** Outreach draft lifecycle (nw14). */
export type OutreachStatus = "draft" | "queued" | "sent";

export interface OutreachItem {
  id: string;
  title: string;
  status: OutreachStatus;
  summary: string;
}

/** Communication-log event kinds (nw16). */
export type CommEventKind = "reply" | "sent" | "handshake";

export interface CommEvent {
  id: string;
  kind: CommEventKind;
  text: string;
  timeAgo: string;
}

/** Raw counters feeding the response-rate metric. */
export interface ResponseCounters {
  contacted: number;
  replied: number;
}

/** Result of validating the Add-Contact form (name/company/role inputs, nw05). */
export type AddContactResult =
  | { ok: true; contact: Contact }
  | { ok: false; errors: Partial<Record<"name" | "company" | "role", string>> };
