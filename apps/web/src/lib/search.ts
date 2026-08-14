/**
 * The shell's search index — MOVED VERBATIM from `components/topbar.tsx`
 * (S-UI-REBUILD §1.6 wiring law).
 *
 * The command palette and the old top-bar search box are the same search:
 * the same three API calls (`/jobs?`, `/applications`, `fetchAgents()`), the
 * same lazy-on-first-open trigger, the same ">= 2 characters" rule and the
 * same `limit 8`. Nothing about the wiring changed in the move — only where
 * the functions live — and `components/topbar.tsx` re-exports both so
 * `src/__tests__/dashboard/topbar-search.test.ts` keeps importing them from
 * the path it always has.
 */
import { fetchAgents } from "./api/agents";
import { apiRequest } from "./api/client";

export interface SearchHit {
  kind: "job" | "application" | "agent";
  id: string;
  label: string;
  sublabel: string;
  href: string;
}

/** Case-insensitive substring match over label + sublabel; requires ≥2 chars. */
export function filterSearchHits(hits: SearchHit[], query: string, limit = 8): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  return hits
    .filter((h) => `${h.label} ${h.sublabel}`.toLowerCase().includes(q))
    .slice(0, limit);
}

/** Build the search index from the user's live jobs, applications and agents. */
export async function loadSearchIndex(): Promise<SearchHit[]> {
  const [jobs, applications, agents] = await Promise.all([
    apiRequest<Array<{ id: string; title: string; company: string }>>("/jobs?"),
    apiRequest<Array<{ id: string; jobTitle?: string | null; company?: string | null }>>(
      "/applications",
    ),
    fetchAgents(),
  ]);
  return [
    ...jobs.map<SearchHit>((j) => ({
      kind: "job",
      id: j.id,
      label: j.title,
      sublabel: j.company,
      href: "/dashboard/jobs",
    })),
    ...applications.map<SearchHit>((a) => ({
      kind: "application",
      id: a.id,
      label: a.jobTitle ?? "Application",
      sublabel: a.company ?? "",
      href: "/dashboard/applications",
    })),
    ...agents.map<SearchHit>((a) => ({
      kind: "agent",
      id: a.name,
      label: a.name,
      sublabel: "agent",
      href: "/dashboard/agents",
    })),
  ];
}
