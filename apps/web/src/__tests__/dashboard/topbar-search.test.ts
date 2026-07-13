/**
 * Topbar global search (wireframe topbar contract: "Search jobs,
 * applications, agents…") — filtering semantics over the live index.
 */
import { describe, expect, it } from "vitest";

import { filterSearchHits, type SearchHit } from "../../components/topbar";

const INDEX: SearchHit[] = [
  {
    kind: "job",
    id: "j1",
    label: "Head of Projects / Programme Manager",
    sublabel: "Arete Executive",
    href: "/dashboard/jobs",
  },
  {
    kind: "job",
    id: "j2",
    label: "Senior Business Analyst",
    sublabel: "Peoplebank",
    href: "/dashboard/jobs",
  },
  {
    kind: "application",
    id: "a1",
    label: "Senior Business Analyst",
    sublabel: "Peoplebank",
    href: "/dashboard/applications",
  },
  { kind: "agent", id: "scout", label: "scout", sublabel: "agent", href: "/dashboard/agents" },
];

describe("filterSearchHits", () => {
  it("returns nothing for queries shorter than 2 characters", () => {
    expect(filterSearchHits(INDEX, "")).toEqual([]);
    expect(filterSearchHits(INDEX, "s")).toEqual([]);
    expect(filterSearchHits(INDEX, " s ")).toEqual([]);
  });

  it("matches case-insensitively across label and sublabel", () => {
    expect(filterSearchHits(INDEX, "arete").map((h) => h.id)).toEqual(["j1"]);
    expect(filterSearchHits(INDEX, "BUSINESS ANALYST").map((h) => h.id)).toEqual(["j2", "a1"]);
  });

  it("finds agents by name", () => {
    expect(filterSearchHits(INDEX, "scout").map((h) => h.kind)).toEqual(["agent"]);
  });

  it("caps results at the limit", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      kind: "job" as const,
      id: `j${i}`,
      label: `Delivery Lead ${i}`,
      sublabel: "Acme",
      href: "/dashboard/jobs",
    }));
    expect(filterSearchHits(many, "delivery")).toHaveLength(8);
    expect(filterSearchHits(many, "delivery", 3)).toHaveLength(3);
  });

  it("returns nothing when nothing matches", () => {
    expect(filterSearchHits(INDEX, "kubernetes")).toEqual([]);
  });
});
