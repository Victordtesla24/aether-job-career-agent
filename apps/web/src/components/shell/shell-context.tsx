"use client";

/**
 * One shell, one `GET /billing/subscription`.
 *
 * The rail (desktop) and the mobile nav sheet both show the plan/quota block
 * (S-UI-REBUILD §1.2 / §1.5). Fetching it in each would add a request that
 * does not exist on `main`, and Binding Constraint 1 is checked by comparing
 * the request list — method, path, order, body — against `main`. So the
 * shell fetches it ONCE and shares it here.
 *
 * A `null` context value means "no provider" — the component is being
 * rendered standalone (as `components/__tests__/sidebar.test.tsx` does), and
 * it falls back to fetching for itself exactly as it always has. That
 * fallback is what keeps the existing sidebar tests green unmodified.
 */
import { createContext, useContext } from "react";

import type { SubscriptionState } from "../../lib/api/billing";

/** Boxed so `undefined` can keep meaning "still loading" inside the box. */
export interface ShellSubscription {
  value: SubscriptionState | null | undefined;
}

export const ShellSubscriptionContext = createContext<ShellSubscription | null>(null);

export function useShellSubscription(): ShellSubscription | null {
  return useContext(ShellSubscriptionContext);
}
