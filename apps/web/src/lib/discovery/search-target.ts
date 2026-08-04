/**
 * What a discovery run should search for — derived from the SIGNED-IN user.
 *
 * F-02 (PROD-UAT-2026-08-03). Two screens used to post a hardcoded persona to
 * `POST /agents/scout/run` for every customer alike:
 *
 *   dashboard/jobs/page.tsx   "delivery lead, product owner, program manager,
 *                              business analyst" / "Australia"
 *   dashboard/agents/page.tsx "software engineer" / "Australia"
 *
 * A new customer with a Senior Data Scientist résumé and an empty profile
 * therefore had 1,621 project-management postings written into their account.
 *
 * This module is the single place either screen resolves that question, and it
 * is deliberately built around one rule: **it owns no query of its own.** There
 * is no constant here to fall back to, so "the user told us nothing" can only
 * ever resolve to `needs-input` — a question for the user — never to a search
 * on somebody else's behalf. A future edit that reintroduces a default has to
 * add the literal to this file, where `search-target.test.ts` is watching for
 * exactly that.
 *
 * Where the real signal comes from:
 *   - `targetRole` / `location` — the user's own profile columns, read through
 *     GET /auth/me (`lib/api/admin.ts:fetchMe`), which is the same source the
 *     topbar chip and Settings > Profile already render.
 *   - the RÉSUMÉ is deliberately NOT parsed here. The backend already scores
 *     and filters every discovered posting against the user's real résumé
 *     inside `ScoutAgent.run` (apps/api/app/agents/scout_agent.py — it loads
 *     `require_user_resume_text` and runs the ATS engine over each result), so
 *     re-deriving a role from résumé prose in the browser would be a second,
 *     weaker, client-side guess at something the server already knows.
 *   - the backend also broadens a recognised role into its whole family
 *     (`app/services/discovery/query_builder.build_scout_query`). The query
 *     sent from here is the user's own wording; broadening stays server-side
 *     where the matching regex lives.
 */

/** The profile fields GET /auth/me exposes that describe what this user wants. */
export interface DiscoveryProfile {
  targetRole: string;
  location: string;
}

/** A role/location the user typed into the "what should we search for?" prompt. */
export interface EnteredTarget {
  role: string;
  location: string;
}

export type MissingTargetField = "role" | "location";

export type SearchTarget =
  | {
      status: "ready";
      /** Exactly what the user asked for — never widened or substituted here. */
      query: string;
      location: string;
      /** Whether this came from their saved profile or this session's prompt. */
      source: "profile" | "entered";
    }
  | {
      status: "needs-input";
      /** Which halves are missing, so the UI can name them honestly. */
      missing: MissingTargetField[];
      /** Whatever IS known, offered back as a prefill — not as a licence to run. */
      role: string;
      location: string;
    };

/**
 * Resolve the search target, preferring anything the user just typed.
 *
 * `profile` may be `null`/`undefined` — that is the "we could not read it"
 * case, and it resolves to `needs-input` like any other absence. Failing to
 * load a profile must never silently become a search.
 */
export function deriveSearchTarget(
  profile: DiscoveryProfile | null | undefined,
  entered?: EnteredTarget | null,
): SearchTarget {
  const enteredRole = (entered?.role ?? "").trim();
  const enteredLocation = (entered?.location ?? "").trim();
  if (enteredRole && enteredLocation) {
    return { status: "ready", query: enteredRole, location: enteredLocation, source: "entered" };
  }

  const profileRole = (profile?.targetRole ?? "").trim();
  const profileLocation = (profile?.location ?? "").trim();
  const missing: MissingTargetField[] = [];
  if (!profileRole) missing.push("role");
  if (!profileLocation) missing.push("location");
  if (missing.length === 0) {
    return { status: "ready", query: profileRole, location: profileLocation, source: "profile" };
  }
  return {
    status: "needs-input",
    missing,
    role: enteredRole || profileRole,
    location: enteredLocation || profileLocation,
  };
}

/** Name the missing halves the way the user would ("target role and location"). */
export function missingTargetLabel(missing: MissingTargetField[]): string {
  const names = missing.map((m) => (m === "role" ? "target role" : "location"));
  return names.length === 2 ? `${names[0]} and ${names[1]}` : (names[0] ?? "target role");
}
