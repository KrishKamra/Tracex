"use client";

import { useEffect, useRef } from "react";

import { Header } from "@/components/chrome/Header";
import { IndexGate, ShortcutsModal, Toast } from "@/components/chrome/Overlays";
import { StatusBar } from "@/components/chrome/StatusBar";
import { CodeInspector } from "@/components/code-inspector/CodeInspector";
import { QUERY_INPUT_ID } from "@/components/command-bar/CommandBar";
import { SearchStream } from "@/components/search-stream/SearchStream";
import { TopologyPanel } from "@/components/topology-graph/TopologyPanel";
import { parseRangeHash, rangeHash } from "@/lib/permalink";
import { useWorkspace, workspaceStore, type WorkspaceState } from "@/store/workspace";

/** Pure keyboard dispatcher (unit-tested); returns true when the key was handled. */
export function handleShortcut(
  e: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey">,
  typing: boolean,
  state: WorkspaceState,
  chord: { pendingG: boolean },
  focusInput: () => void,
): boolean {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    focusInput();
    return true;
  }
  if (e.key === "Escape") {
    if (state.shortcutsOpen) state.setShortcutsOpen(false);
    else if (state.popover) state.setPopover(null);
    else if (state.selection.kind !== "focus" || state.lineAnchor) state.select({ kind: "focus" });
    return true;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return false;
  if (chord.pendingG) {
    chord.pendingG = false;
    if (e.key === "d") {
      state.goToDefinition();
      return true;
    }
  }
  switch (e.key) {
    case "[":
      state.togglePanel("left");
      return true;
    case "]":
      state.togglePanel("right");
      return true;
    case "/":
      focusInput();
      return true;
    case "j":
      state.stepHit(1);
      return true;
    case "k":
      state.stepHit(-1);
      return true;
    case "?":
      state.setShortcutsOpen(!state.shortcutsOpen);
      return true;
    case "g":
      chord.pendingG = true;
      return true;
    default:
      return false;
  }
}

export function Workspace() {
  const focus = useWorkspace((s) => s.focus);
  const focusId = useWorkspace((s) => s.focusId);
  const lineAnchor = useWorkspace((s) => s.lineAnchor);
  const theme = useWorkspace((s) => s.theme);
  const chord = useRef({ pendingG: false });

  // Boot: theme, responsive panels, API health, and deep links (?symbol=…#L12-L18).
  useEffect(() => {
    const store = workspaceStore.getState();
    try {
      store.setTheme(localStorage.getItem("tracex-theme") === "light" ? "light" : "dark");
    } catch {
      /* storage unavailable */
    }
    if (window.matchMedia("(max-width: 960px)").matches) {
      store.togglePanel("left", false);
      store.togglePanel("right", false);
    }
    void store.init().then(() => {
      const symbol = new URLSearchParams(window.location.search).get("symbol");
      if (symbol && workspaceStore.getState().index) {
        void store.focusSymbol(symbol, { range: parseRangeHash(window.location.hash) });
      }
    });
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("tracex-theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);

  // Keep the URL shareable: ?symbol=<id>#L<start>-L<end>.
  useEffect(() => {
    if (!focusId) return;
    const url = new URL(window.location.href);
    url.searchParams.set("symbol", focusId);
    url.hash = lineAnchor ? rangeHash(lineAnchor) : "";
    window.history.replaceState(null, "", url);
  }, [focusId, lineAnchor]);

  useEffect(() => {
    const focusInput = () => {
      const input = document.getElementById(QUERY_INPUT_ID) as HTMLInputElement | null;
      input?.focus();
      input?.select();
    };
    const onKey = (e: KeyboardEvent) => {
      const active = document.activeElement;
      const typing = !!active && /^(INPUT|TEXTAREA)$/.test(active.tagName);
      if (e.key === "Escape" && typing) (active as HTMLElement).blur();
      if (handleShortcut(e, typing, workspaceStore.getState(), chord.current, focusInput)) {
        if (e.key !== "Escape" || !typing) e.preventDefault();
      }
    };
    // React's delegated listener also lives on `document` (Next.js hydrates the whole
    // document), so stopPropagation cannot shield popovers: detect them structurally.
    const onClick = (e: MouseEvent) => {
      if (!(e.target instanceof Element) || !e.target.closest("[data-popover]")) {
        workspaceStore.getState().setPopover(null);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onClick);
    };
  }, []);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <Header />
      <div className="flex-1 min-h-0 flex">
        <SearchStream />
        <main className="relative flex-1 min-w-0 flex flex-col bg-bg">
          {focus || focusId ? <CodeInspector /> : <IndexGate />}
          <Toast />
        </main>
        <TopologyPanel />
      </div>
      <StatusBar />
      <ShortcutsModal />
    </div>
  );
}
