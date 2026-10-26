// Converts API ego networks into React Flow nodes/edges and merges "+N"
// expansions into the canvas. Pure functions, so they are unit-tested.
//
// Layout follows the golden reference: callers above, focus centred, callees
// below. Each depth layer wraps into a two-column grid so the canvas stays
// legible inside the 360px side panel.

import type { Edge, Node } from "@xyflow/react";
import type { GraphEdgeOut, GraphNodeData, GraphResponse } from "./types";

export const NODE_W = 168;
export const FOCUS_W = 200;
export const NODE_H = 50;
export const COLS = 2;
const COL_GAP = 16;
const ROW_GAP = 26; // room for the +N pills that straddle node edges
const LAYER_GAP = 64;

export type SymbolFlowNode = Node<GraphNodeData & Record<string, unknown>, "symbol">;
export type CallFlowEdge = Edge<{ kind: "CALLS" | "INHERITS"; call_lines: number[] } & Record<string, unknown>>;

export interface FlowGraph {
  focus: string;
  nodes: SymbolFlowNode[];
  edges: CallFlowEdge[];
}

export const nodeWidth = (n: Pick<SymbolFlowNode, "data">) => (n.data.role === "focus" ? FOCUS_W : NODE_W);

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** Deterministic layered layout by depth (negative = upstream). */
export function layoutByDepth(nodes: SymbolFlowNode[]): SymbolFlowNode[] {
  const layers = new Map<number, SymbolFlowNode[]>();
  for (const n of nodes) layers.set(n.data.depth, [...(layers.get(n.data.depth) ?? []), n]);
  const positions = new Map<string, { x: number; y: number }>();
  let cursor = 0;
  for (const depth of [...layers.keys()].sort((a, b) => a - b)) {
    const members = layers
      .get(depth)!
      .slice()
      .sort((a, b) => a.data.qualified_name.localeCompare(b.data.qualified_name));
    const focus = members.filter((n) => n.data.role === "focus");
    const rest = members.filter((n) => n.data.role !== "focus");
    const rows = [...(focus.length ? [focus] : []), ...chunk(rest, COLS)];
    rows.forEach((row, r) => {
      const total = row.reduce((w, n) => w + nodeWidth(n), 0) + COL_GAP * (row.length - 1);
      let x = -total / 2;
      for (const n of row) {
        positions.set(n.id, { x, y: cursor + r * (NODE_H + ROW_GAP) });
        x += nodeWidth(n) + COL_GAP;
      }
    });
    cursor += rows.length * (NODE_H + ROW_GAP) - ROW_GAP + LAYER_GAP;
  }
  return nodes.map((n) => ({ ...n, position: positions.get(n.id) ?? n.position }));
}

function toEdge(edge: GraphEdgeOut): CallFlowEdge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    data: { ...edge.data },
  };
}

export function fromResponse(graph: GraphResponse): FlowGraph {
  return withHiddenCounts({
    focus: graph.focus,
    nodes: layoutByDepth(
      graph.nodes.map((n) => ({ id: n.id, type: "symbol", position: { ...n.position }, data: { ...n.data } })),
    ),
    edges: graph.edges.map(toEdge),
  });
}

/**
 * Recompute "+N" counters from what is on the canvas: fan-in / fan-out are the
 * true distinct caller / callee counts, so hidden = total - visible.
 */
export function withHiddenCounts(graph: FlowGraph): FlowGraph {
  const visibleIn = new Map<string, Set<string>>();
  const visibleOut = new Map<string, Set<string>>();
  for (const e of graph.edges) {
    if (e.data?.kind !== "CALLS") continue;
    if (!visibleIn.has(e.target)) visibleIn.set(e.target, new Set());
    if (!visibleOut.has(e.source)) visibleOut.set(e.source, new Set());
    visibleIn.get(e.target)!.add(e.source);
    visibleOut.get(e.source)!.add(e.target);
  }
  return {
    ...graph,
    nodes: graph.nodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        hidden_callers: Math.max(0, n.data.fan_in - (visibleIn.get(n.id)?.size ?? 0)),
        hidden_callees: Math.max(0, n.data.fan_out - (visibleOut.get(n.id)?.size ?? 0)),
      },
    })),
  };
}

/**
 * Merge one direction of `expansion` (the ego network of `anchorId`) into the
 * canvas: new callers land one layer above the anchor, callees one below.
 */
export function mergeExpansion(
  graph: FlowGraph,
  anchorId: string,
  expansion: GraphResponse,
  direction: "callers" | "callees",
): FlowGraph {
  const anchor = graph.nodes.find((n) => n.id === anchorId);
  if (!anchor) return graph;
  const existing = new Set(graph.nodes.map((n) => n.id));
  const role = direction === "callers" ? "caller" : "callee";
  const depth = anchor.data.depth + (direction === "callers" ? -1 : 1);
  const added: SymbolFlowNode[] = expansion.nodes
    .filter((n) => n.data.role === role && !existing.has(n.id))
    .map((n) => ({ id: n.id, type: "symbol", position: { ...anchor.position }, data: { ...n.data, role, depth } }));
  const ids = new Set([...existing, ...added.map((n) => n.id)]);
  const edgeIds = new Set(graph.edges.map((e) => e.id));
  const newEdges = expansion.edges.filter((e) => ids.has(e.source) && ids.has(e.target) && !edgeIds.has(e.id)).map(toEdge);
  return withHiddenCounts({
    focus: graph.focus,
    nodes: layoutByDepth([...graph.nodes, ...added]),
    edges: [...graph.edges, ...newEdges],
  });
}

/** Lines in the focus symbol where it calls `calleeId` (from the CALLS edge). */
export function callLinesTo(graph: FlowGraph | null, focusId: string, calleeId: string): number[] {
  const edge = graph?.edges.find((e) => e.source === focusId && e.target === calleeId && e.data?.kind === "CALLS");
  return edge?.data?.call_lines ?? [];
}
