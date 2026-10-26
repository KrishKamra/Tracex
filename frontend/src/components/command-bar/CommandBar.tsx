"use client";

import { useEffect, useRef, useState } from "react";

import { FilterIcon, SearchIcon } from "@/components/chrome/Icons";
import { PREFIX_HELP, segmentQuery, type SegmentKind } from "@/lib/query-syntax";
import { PILLARS } from "@/lib/rrf";
import { useWorkspace, workspaceStore } from "@/store/workspace";

const SEGMENT_CLASS: Record<SegmentKind, string> = {
  symbol: "q-sym",
  route: "q-route",
  path: "q-path",
  text: "",
  space: "",
};

export const QUERY_INPUT_ID = "tracex-query";

/** Mirror layer behind the transparent input: same text, colored prefix tokens. */
export function QueryMirror({ value }: { value: string }) {
  return (
    <span aria-hidden="true" className="q-mirror pointer-events-none absolute left-0 inset-y-0 flex items-center text-ink">
      {segmentQuery(value).map((segment, i) => (
        <span key={i} className={SEGMENT_CLASS[segment.kind]} data-kind={segment.kind}>
          {segment.text}
        </span>
      ))}
    </span>
  );
}

export function CommandBar() {
  const query = useWorkspace((s) => s.query);
  const pillars = useWorkspace((s) => s.pillars);
  const popover = useWorkspace((s) => s.popover);
  const hasReranker = useWorkspace((s) => Boolean(s.index?.reranker_model));
  const { setQuery, runSearch, togglePillar, setPopover } = workspaceStore.getState();
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);

  // Keep the mirror scrolled with the input when text overflows.
  useEffect(() => {
    const input = inputRef.current;
    const mirror = mirrorRef.current;
    if (!input || !mirror) return;
    const sync = () => (mirror.scrollLeft = input.scrollLeft);
    input.addEventListener("scroll", sync);
    sync();
    return () => input.removeEventListener("scroll", sync);
  }, [query]);

  const filtersOpen = popover === "filters";
  const showHelp = focused && !filtersOpen;

  return (
    <div className="relative w-full max-w-[580px]">
      <label className="flex items-center gap-2.5 h-8 pl-3 pr-1 rounded-lg border border-line bg-bg/60 focus-within:border-mint/40 transition-colors">
        <SearchIcon />
        <span className="sr-only">Search the codebase</span>
        <div className="relative flex-1 min-w-0 h-full">
          <div ref={mirrorRef} className="absolute inset-0 overflow-hidden text-[13px]">
            <QueryMirror value={query} />
          </div>
          <input
            id={QUERY_INPUT_ID}
            ref={inputRef}
            type="text"
            spellCheck={false}
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void runSearch();
              }
            }}
            className="q-input relative w-full h-full bg-transparent outline-none text-[13px] placeholder:text-muted"
            placeholder="Ask anything or type @symbol, #route, /path…"
            aria-describedby="query-help"
          />
        </div>
        <button
          type="button"
          aria-haspopup="true"
          aria-expanded={filtersOpen}
          title="Retrieval pillars"
          data-popover
          onClick={() => setPopover(filtersOpen ? null : "filters")}
          className="flex items-center gap-1.5 h-6 px-2 rounded-md text-muted hover:text-ink hover:bg-card transition-colors"
        >
          <FilterIcon />
          <span className="flex items-center gap-[3px]">
            {PILLARS.map((p) => (
              <span
                key={p.key}
                className="w-[5px] h-[5px] rounded-full"
                style={{ background: pillars[p.key] ? `rgb(${p.color})` : "rgb(var(--line))" }}
              />
            ))}
            <span
              className="w-[5px] h-[5px] rounded-full"
              style={{ background: pillars.rerank ? "rgb(var(--ink))" : "rgb(var(--line))" }}
            />
          </span>
        </button>
        <kbd className="hidden md:inline-flex items-center h-6 px-1.5 rounded-md border border-line text-[10.5px] text-muted">
          ⌘K
        </kbd>
      </label>

      {/* prefix help: shown while typing */}
      <div
        id="query-help"
        className="pop glass absolute left-0 right-0 top-10 z-30 rounded-xl border border-line shadow-2xl shadow-black/40 p-2"
        data-open={showHelp}
        role="note"
      >
        <div className="px-2 pt-1 pb-1.5 text-[10.5px] font-medium uppercase tracking-[.08em] text-muted">
          Prefix filters · combine with free text
        </div>
        {PREFIX_HELP.map((p) => (
          <button
            key={p.prefix}
            type="button"
            tabIndex={-1}
            onMouseDown={(e) => {
              e.preventDefault();
              setQuery(p.example);
              void runSearch(p.example);
            }}
            className="w-full flex items-center gap-3 px-2 h-8 rounded-lg text-left hover:bg-card transition-colors"
          >
            <span className={`font-mono text-[12px] px-1 ${SEGMENT_CLASS[p.kind]}`}>{p.prefix}</span>
            <span className="text-[12px] text-ink w-14">{p.label}</span>
            <span className="font-mono text-[11.5px] text-muted truncate">{p.example}</span>
          </button>
        ))}
        <div className="px-2 pt-1.5 text-[11px] text-muted border-t border-line mt-1">
          <kbd>Enter</kbd> search · <kbd>Esc</kbd> close · <kbd>?</kbd> all shortcuts
        </div>
      </div>

      {/* pillar toggles */}
      <div
        className="pop glass absolute right-0 top-10 z-30 w-[300px] rounded-xl border border-line shadow-2xl shadow-black/40 p-2"
        role="dialog"
        aria-label="Retrieval pillars"
        data-open={filtersOpen}
        data-popover
      >
        <div className="px-2 pt-1.5 pb-2 text-[10.5px] font-medium uppercase tracking-[.08em] text-muted">
          Retrieval pillars
        </div>
        <div className="flex flex-col">
          {PILLARS.map((p) => (
            <PillarSwitch
              key={p.key}
              on={pillars[p.key]}
              color={`rgb(${p.color})`}
              name={p.name}
              desc={p.desc}
              onToggle={() => togglePillar(p.key)}
            />
          ))}
          <PillarSwitch
            on={pillars.rerank}
            color="rgb(var(--ink))"
            name="Cross-encoder rerank"
            desc={hasReranker ? "Rescore the fused top-20 jointly" : "Start the API with TRACEX_RERANKER=1"}
            onToggle={() => togglePillar("rerank")}
          />
        </div>
        <div className="px-2 pt-2 pb-1 text-[11px] text-muted border-t border-line mt-1">
          Results fuse with weighted Reciprocal Rank Fusion (k = 60).
        </div>
      </div>
    </div>
  );
}

function PillarSwitch(props: { on: boolean; color: string; name: string; desc: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={props.on}
      onClick={props.onToggle}
      className="flex items-center gap-3 px-2 py-2 rounded-lg text-left hover:bg-card transition-colors"
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: props.color }} />
      <span className="flex-1 min-w-0">
        <span className="block text-[12.5px] text-ink">{props.name}</span>
        <span className="block text-[11px] text-muted">{props.desc}</span>
      </span>
      <span className="switch" />
    </button>
  );
}
