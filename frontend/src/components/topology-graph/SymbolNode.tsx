"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { memo } from "react";

import { basename } from "@/lib/format";
import { FOCUS_W, NODE_W, type SymbolFlowNode } from "@/lib/graph-layout";

export type SymbolNodeData = SymbolFlowNode["data"] & {
  selected?: boolean;
  onExpand?: (id: string, direction: "callers" | "callees") => void;
};

function Expander({ count, side, onClick }: { count: number; side: "top" | "bottom"; onClick: () => void }) {
  const noun = side === "top" ? "caller" : "callee";
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      title={`Show ${count} more ${noun}${count === 1 ? "" : "s"}`}
      className={`nodrag absolute left-1/2 -translate-x-1/2 ${side === "top" ? "-top-2.5" : "-bottom-2.5"} h-5 px-1.5 rounded-full border border-line bg-panel font-mono text-[10px] leading-none text-sub hover:text-ink hover:border-mint/50 transition-colors`}
    >
      +{count} {noun}
      {count === 1 ? "" : "s"}
    </button>
  );
}

function SymbolNodeView({ id, data }: NodeProps) {
  const d = data as SymbolNodeData;
  const cls = d.role === "focus" ? "focus" : d.selected ? "sel" : "";
  return (
    <div
      className={`gnode relative rounded-[10px] px-3 py-2 ${cls}`}
      style={{ width: d.role === "focus" ? FOCUS_W : NODE_W }}
      aria-label={`${d.role} ${d.qualified_name}`}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className={`font-mono font-medium text-ink truncate ${d.role === "focus" ? "text-[13px]" : "text-[11.5px]"}`}>
        {d.label}
        {d.kind !== "class" && "()"}
      </div>
      <div className="font-mono text-[10px] text-sub/75 truncate">
        {basename(d.file_path)}:{d.start_line}
      </div>
      {d.hidden_callers > 0 && <Expander count={d.hidden_callers} side="top" onClick={() => d.onExpand?.(id, "callers")} />}
      {d.hidden_callees > 0 && <Expander count={d.hidden_callees} side="bottom" onClick={() => d.onExpand?.(id, "callees")} />}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

export const SymbolNode = memo(SymbolNodeView);
