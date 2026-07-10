/**
 * Networking CRM — pure business logic (AGT-NTWRK).
 *
 * No I/O, no framework imports: every function is deterministic and unit-tested.
 * The Next.js page (blocked on framework bootstrap — see shared-change request)
 * wires these to `/networking/summary` and the Add-Contact modal.
 */

import type {
  AddContactResult,
  Contact,
  CrmStats,
  PipelineColumn,
  PipelineStage,
  ResponseCounters,
  Warmth,
} from "./types";

/** Canonical stage order + display labels (single source of truth for the pipeline). */
export const STAGES: ReadonlyArray<{ stage: PipelineStage; label: string }> = [
  { stage: "new", label: "New" },
  { stage: "warm", label: "Warm" },
  { stage: "active", label: "Active" },
  { stage: "scheduled", label: "Scheduled" },
  { stage: "placed", label: "Placed" },
];

const STAGE_KEYS: ReadonlySet<PipelineStage> = new Set(STAGES.map((s) => s.stage));

/** Derive the two-letter monogram used on avatars (e.g. "Sarah L." -> "SL"). */
export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** True when there are no contacts across the whole pipeline -> render the empty state (nw18). */
export function isPipelineEmpty(columns: ReadonlyArray<PipelineColumn>): boolean {
  return totalContacts(columns) === 0;
}

/** Authoritative total = sum of stage badge counts (wireframe shows 14+10+12+7+5 = 48). */
export function totalContacts(columns: ReadonlyArray<PipelineColumn>): number {
  return columns.reduce((sum, c) => sum + c.count, 0);
}

function countForStage(columns: ReadonlyArray<PipelineColumn>, stage: PipelineStage): number {
  return columns.find((c) => c.stage === stage)?.count ?? 0;
}

/**
 * Whole-number response rate. Guards divide-by-zero (returns 0 when nobody has
 * been contacted) and clamps to [0, 100].
 */
export function computeResponseRate({ contacted, replied }: ResponseCounters): number {
  if (contacted <= 0) return 0;
  const clampedReplied = Math.max(0, Math.min(replied, contacted));
  return Math.round((clampedReplied / contacted) * 100);
}

/** Roll up the four stat cards (nw06) from the pipeline + response counters. */
export function computeStats(
  columns: ReadonlyArray<PipelineColumn>,
  counters: ResponseCounters,
): CrmStats {
  return {
    totalContacts: totalContacts(columns),
    activeThreads: countForStage(columns, "active"),
    referralsSecured: countForStage(columns, "placed"),
    responseRate: computeResponseRate(counters),
  };
}

/**
 * Build ordered pipeline columns from a flat contact list, preserving the
 * canonical stage order and label. `counts` lets the caller supply authoritative
 * badge totals (from the API) that may exceed the number of materialised sample
 * cards; when omitted, the count is the number of contacts in that stage.
 */
export function buildPipeline(
  contacts: ReadonlyArray<Contact>,
  counts?: Partial<Record<PipelineStage, number>>,
): PipelineColumn[] {
  return STAGES.map(({ stage, label }) => {
    const stageContacts = contacts.filter((c) => c.stage === stage);
    return {
      stage,
      label,
      count: counts?.[stage] ?? stageContacts.length,
      contacts: stageContacts,
    };
  });
}

/** Warmth -> filled/empty star flags for the 3-star indicator on each card. */
export function warmthStars(warmth: Warmth): boolean[] {
  return [0, 1, 2].map((i) => i < warmth);
}

function isValidStage(stage: string): stage is PipelineStage {
  return STAGE_KEYS.has(stage as PipelineStage);
}

/**
 * Validate + construct a contact from the Add-Contact modal inputs
 * (contact-name-input / contact-company-input / contact-role-input in prod).
 * New contacts always enter the pipeline at the "new" stage with zero warmth.
 */
export function addContact(
  input: { name: string; company: string; role: string; relationship?: Contact["relationship"] },
  idFactory: () => string,
): AddContactResult {
  const name = input.name.trim();
  const company = input.company.trim();
  const role = input.role.trim();

  const errors: Partial<Record<"name" | "company" | "role", string>> = {};
  if (!name) errors.name = "Name is required.";
  if (!company) errors.company = "Company is required.";
  if (!role) errors.role = "Role is required.";
  if (Object.keys(errors).length > 0) return { ok: false, errors };

  return {
    ok: true,
    contact: {
      id: idFactory(),
      name,
      initials: initialsFor(name),
      role,
      company,
      relationship: input.relationship ?? "recruiter",
      stage: "new",
      warmth: 0,
    },
  };
}

/**
 * Move a contact to a new stage, returning a new array (immutable update).
 * Unknown stage or unknown id is a no-op that returns the original reference.
 */
export function moveContact(
  contacts: ReadonlyArray<Contact>,
  contactId: string,
  toStage: string,
): Contact[] | ReadonlyArray<Contact> {
  if (!isValidStage(toStage)) return contacts;
  if (!contacts.some((c) => c.id === contactId)) return contacts;
  return contacts.map((c) => (c.id === contactId ? { ...c, stage: toStage } : c));
}
