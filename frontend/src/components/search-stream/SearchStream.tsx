"use client";

import { useEffect, useRef, useState } from "react";

import { ChevronLeft, ChevronRight } from "@/components/chrome/Icons";
import { ORIGIN_TONE, originLabel } from "@/lib/rrf";
import type { SearchHit } from "@/lib/types";
import { useWorkspace, workspaceStore } from "@/store/workspace";

import { RRFPopover } from "./RRFPopover";

export function SearchStream() {
  const open = useWorkspace((s) => s.panels.left);
  const results = useWorkspace((s) => s.results);
  const searching = useWorkspace((s) => s.searching);
  const searchError = useWorkspace((s) => s.searchError);
  const activeQuery = useWorkspace((s) => s.activeQuery);
  const focusId = useWorkspace((s) => s.focusId);
  const { togglePanel, focusSymbol } = workspaceStore.getState();
  const listRef = useRef<HTMLDivElement>(null);

  // Keep the focused hit visible during j / k navigation.
  useEffect(() => {
    listRef.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "nearest" });
  }, [focusId]);

  const hits = results?.hits ?? [];

  return (
    <aside
      className="side relative shrink-0 border-r border-line bg-panel overflow-hidden"
      style={{ width: open ? 300 : 44 }}
      data-open={open}
      aria-label="Search results"
    >
      <div className="full absolute inset-y-0 left-0 w-[300px] flex flex-col">
        <div className="h-11 shrink-0 flex items-center gap-2 pl-4 pr-2">
          <span className="text-[11px] font-medium uppercase tracking-[.08em] text-muted">Results</span>
          <span className="text-[11px] text-muted font-mono">{!searching && hits.length ? hits.length : ""}</span>
          {results && !searching && (
            <span className="text-[11px] text-muted/70 font-mono">of {results.candidates}</span>
          )}
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => togglePanel("left")}
            aria-label="Collapse results ( [ )"
            title="Collapse  ["
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card transition-colors"
          >
            <ChevronLeft />
          </button>
        </div>
        {activeQuery && <p className="px-4 pb-3 text-[12.5px] leading-relaxed text-sub break-words">{activeQuery}</p>}
        <div ref={listRef} className="scroll flex-1 min-h-0 overflow-y-auto pb-4" role="list">
          {searching ? (
            [1, 2, 3, 4].map((i) => <div key={i} className="mx-3 mb-2 h-[84px] rounded-lg bg-card/60 animate-pulse" />)
          ) : searchError ? (
            <p className="px-4 py-8 text-center text-[12.5px] leading-relaxed text-sub">{searchError}</p>
          ) : results && !hits.length ? (
            <p className="px-4 py-8 text-center text-[12.5px] leading-relaxed text-sub">
              No matches.
              <br />
              Loosen a prefix filter or rephrase the question.
            </p>
          ) : !results ? (
            <p className="px-4 py-8 text-center text-[12.5px] leading-relaxed text-muted">
              Ask a question in natural language, or jump with <span className="q-sym px-0.5">@symbol</span>,{" "}
              <span className="q-route px-0.5">#route</span> and <span className="q-path px-0.5">/path</span>.
            </p>
          ) : (
            <div className="list-fade">
              {hits.map((hit) => (
                <HitCard
                  key={hit.symbol_id}
                  hit={hit}
                  current={hit.symbol_id === focusId}
                  onOpen={() => void focusSymbol(hit.symbol_id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="rail absolute inset-y-0 left-0 w-11 flex flex-col items-center pt-2 gap-3">
        <button
          type="button"
          onClick={() => togglePanel("left")}
          aria-label="Expand results ( [ )"
          title="Expand  ["
          className="w-8 h-8 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card transition-colors"
        >
          <ChevronRight />
        </button>
        <span className="text-[10.5px] tracking-[.12em] uppercase text-muted [writing-mode:vertical-rl] rotate-180">
          Results
        </span>
      </div>
    </aside>
  );
}

export function HitCard({ hit, current, onOpen }: { hit: SearchHit; current: boolean; onOpen: () => void }) {
  const [explain, setExplain] = useState(false);
  const origin = originLabel(hit);
  const tone = ORIGIN_TONE[origin];
  const snippetLine =
    hit.snippet
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith("@") && !l.startsWith("#") && !l.startsWith("//")) ?? hit.signature;

  return (
    <div role="listitem" className="relative">
      <button
        type="button"
        className="hit w-full text-left block pl-[14px] pr-4 py-3 border-l-2 border-transparent hover:bg-card/50"
        aria-current={current}
        onClick={onOpen}
      >
        <span className="flex items-center gap-2">
          <span className="hit-name flex-1 min-w-0 truncate font-mono text-[12.5px] font-medium text-ink/85">
            {hit.qualified_name}
            {hit.kind !== "class" && "()"}
          </span>
          <span
            className="shrink-0 px-1.5 py-[1px] rounded text-[10.5px] font-medium cursor-help"
            style={{ color: `rgb(var(--${tone}))`, background: `rgb(var(--${tone}) / .09)` }}
            onMouseEnter={() => setExplain(true)}
            onMouseLeave={() => setExplain(false)}
            onFocus={() => setExplain(true)}
            onBlur={() => setExplain(false)}
            tabIndex={0}
            aria-label={`${origin} match, show score breakdown`}
          >
            {origin}
          </span>
        </span>
        <span className="block mt-1 truncate font-mono text-[11px] text-muted">
          {hit.file_path}:{hit.start_line}-{hit.end_line}
        </span>
        <span className="block mt-1.5 truncate font-mono text-[11px] text-sub/80">{snippetLine}</span>
      </button>
      <RRFPopover hit={hit} open={explain} />
    </div>
  );
}
