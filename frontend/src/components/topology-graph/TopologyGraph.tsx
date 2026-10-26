"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import { useWorkspace, workspaceStore } from "@/store/workspace";

import { SymbolNode } from "./SymbolNode";

const nodeTypes = { symbol: SymbolNode };
// Keep fitted content clear of the minimap / controls overlaid on the bottom edge.
const FIT_PADDING = { top: "28px", bottom: "80px", x: "20px" } as const;

function Canvas() {
  const graph = useWorkspace((s) => s.graph);
  const selection = useWorkspace((s) => s.selection);
  const centerRequest = useWorkspace((s) => s.centerRequest);
  const { select, focusSymbol, expandNode } = workspaceStore.getState();
  const { fitView } = useReactFlow();
  const [hovered, setHovered] = useState<string | null>(null);

  const selectedId = selection.kind === "focus" ? null : selection.id;
  const focusId = graph?.focus ?? null;

  // Nodes live in React Flow's controlled state so measured sizes survive updates.
  // Rebuilding node objects without `measured` makes React Flow hide every node
  // until it re-measures them: a one-frame flicker on each selection that also
  // swallowed the second click of a double-click.
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);

  useEffect(() => {
    setNodes((previous) => {
      const measured = new Map(previous.map((n) => [n.id, n.measured]));
      return (graph?.nodes ?? []).map((n) => ({
        ...n,
        measured: measured.get(n.id),
        data: { ...n.data, selected: false, onExpand: expandNode },
      }));
    });
  }, [graph, expandNode, setNodes]);

  useEffect(() => {
    setNodes((current) =>
      current.map((n) =>
        n.data.selected === (n.id === selectedId) ? n : { ...n, data: { ...n.data, selected: n.id === selectedId } },
      ),
    );
  }, [selectedId, graph, setNodes]);

  const edges: Edge[] = useMemo(
    () =>
      (graph?.edges ?? []).map((e) => {
        const touchesFocus = e.source === focusId || e.target === focusId;
        const traced =
          selectedId !== null &&
          ((e.source === focusId && e.target === selectedId) || (e.source === selectedId && e.target === focusId));
        const hot = hovered !== null && (e.id === hovered || e.source === hovered || e.target === hovered);
        const kind = e.data?.kind === "INHERITS" ? "inherits" : "";
        return {
          ...e,
          animated: hot || traced,
          className: `${traced ? "trace" : selectedId === null && touchesFocus ? "on" : ""} ${kind}`.trim(),
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: traced ? "rgb(var(--trace))" : "rgb(var(--line))" },
        };
      }),
    [graph, focusId, selectedId, hovered],
  );

  // Bi-directional sync: a new focus (from search, j/k, double-click) recenters the canvas.
  useEffect(() => {
    if (!graph) return;
    const frame = requestAnimationFrame(() => {
      void fitView({ duration: 450, padding: FIT_PADDING, maxZoom: 1.1 });
    });
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerRequest]);

  if (!graph) {
    return <div className="h-full flex items-center justify-center text-[12px] text-muted">No symbol in focus.</div>;
  }

  return (
    <ReactFlow
      className="tracex-flow graph-fade"
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      nodeTypes={nodeTypes}
      nodesConnectable={false}
      nodesDraggable={false} // positions come from the layered layout
      // Double-click means "open definition". d3-zoom's dblclick-to-zoom handler also
      // stops propagation before the event reaches React's delegated listener on
      // `document` (Next.js hydrates the whole document), which would swallow
      // onNodeDoubleClick. Zoom stays available via wheel, pinch and the controls.
      zoomOnDoubleClick={false}
      elementsSelectable={false}
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, node) => {
        const role = (node.data as { role: string }).role;
        select(role === "focus" ? { kind: "focus" } : { kind: role as "caller" | "callee", id: node.id });
      }}
      onNodeDoubleClick={(_, node) => {
        if (node.id !== focusId) void focusSymbol(node.id);
      }}
      onNodeMouseEnter={(_, node) => setHovered(node.id)}
      onNodeMouseLeave={() => setHovered(null)}
      onEdgeMouseEnter={(_, edge) => setHovered(edge.id)}
      onEdgeMouseLeave={() => setHovered(null)}
      onPaneClick={() => select({ kind: "focus" })}
      fitView
      fitViewOptions={{ padding: FIT_PADDING, maxZoom: 1.1 }}
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="rgb(var(--line))" />
      <MiniMap
        pannable
        zoomable
        nodeBorderRadius={6}
        nodeColor={(n) =>
          (n.data as { role: string }).role === "focus" ? "rgb(var(--mint))" : n.id === selectedId ? "rgb(var(--trace))" : "rgb(var(--card))"
        }
        style={{ width: 96, height: 64 }}
      />
      <Controls showInteractive={false} position="bottom-left" orientation="horizontal" />
    </ReactFlow>
  );
}

export function TopologyGraph() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  );
}
