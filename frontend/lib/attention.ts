/**
 * One derivation of "what matters", shared by every surface.
 *
 * The canvas, the panel, the dossier and the briefing must never disagree
 * about which nodes are hot — so none of them computes it. They all read this.
 *
 * A node needs the user when it is in tension, when it is an unexplored gap,
 * or when it echoes another project. A node recedes when it is verified and
 * uncontested: the map should read as a heatmap of where thinking is unfinished.
 */

import type { GraphLink, GraphNode } from "./types";

export interface NodeBadges {
  tension: boolean;
  echo: boolean;
  pending: boolean;
  verified: boolean;
  gap: boolean;
  /** 2 = demands attention, 1 = live, 0 = settled. Drives size, glow, labels. */
  heat: 0 | 1 | 2;
}

export type AttentionMap = Record<string, NodeBadges>;

function linkEnd(end: string | GraphNode): string {
  return typeof end === "string" ? end : end.id;
}

export function buildAttention(
  nodes: GraphNode[],
  links: GraphLink[],
): AttentionMap {
  const inTension = new Set<string>();
  for (const l of links) {
    if (l.relation !== "contradicts") continue;
    inTension.add(linkEnd(l.source));
    inTension.add(linkEnd(l.target));
  }

  const map: AttentionMap = {};
  for (const n of nodes) {
    const tension = inTension.has(n.id);
    const echo = (n.echoes?.length ?? 0) > 0;
    const gap = n.type === "gap";
    const pending = n.status === "verification_pending";
    const verified = n.status === "verified";
    const heat: 0 | 1 | 2 =
      tension || gap ? 2 : echo || pending ? 1 : verified ? 0 : 1;
    map[n.id] = { tension, echo, pending, verified, gap, heat };
  }
  return map;
}

export const EMPTY_BADGES: NodeBadges = {
  tension: false,
  echo: false,
  pending: false,
  verified: false,
  gap: false,
  heat: 1,
};

/** Tension pairs as displayable rows — used by the attention panel. */
export interface TensionPair {
  edgeId: string;
  by: string;
  a: GraphNode;
  b: GraphNode;
}

export function tensionPairs(
  nodes: GraphNode[],
  links: GraphLink[],
): TensionPair[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rows: TensionPair[] = [];
  for (const l of links) {
    if (l.relation !== "contradicts") continue;
    const a = byId.get(linkEnd(l.source));
    const b = byId.get(linkEnd(l.target));
    if (a && b) rows.push({ edgeId: l.id, by: l.created_by_agent, a, b });
  }
  return rows;
}
