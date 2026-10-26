"use client";

import { useStore } from "zustand";
import { createStore, type StoreApi } from "zustand/vanilla";

import { api as defaultApi, ApiError, type Api } from "@/lib/api";
import { callLinesTo, fromResponse, mergeExpansion, type FlowGraph } from "@/lib/graph-layout";
import { extendSelection, type LineRange } from "@/lib/permalink";
import type { Health, IndexSummary, Pillar, SearchResponse, SymbolDetail } from "@/lib/types";

export type Selection = { kind: "focus" } | { kind: "caller" | "callee"; id: string };
export type Tab = "graph" | "deps";
export type Theme = "dark" | "light";
export type Popover = "filters" | "telemetry" | null;
export type Pillars = Record<Pillar, boolean> & { rerank: boolean };

export interface WorkspaceState {
  health: Health | null;
  index: IndexSummary | null;
  indexing: boolean;
  connectionError: string | null;

  query: string;
  activeQuery: string;
  pillars: Pillars;
  results: SearchResponse | null;
  searching: boolean;
  searchError: string | null;

  focusId: string | null;
  focus: SymbolDetail | null;
  focusLoading: boolean;
  selection: Selection;
  lineAnchor: LineRange | null;
  hoverTarget: string | null;

  graph: FlowGraph | null;
  graphDepth: number;
  centerRequest: number;

  panels: { left: boolean; right: boolean };
  tab: Tab;
  theme: Theme;
  popover: Popover;
  shortcutsOpen: boolean;
  toast: { id: number; message: string } | null;

  init: () => Promise<void>;
  reindex: (path: string) => Promise<void>;
  setQuery: (query: string) => void;
  runSearch: (query?: string) => Promise<void>;
  togglePillar: (pillar: keyof Pillars) => void;
  focusSymbol: (id: string, options?: { range?: LineRange | null }) => Promise<void>;
  select: (selection: Selection) => void;
  anchorLine: (line: number, shift: boolean) => void;
  setHoverTarget: (id: string | null) => void;
  expandNode: (id: string, direction: "callers" | "callees") => Promise<void>;
  setDepth: (depth: number) => Promise<void>;
  stepHit: (delta: 1 | -1) => void;
  goToDefinition: () => void;
  togglePanel: (side: "left" | "right", open?: boolean) => void;
  setTab: (tab: Tab) => void;
  setTheme: (theme: Theme) => void;
  setPopover: (popover: Popover) => void;
  setShortcutsOpen: (open: boolean) => void;
  showToast: (message: string) => void;
}

const message = (error: unknown) =>
  error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);

export function createWorkspaceStore(api: Api = defaultApi, initial: Partial<WorkspaceState> = {}) {
  let searchController: AbortController | null = null;
  let focusToken = 0;
  let toastId = 0;

  return createStore<WorkspaceState>()((set, get) => ({
    health: null,
    index: null,
    indexing: false,
    connectionError: null,

    query: "",
    activeQuery: "",
    pillars: { dense: true, bm25: true, graph: true, rerank: false },
    results: null,
    searching: false,
    searchError: null,

    focusId: null,
    focus: null,
    focusLoading: false,
    selection: { kind: "focus" },
    lineAnchor: null,
    hoverTarget: null,

    graph: null,
    graphDepth: 1,
    centerRequest: 0,

    panels: { left: true, right: true },
    tab: "graph",
    theme: "dark",
    popover: null,
    shortcutsOpen: false,
    toast: null,
    ...initial,

    async init() {
      try {
        const health = await api.health();
        set({ health, connectionError: null });
        if (health.indexed) set({ index: await api.index() });
      } catch (error) {
        set({ connectionError: `Cannot reach the Tracex API (${message(error)}). Is the backend running on :8000?` });
      }
    },

    async reindex(path) {
      set({ indexing: true });
      try {
        const index = await api.reindex(path);
        set({
          index,
          health: { status: "ok", indexed: true, version: get().health?.version ?? "" },
          results: null,
          focusId: null,
          focus: null,
          graph: null,
          connectionError: null,
        });
        get().showToast(`Indexed ${index.symbols} symbols from ${index.files} files`);
      } catch (error) {
        get().showToast(`Indexing failed: ${message(error)}`);
      } finally {
        set({ indexing: false });
      }
    },

    setQuery: (query) => set({ query }),

    async runSearch(query) {
      const q = (query ?? get().query).trim();
      if (!q) return;
      searchController?.abort();
      const controller = new AbortController();
      searchController = controller;
      const { pillars } = get();
      set({ query: q, activeQuery: q, searching: true, searchError: null });
      try {
        const results = await api.search(q, pillars, controller.signal);
        if (controller.signal.aborted) return;
        set({ results, searching: false });
        const top = results.hits[0];
        if (top && top.symbol_id !== get().focusId) await get().focusSymbol(top.symbol_id);
      } catch (error) {
        if (controller.signal.aborted) return;
        set({ searching: false, searchError: message(error) });
      }
    },

    togglePillar(pillar) {
      const next = { ...get().pillars, [pillar]: !get().pillars[pillar] };
      if (!next.dense && !next.bm25) {
        get().showToast("Keep Dense or BM25 on: graph expansion needs seed results");
        return;
      }
      if (next.rerank && !get().index?.reranker_model) {
        get().showToast("No cross-encoder loaded: start the API with TRACEX_RERANKER=1");
        return;
      }
      set({ pillars: next });
      if (get().activeQuery) void get().runSearch(get().activeQuery);
    },

    async focusSymbol(id, options) {
      const token = ++focusToken;
      set({ focusId: id, focusLoading: true, selection: { kind: "focus" }, lineAnchor: options?.range ?? null });
      try {
        const [focus, graph] = await Promise.all([api.symbol(id), api.graph(id, get().graphDepth)]);
        if (token !== focusToken) return;
        set((s) => ({ focus, graph: fromResponse(graph), focusLoading: false, centerRequest: s.centerRequest + 1 }));
      } catch (error) {
        if (token !== focusToken) return;
        set({ focusLoading: false });
        get().showToast(`Could not open ${id}: ${message(error)}`);
      }
    },

    select: (selection) => set({ selection, lineAnchor: null }),

    anchorLine(line, shift) {
      set((s) => ({ lineAnchor: extendSelection(s.lineAnchor, line, shift), selection: { kind: "focus" } }));
    },

    setHoverTarget: (hoverTarget) => set({ hoverTarget }),

    async expandNode(id, direction) {
      try {
        const expansion = await api.graph(id, 1);
        const graph = get().graph;
        if (graph) {
          set((s) => ({ graph: mergeExpansion(graph, id, expansion, direction), centerRequest: s.centerRequest + 1 }));
        }
      } catch (error) {
        get().showToast(`Expansion failed: ${message(error)}`);
      }
    },

    async setDepth(depth) {
      set({ graphDepth: depth });
      const id = get().focusId;
      if (!id) return;
      try {
        const graph = await api.graph(id, depth);
        if (get().focusId === id) set((s) => ({ graph: fromResponse(graph), centerRequest: s.centerRequest + 1 }));
      } catch (error) {
        get().showToast(`Graph failed: ${message(error)}`);
      }
    },

    stepHit(delta) {
      const hits = get().results?.hits ?? [];
      if (!hits.length) return;
      const index = hits.findIndex((h) => h.symbol_id === get().focusId);
      const next = index < 0 ? 0 : Math.min(hits.length - 1, Math.max(0, index + delta));
      const hit = hits[next];
      if (hit && next !== index) void get().focusSymbol(hit.symbol_id);
    },

    goToDefinition() {
      const { selection, hoverTarget } = get();
      const target = selection.kind !== "focus" ? selection.id : hoverTarget;
      if (target) void get().focusSymbol(target);
      else get().showToast("Select a graph node or hover a resolved call, then press g d");
    },

    togglePanel: (side, open) =>
      set((s) => ({ panels: { ...s.panels, [side]: open ?? !s.panels[side] } })),
    setTab: (tab) => set({ tab }),
    setTheme: (theme) => set({ theme }),
    setPopover: (popover) => set({ popover }),
    setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
    showToast: (text) => set({ toast: { id: ++toastId, message: text } }),
  }));
}

export interface Highlight {
  ranges: LineRange[];
  traced: boolean;
}

/** Group sorted line numbers into contiguous ranges. */
export function toRanges(lines: number[]): LineRange[] {
  const sorted = [...new Set(lines)].sort((a, b) => a - b);
  const ranges: [number, number][] = [];
  for (const line of sorted) {
    const last = ranges[ranges.length - 1];
    if (last && line === last[1] + 1) last[1] = line;
    else ranges.push([line, line]);
  }
  return ranges;
}

/**
 * What the inspector highlights:
 * - a user line anchor (click / shift+click) wins;
 * - a selected callee traces the exact call-site lines inside the focus;
 * - a selected caller traces the focus header it calls into;
 * - otherwise the whole focus symbol.
 */
export function currentHighlight(s: Pick<WorkspaceState, "focus" | "lineAnchor" | "selection" | "graph">): Highlight | null {
  const focus = s.focus;
  if (!focus) return null;
  if (s.lineAnchor) return { ranges: [s.lineAnchor], traced: false };
  const { start_line, end_line } = focus.highlight;
  const selection = s.selection;
  if (selection.kind === "callee") {
    const lines = callLinesTo(s.graph, focus.symbol_id, selection.id);
    const fallback = focus.call_sites.filter((c) => c.target_id === selection.id).map((c) => c.line);
    const traced = lines.length ? lines : fallback;
    if (traced.length) return { ranges: toRanges(traced), traced: true };
  }
  if (selection.kind === "caller") {
    return { ranges: [[start_line, Math.min(end_line, start_line + focus.decorators.length)]], traced: true };
  }
  return { ranges: [[start_line, end_line]], traced: false };
}

export type WorkspaceStore = StoreApi<WorkspaceState>;

export const workspaceStore = createWorkspaceStore();

export function useWorkspace<T>(selector: (state: WorkspaceState) => T): T {
  return useStore(workspaceStore, selector);
}
