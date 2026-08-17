/**
 * AUD-AGENT-4 — how big this product is, said honestly.
 *
 * THE DEFECT THIS REPLACES. The agent catalog is a list of CARDS, not of
 * agents: one deterministic engine (`fitScorer`) is presented as three cards —
 * Match Scoring, ATS Optimization and Skill Gap — so the catalog's card total
 * has never been a count of agents. Both the Agents page subline and the Agent
 * Configuration header rendered that total as "22 agents", which counted one
 * engine three times and padded the product's headline number.
 *
 * THE RULE. Every count on screen is the SERVER's (`GET /agents/catalog` →
 * `counts.engines` / `counts.cards`, derived from the catalog itself), and it
 * is stated as an explicit DUAL DISCLOSURE — "N engines powering M cards" —
 * so neither number can be mistaken for the other. This mirrors the
 * conductor's "Run everything (N agents / M cards)" label
 * (`./conductor.ts`), which already reads its two numbers off the server's
 * plan; the two screens are now the same arithmetic over the same catalog and
 * cannot disagree.
 *
 * NO FALLBACK. A server that sends no honest basis (one predating this fix)
 * makes the UI state NO count at all. Substituting the padded card total would
 * be the exact fabrication this fix removes, so the absence is surfaced as an
 * absence.
 */
import type { Catalog } from "./api";

export type CatalogCounts = Catalog["counts"];

/** The two server-computed numbers, or `null` when the server sent neither. */
export function catalogScale(
  counts: CatalogCounts | null | undefined,
): { engines: number; cards: number } | null {
  if (!counts) return null;
  const { engines, cards } = counts;
  if (typeof engines !== "number" || typeof cards !== "number") return null;
  return { engines, cards };
}

/**
 * "20 engines powering 22 cards" — the dual disclosure, or `null`.
 *
 * Stated uniformly even when the two numbers agree: a single blended "N
 * agents" is precisely the claim that went wrong, and a reader who sees the
 * pair always knows which number is which.
 */
export function catalogScaleLabel(counts: CatalogCounts | null | undefined): string | null {
  const scale = catalogScale(counts);
  if (!scale) return null;
  const engines = `${scale.engines} engine${scale.engines === 1 ? "" : "s"}`;
  const cards = `${scale.cards} card${scale.cards === 1 ? "" : "s"}`;
  return `${engines} powering ${cards}`;
}

/**
 * The number of AGENTS — distinct engines, each counted once — or `null`.
 *
 * This is the only number a surface labelled "agents" may show.
 */
export function honestAgentCount(counts: CatalogCounts | null | undefined): number | null {
  return catalogScale(counts)?.engines ?? null;
}
