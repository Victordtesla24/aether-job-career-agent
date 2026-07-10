/**
 * Networking CRM — wireframe demo fixtures (AGT-NTWRK).
 *
 * These mirror the exact sample data drawn in `design/screens/networking.html`.
 * They exist to (a) drive Storybook-style previews and (b) let the logic tests
 * assert that derived stats reproduce the numbers shown in the wireframe.
 *
 * NOT a live data source. The production page loads real data from
 * `/networking/summary`; wiring these fixtures into the shipped page in place of
 * that fetch would be a "fixture-as-live" gap per the swarm protocol.
 */

import type { CommEvent, Contact, OutreachItem, ResponseCounters } from "./types";

/** Authoritative per-stage badge counts from the wireframe (sum = 48). */
export const DEMO_STAGE_COUNTS = {
  new: 14,
  warm: 10,
  active: 12,
  scheduled: 7,
  placed: 5,
} as const;

/** The five sample contact cards (nw08–nw12), one per pipeline column. */
export const DEMO_CONTACTS: Contact[] = [
  { id: "nw08", name: "Sarah L.", initials: "SL", role: "Recruiter", company: "Atlassian", relationship: "recruiter", stage: "new", warmth: 2 },
  { id: "nw09", name: "Mark K.", initials: "MK", role: "Eng Mgr", company: "Canva", relationship: "hiring-manager", stage: "warm", warmth: 3 },
  { id: "nw10", name: "Priya R.", initials: "PR", role: "TA Lead", company: "ANZ", relationship: "recruiter", stage: "active", warmth: 3 },
  { id: "nw11", name: "James T.", initials: "JT", role: "Recruiter", company: "Stripe", relationship: "recruiter", stage: "scheduled", warmth: 0 },
  { id: "nw12", name: "Dan N.", initials: "DN", role: "Referral", company: "NAB", relationship: "referral", stage: "placed", warmth: 0 },
];

/** Response counters chosen to reproduce the wireframe's 41% response-rate stat. */
export const DEMO_RESPONSE_COUNTERS: ResponseCounters = { contacted: 49, replied: 20 };

export const DEMO_OUTREACH: OutreachItem[] = [
  { id: "out1", title: "Follow-up: Mark K.", status: "draft", summary: "Agent drafted a warm follow-up referencing Canva scaling." },
  { id: "out2", title: "Intro: Sarah L.", status: "queued", summary: "Sends tomorrow 9:00 AEST." },
];

export const DEMO_COMM_LOG: CommEvent[] = [
  { id: "log1", kind: "reply", text: "Priya R. replied", timeAgo: "2h ago · “Let’s set up a call”" },
  { id: "log2", kind: "sent", text: "Sent intro to James T.", timeAgo: "Yesterday" },
  { id: "log3", kind: "handshake", text: "Dan N. confirmed referral", timeAgo: "3 days ago" },
];
