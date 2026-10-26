"use client";

import { Fragment, useMemo } from "react";

import { ArrowRight, ChevronLeft, ChevronRight } from "@/components/chrome/Icons";
import { basename, dirname } from "@/lib/format";
import { rangeLabel } from "@/lib/permalink";
import { currentHighlight, useWorkspace, workspaceStore, type Selection } from "@/store/workspace";

import { TopologyGraph } from "./TopologyGraph";

export function TopologyPanel() {
  const open = useWorkspace((s) => s.panels.right);
  const tab = useWorkspace((s) => s.tab);
  const { togglePanel, setTab } = workspaceStore.getState();

  return (
    <aside
      className="side relative shrink-0 border-l border-line bg-panel overflow-hidden"
      style={{ width: open ? 360 : 44 }}
      data-open={open}
      aria-label="Call graph and dependencies"
    >
      <div className="full absolute inset-y-0 right-0 w-[360px] flex flex-col">
        <div className="h-11 shrink-0 flex items-center gap-2 pl-2 pr-3 border-b border-line">
          <button
            type="button"
            onClick={() => togglePanel("right")}
            aria-label="Collapse graph panel ( ] )"
            title="Collapse  ]"
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card transition-colors"
          >
            <ChevronRight />
          </button>
          <div role="tablist" aria-label="Graph views" className="flex items-center p-0.5 rounded-lg bg-bg border border-line">
            {(
              [
                ["graph", "Topology Graph"],
                ["deps", "Dependencies & Imports"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`h-7 px-3 rounded-md text-[12px] transition-colors ${tab === key ? "bg-card text-ink" : "text-muted hover:text-ink"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="scroll flex-1 min-h-0 overflow-y-auto">
          {tab === "graph" ? (
            <section role="tabpanel" aria-label="Topology Graph" className="px-4 pt-4 pb-6">
              <GraphToolbar />
              <div className="h-[400px] rounded-xl border border-line bg-bg/50 overflow-hidden">
                <TopologyGraph />
              </div>
              <p className="mt-2.5 text-[11px] text-muted text-center">
                Click a node to trace it in code · double-click to open
              </p>
              <NodeCard />
            </section>
          ) : (
            <section role="tabpanel" aria-label="Dependencies and Imports" className="px-4 pt-4 pb-6">
              <Dependencies />
            </section>
          )}
        </div>
      </div>
      <div className="rail absolute inset-y-0 right-0 w-11 flex flex-col items-center pt-2 gap-3">
        <button
          type="button"
          onClick={() => togglePanel("right")}
          aria-label="Expand graph panel ( ] )"
          title="Expand  ]"
          className="w-8 h-8 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card transition-colors"
        >
          <ChevronLeft />
        </button>
        <span className="text-[10.5px] tracking-[.12em] uppercase text-muted [writing-mode:vertical-rl]">Graph</span>
      </div>
    </aside>
  );
}

function GraphToolbar() {
  const depth = useWorkspace((s) => s.graphDepth);
  const graph = useWorkspace((s) => s.graph);
  const focus = useWorkspace((s) => s.focus);
  const { setDepth } = workspaceStore.getState();
  // Direct neighbours only: fan-in / fan-out count distinct 1-hop callers / callees.
  const callers = graph?.nodes.filter((n) => n.data.depth === -1).length ?? 0;
  const callees = graph?.nodes.filter((n) => n.data.depth === 1).length ?? 0;
  return (
    <div className="mb-2.5 flex items-center gap-2 whitespace-nowrap text-[10.5px] font-medium uppercase tracking-[.08em] text-muted">
      <span title="Callers shown of total (fan-in)">
        Callers <span className="font-mono normal-case tracking-normal text-sub">{callers}/{focus?.fan_in ?? 0}</span>
      </span>
      <span title="Callees shown of total (fan-out)">
        Callees <span className="font-mono normal-case tracking-normal text-sub">{callees}/{focus?.fan_out ?? 0}</span>
      </span>
      <span className="flex-1" />
      <span className="normal-case tracking-normal">Hops</span>
      <div className="flex items-center p-0.5 rounded-md bg-bg border border-line" role="radiogroup" aria-label="Graph depth">
        {[1, 2, 3].map((d) => (
          <button
            key={d}
            type="button"
            role="radio"
            aria-checked={depth === d}
            onClick={() => void setDepth(d)}
            className={`w-6 h-5 rounded font-mono text-[11px] ${depth === d ? "bg-card text-ink" : "text-muted hover:text-ink"}`}
          >
            {d}
          </button>
        ))}
      </div>
    </div>
  );
}

function useSelectedInfo() {
  const focus = useWorkspace((s) => s.focus);
  const graph = useWorkspace((s) => s.graph);
  const selection = useWorkspace((s) => s.selection);
  const lineAnchor = useWorkspace((s) => s.lineAnchor);
  return useMemo(() => {
    if (!focus) return null;
    const node = selection.kind === "focus" ? null : graph?.nodes.find((n) => n.id === selection.id);
    const highlight = currentHighlight({ focus, graph, selection, lineAnchor });
    const ranges = highlight?.ranges ?? [];
    const first = ranges[0];
    const last = ranges[ranges.length - 1];
    return {
      rel: node ? (node.data.role === "caller" ? "Caller" : "Callee") : "Focus",
      kind: node?.data.kind ?? focus.kind,
      title: node?.data.qualified_name ?? focus.qualified_name,
      file: node ? `${node.data.file_path}:${node.data.start_line}` : focus.file_path,
      inN: node?.data.fan_in ?? focus.fan_in,
      outN: node?.data.fan_out ?? focus.fan_out,
      range: first && last ? rangeLabel([first[0], last[1]]) : "",
      target: node?.id ?? null,
    };
  }, [focus, graph, selection, lineAnchor]);
}

function NodeCard() {
  const info = useSelectedInfo();
  const { focusSymbol } = workspaceStore.getState();
  if (!info) return null;
  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <span className="uppercase tracking-[.08em]">{info.rel}</span>
        <span>·</span>
        <span>{info.kind}</span>
      </div>
      <div className="mt-1.5 font-mono text-[13px] font-medium text-ink break-all">{info.title}</div>
      <div className="mt-0.5 font-mono text-[11px] text-muted break-all">{info.file}</div>
      <div className="mt-3 flex items-center gap-5 text-[11.5px] text-sub">
        <span>
          <span className="font-mono text-ink">{info.inN}</span> in
        </span>
        <span>
          <span className="font-mono text-ink">{info.outN}</span> out
        </span>
        <span className="ml-auto font-mono text-muted">{info.range}</span>
      </div>
      {info.target && (
        <button
          type="button"
          onClick={() => void focusSymbol(info.target!)}
          className="mt-3 w-full h-8 inline-flex items-center justify-center gap-1.5 rounded-lg border border-mint/30 text-mint text-[12px] hover:bg-mint/10 transition-colors"
        >
          Open definition
          <ArrowRight />
        </button>
      )}
    </div>
  );
}

function SectionHead({ title, count }: { title: string; count?: string | number }) {
  return (
    <h3 className="flex items-center gap-2 mb-2 text-[11px] font-medium uppercase tracking-[.08em] text-muted">
      {title}
      {count !== undefined && <span className="font-mono normal-case tracking-normal text-muted/70">{count}</span>}
    </h3>
  );
}

function Dependencies() {
  const focus = useWorkspace((s) => s.focus);
  const graph = useWorkspace((s) => s.graph);
  const selection = useWorkspace((s) => s.selection);
  const { select } = workspaceStore.getState();
  if (!focus) return <p className="text-[12px] text-muted">No symbol in focus.</p>;

  const direct = (role: "caller" | "callee") =>
    (graph?.nodes ?? [])
      .filter((n) => n.data.role === role && Math.abs(n.data.depth) === 1)
      .sort((a, b) => a.data.qualified_name.localeCompare(b.data.qualified_name));
  const callLines = (calleeId: string) =>
    focus.call_sites.filter((c) => c.target_id === calleeId).map((c) => c.line);

  const table = (role: "caller" | "callee") => {
    const rows = direct(role);
    if (!rows.length) return <p className="text-[12px] text-muted">None resolved in this repository.</p>;
    return (
      <div className="rounded-lg border border-line overflow-hidden">
        {rows.map((n) => {
          const selected = selection.kind === role && selection.id === n.id;
          const lines = role === "callee" ? callLines(n.id) : [];
          const loc = role === "callee" && lines.length ? `L${lines.join(", L")}` : `${basename(n.data.file_path)}:${n.data.start_line}`;
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => select({ kind: role, id: n.id } as Selection)}
              className={`w-full flex items-center gap-3 px-3 h-10 text-left border-b border-line last:border-b-0 transition-colors ${selected ? "bg-trace/10" : "hover:bg-card/60"}`}
            >
              <span className={`flex-1 min-w-0 truncate font-mono text-[12px] ${selected ? "text-ink" : "text-ink/85"}`}>
                {n.data.qualified_name}
                {n.data.kind !== "class" && "()"}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-muted">{loc}</span>
            </button>
          );
        })}
      </div>
    );
  };

  const unresolved = [...new Set(focus.call_sites.filter((c) => !c.target_id).map((c) => c.callee))];
  const scopeRows: [string, string[]][] = (
    [
      ["decorators", focus.decorators],
      ["routes", focus.routes],
      ["bases", focus.bases],
      ["params", focus.scope.params.map((p) => `${p.name}${p.annotation ? `: ${p.annotation}` : ""}${p.default ? ` = ${p.default}` : ""}`)],
      ["locals", focus.scope.locals],
      ["raises", focus.scope.raises],
      ["returns", focus.scope.return_type ? [focus.scope.return_type] : focus.scope.returns],
      ["external", unresolved],
    ] as [string, string[]][]
  ).filter(([, values]) => values.length);

  return (
    <>
      <section className="mb-6">
        <SectionHead title="Callers" count={`${direct("caller").length} of ${focus.fan_in}`} />
        {table("caller")}
      </section>
      <section className="mb-6">
        <SectionHead title="Callees" count={`${direct("callee").length} of ${focus.fan_out}`} />
        {table("callee")}
      </section>
      <section className="mb-6">
        <SectionHead title="Imports" count={focus.imports.length} />
        {focus.imports.length ? (
          <ul className="flex flex-col gap-1">
            {focus.imports.map((im, i) => (
              <li key={i} className="truncate font-mono text-[11.5px] text-sub px-3 py-1.5 rounded-md bg-card/50">
                {im.name === null
                  ? `import ${im.module}${im.alias ? ` as ${im.alias}` : ""}`
                  : `from ${im.module} import ${im.name}${im.alias ? ` as ${im.alias}` : ""}`}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12px] text-muted">No module-level imports in this file.</p>
        )}
      </section>
      <section>
        <SectionHead title="AST scope" />
        <div className="rounded-lg border border-line p-3 font-mono text-[11.5px]">
          <div className="text-muted">{[...dirname(focus.file_path), basename(focus.file_path)].join("/")}</div>
          {focus.qualified_name.split(".").map((part, i) => (
            <div key={i} className="text-sub" style={{ paddingLeft: (i + 1) * 12 }}>
              <span className="text-muted/60">└ </span>
              {part}
            </div>
          ))}
          {scopeRows.length > 0 && (
            <div className="mt-2.5 pt-2.5 border-t border-line grid grid-cols-[84px_1fr] gap-x-3 gap-y-1.5">
              {scopeRows.map(([key, values]) => (
                <Fragment key={key}>
                  <span className="text-muted">{key}</span>
                  <span className="text-ink/85 break-words">{values.join(", ")}</span>
                </Fragment>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
