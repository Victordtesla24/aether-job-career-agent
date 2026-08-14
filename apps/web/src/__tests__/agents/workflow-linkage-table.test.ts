/**
 * U-STORY-3a — the CROSS-WORKFLOW LINKAGE TABLE's integrity.
 *
 * The user mandate this slice answers: "story extraction and resume tailoring /
 * cover letter agents are on separate workflows on the UI — users must be able
 * to KNOW THE LINKAGES VISUALLY to know what happened to their job search and
 * application and when."
 *
 * The honesty risk it creates is obvious: a linkage table is a place where a
 * plausible-sounding wire can be typed in that no code actually implements.
 * These tests exist so that cannot happen quietly.
 *
 * WHAT IS PINNED (each one a way the table could lie):
 *   1. every linkage carries provenance — never zero hops;
 *   2. every hop's `evidence` is a real `path/to/file.py:line` citation, not
 *      prose;
 *   3. every hop EXISTS VERBATIM in the checked-in AGENT-GRAPH snapshot — the
 *      structural graph derived by reading the API, hop for hop, with the same
 *      from/to/kind/evidence/status. This is the anti-fabrication test: a wire
 *      nobody read out of the code cannot be added to the table;
 *   4. every hop is `status: "live"` — a wire the discovery marked `absent`
 *      (e.g. learningFeedback → quality_policy) may never be drawn;
 *   5. the hop chain is contiguous and actually starts/ends at the two agents
 *      the linkage claims to join;
 *   6. both endpoints are real catalog agents;
 *   7. `drawableLinkages` — the filter the renderer runs — DROPS anything that
 *      breaks 1/4/5, so the guard is structural at runtime and not only here.
 *
 * The snapshot is a byte copy of the discovery artefact
 * `uat/reports/evidence/market-perf/u-story/AGENT-GRAPH.json` (81 nodes / 105
 * code-evidenced edges), checked in beside this slice's evidence so the claim
 * stays auditable and this test stays hermetic.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  LINKAGE_SOURCE,
  WORKFLOW_LINKAGES,
  drawableLinkages,
  type WorkflowLinkage,
} from "../../components/agents/workflow-linkage";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");
const SNAPSHOT = path.join(REPO_ROOT, LINKAGE_SOURCE.snapshotPath);

interface GraphEdge {
  from: string;
  to: string;
  kind: string;
  mechanism: string;
  evidence: string;
  status: string;
}
interface GraphNode {
  id: string;
  type: string;
  name: string;
}

/** Loaded EAGERLY and without a try/catch: a missing snapshot must fail the
 *  suite loudly, never degrade into a weaker shape-only check. */
const graph = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

const graphEdges = new Map<string, GraphEdge[]>();
graph.edges.forEach((e) => {
  const key = `${e.from}|${e.to}`;
  graphEdges.set(key, [...(graphEdges.get(key) ?? []), e]);
});
const agentNodes = new Set(graph.nodes.filter((n) => n.type === "agent").map((n) => n.id));

/** A citation is `apps/<dir>/<file>.<ext>:<line>` — a line number, not prose. */
const CITATION = /(?:^|\s)apps\/[\w./-]+\.(?:py|ts|tsx|prisma):\d+/;

describe("U-STORY-3a linkage table — provenance or it does not exist", () => {
  it("ships at least the story-bank linkages the mandate is about", () => {
    const ids = WORKFLOW_LINKAGES.map((l) => l.id);
    expect(ids).toContain("storyExtraction->resumeTailoring");
    expect(ids).toContain("storyExtraction->coverLetter");
    // The loop closing back the other way is the other half of the aha.
    expect(ids).toContain("resumeTailoring->storyExtraction");
  });

  it("gives every linkage a unique id, two distinct endpoints and a meaning", () => {
    const ids = new Set<string>();
    const pairs = new Set<string>();
    WORKFLOW_LINKAGES.forEach((link) => {
      expect(ids.has(link.id), `duplicate id ${link.id}`).toBe(false);
      ids.add(link.id);
      const pair = `${link.from}->${link.to}`;
      expect(pairs.has(pair), `duplicate linkage ${pair}`).toBe(false);
      pairs.add(pair);
      expect(link.id).toBe(pair);
      expect(link.from).not.toBe(link.to);
      // Plain language, not a slug: this is what the user reads.
      expect(link.meaning.length).toBeGreaterThan(20);
      expect(link.meaning.endsWith(".")).toBe(true);
      expect(link.label.length).toBeGreaterThan(3);
    });
  });

  it("never ships a linkage without provenance", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      expect(link.provenance.length, `${link.id} has no provenance`).toBeGreaterThan(0);
    });
  });

  it("cites a real file:line on every hop", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      link.provenance.forEach((hop) => {
        expect(hop.evidence, `${link.id}: ${hop.evidence}`).toMatch(CITATION);
        expect(hop.mechanism.length).toBeGreaterThan(0);
      });
    });
  });

  it("keeps every hop chain contiguous between the two agents it claims to join", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      const hops = link.provenance;
      expect(hops[0].from).toBe(`agent.${link.from}`);
      expect(hops[hops.length - 1].to).toBe(`agent.${link.to}`);
      for (let i = 0; i < hops.length - 1; i += 1) {
        expect(hops[i].to, `${link.id} hop ${i} does not join hop ${i + 1}`).toBe(hops[i + 1].from);
      }
    });
  });

  it("places both endpoints in the agent catalog the graph was derived from", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      expect(agentNodes.has(`agent.${link.from}`), `${link.from} is not a catalog agent`).toBe(true);
      expect(agentNodes.has(`agent.${link.to}`), `${link.to} is not a catalog agent`).toBe(true);
    });
  });

  it("draws no hop the AGENT-GRAPH snapshot does not itself record", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      link.provenance.forEach((hop) => {
        const candidates = graphEdges.get(`${hop.from}|${hop.to}`) ?? [];
        const match = candidates.find(
          (e) =>
            e.kind === hop.kind &&
            e.evidence === hop.evidence &&
            e.mechanism === hop.mechanism &&
            e.status === hop.status,
        );
        expect(
          match,
          `${link.id}: ${hop.from} -> ${hop.to} is not in ${LINKAGE_SOURCE.snapshotPath}`,
        ).toBeTruthy();
      });
    });
  });

  it("refuses any hop the discovery marked absent or partial", () => {
    WORKFLOW_LINKAGES.forEach((link) => {
      link.provenance.forEach((hop) => {
        expect(hop.status, `${link.id} draws a non-live hop`).toBe("live");
      });
    });
  });

  it("passes its own drawable filter unchanged", () => {
    expect(drawableLinkages(WORKFLOW_LINKAGES)).toHaveLength(WORKFLOW_LINKAGES.length);
  });
});

describe("drawableLinkages — the runtime guard, not just the test suite", () => {
  const honest = WORKFLOW_LINKAGES.find((l) => l.id === "storyExtraction->resumeTailoring")!;

  function mutate(patch: Partial<WorkflowLinkage>): WorkflowLinkage {
    return { ...honest, ...patch, id: "fabricated->edge" } as WorkflowLinkage;
  }

  it("drops an edge with no provenance at all", () => {
    expect(drawableLinkages([mutate({ provenance: [] })])).toHaveLength(0);
  });

  it("drops an edge whose citation is prose rather than file:line", () => {
    const bad = mutate({
      provenance: [{ ...honest.provenance[0], evidence: "everyone knows this is wired" }],
    });
    expect(drawableLinkages([bad])).toHaveLength(0);
  });

  it("drops an edge that hangs on a hop the discovery found absent", () => {
    const bad = mutate({
      provenance: honest.provenance.map((h, i) =>
        i === 0 ? { ...h, status: "absent" as const } : h,
      ),
    });
    expect(drawableLinkages([bad])).toHaveLength(0);
  });

  it("drops an edge whose chain does not reach the agent it claims to feed", () => {
    const bad: WorkflowLinkage = {
      ...honest,
      id: "storyExtraction->submission",
      to: "submission",
    };
    expect(drawableLinkages([bad])).toHaveLength(0);
  });

  it("drops an edge whose hops do not join up", () => {
    const bad = mutate({
      from: "storyExtraction",
      to: "resumeTailoring",
      provenance: [honest.provenance[0], honest.provenance[2]],
    });
    expect(drawableLinkages([bad])).toHaveLength(0);
  });
});
