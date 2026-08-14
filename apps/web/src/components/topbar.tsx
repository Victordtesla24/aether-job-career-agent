"use client";

/**
 * The dashboard top bar now lives in `components/shell/CommandBar.tsx`
 * (S-UI-REBUILD §1.3), and its search index in `lib/search.ts` (§1.6 wiring
 * law). This module stays as the stable import path so every existing
 * importer keeps working unmodified, which Binding Constraint 1 requires:
 *
 *   - `app/dashboard/layout.tsx` (now via `shell/AppShell`)
 *   - `components/__tests__/topbar.test.tsx`
 *   - `components/__tests__/topbar-notification-panel.test.tsx`
 *   - `components/__tests__/wg-admin-indicator-006.test.tsx`
 *   - `__tests__/dashboard/topbar-search.test.ts` (`filterSearchHits`, `SearchHit`)
 *   - `__tests__/dashboard/topbar-chip.test.ts` (`deriveChip`)
 *   - `__tests__/dashboard/topbar-approval-badge-honesty.test.ts`
 *     (`actionableApprovalCount`)
 *
 * `CommandBar` preserves the whole behavioural contract: the same fetches on
 * the same intervals, the same CRITICAL-4 approval filtering, the same
 * notification-panel portal/backdrop/focus contract, the same testids, and
 * the same MV-mobile-dashboard-001 `min-h-16` + `truncate` geometry.
 */
export { CommandBar as Topbar, actionableApprovalCount, deriveChip } from "./shell/CommandBar";
export { filterSearchHits, loadSearchIndex } from "../lib/search";
export type { SearchHit } from "../lib/search";
