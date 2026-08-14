"use client";

/**
 * The primary application sidebar now lives in `components/shell/Rail.tsx`
 * (S-UI-REBUILD §1.2). This module stays as the stable import path so every
 * existing importer — `app/dashboard/layout.tsx` and
 * `components/__tests__/sidebar.test.tsx` — keeps working unmodified, which
 * Binding Constraint 1 requires.
 *
 * `Rail` preserves this component's entire behavioural contract verbatim:
 * the same `fetchAgents` 30s poll and `agentPulse()` CRITICAL-2 staleness
 * verdict, the same one-shot `fetchSubscription()`, the same `NAV_ITEMS`
 * order, the same `supportEmail` conditional (no dead mailto), and the same
 * `sidebar-plan-*` testids and copy.
 */
export { Rail as Sidebar } from "./shell/Rail";
