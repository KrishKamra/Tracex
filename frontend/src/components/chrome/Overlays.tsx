"use client";

import { useEffect, useState } from "react";

import { useWorkspace, workspaceStore } from "@/store/workspace";

import { CloseIcon } from "./Icons";

export function Toast() {
  const toast = useWorkspace((s) => s.toast);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!toast) return;
    setOpen(true);
    const timer = setTimeout(() => setOpen(false), 2200);
    return () => clearTimeout(timer);
  }, [toast]);
  return (
    <div
      role="status"
      data-open={open}
      className="pop glass absolute left-1/2 -translate-x-1/2 bottom-5 z-20 px-3.5 py-2 rounded-lg border border-line font-mono text-[11.5px] text-ink shadow-xl shadow-black/30"
    >
      {toast?.message}
    </div>
  );
}

export const SHORTCUTS: [string[], string][] = [
  [["⌘", "K"], "Focus the command bar"],
  [["/"], "Focus the command bar"],
  [["j"], "Next result"],
  [["k"], "Previous result"],
  [["["], "Toggle results panel"],
  [["]"], "Toggle graph panel"],
  [["g", "d"], "Go to definition of the selected node / hovered call"],
  [["Click"], "Anchor a line number"],
  [["Shift", "Click"], "Select a line range (permalink)"],
  [["Esc"], "Close popovers · clear trace"],
  [["?"], "Show this help"],
];

export function ShortcutsModal() {
  const open = useWorkspace((s) => s.shortcutsOpen);
  const { setShortcutsOpen } = workspaceStore.getState();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShortcutsOpen(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        className="glass w-[420px] max-w-[calc(100vw-32px)] rounded-xl border border-line shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 h-11 border-b border-line">
          <span className="text-[12.5px] font-medium text-ink">Keyboard shortcuts</span>
          <button
            type="button"
            aria-label="Close"
            onClick={() => setShortcutsOpen(false)}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card"
          >
            <CloseIcon />
          </button>
        </div>
        <ul className="p-3 flex flex-col">
          {SHORTCUTS.map(([keys, label]) => (
            <li key={label + keys.join()} className="flex items-center justify-between gap-4 px-1 py-1.5 text-[12px]">
              <span className="text-sub">{label}</span>
              <span className="flex items-center gap-1">
                {keys.map((k) => (
                  <kbd key={k} className="h-5 min-w-5 px-1.5 inline-flex items-center justify-center rounded border border-line text-[10.5px] text-ink">
                    {k}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const EXAMPLES = ["give the customer their money back", "who calls the spending limit check", "@validate_signature", "/web/ format money"];

/** First-run state: connect / index a repository, then suggest example queries. */
export function IndexGate() {
  const health = useWorkspace((s) => s.health);
  const index = useWorkspace((s) => s.index);
  const indexing = useWorkspace((s) => s.indexing);
  const connectionError = useWorkspace((s) => s.connectionError);
  const { reindex, setQuery, runSearch } = workspaceStore.getState();
  const [path, setPath] = useState("");

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="w-[460px] max-w-full rounded-xl border border-line bg-panel p-6">
        {connectionError ? (
          <>
            <div className="text-[13px] font-medium text-ink">Backend unreachable</div>
            <p className="mt-2 text-[12.5px] leading-relaxed text-sub">{connectionError}</p>
            <pre className="mt-3 px-3 py-2 rounded-md bg-card/60 font-mono text-[11.5px] text-sub overflow-x-auto">
              cd backend{"\n"}uv run uvicorn app.api.main:app --port 8000
            </pre>
          </>
        ) : !index ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (path.trim()) void reindex(path.trim());
            }}
          >
            <div className="text-[13px] font-medium text-ink">Index a repository</div>
            <p className="mt-2 text-[12.5px] leading-relaxed text-sub">
              Tracex parses Python and TypeScript with tree-sitter, embeds every function and class, and builds the call
              graph. {health ? "" : "Connecting…"}
            </p>
            <div className="mt-4 flex gap-2">
              <input
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/absolute/path/to/repository"
                spellCheck={false}
                className="flex-1 min-w-0 h-8 px-3 rounded-lg border border-line bg-bg/60 font-mono text-[12px] outline-none focus:border-mint/40"
              />
              <button
                type="submit"
                disabled={indexing || !path.trim()}
                className="h-8 px-3 rounded-lg border border-mint/30 text-mint text-[12px] hover:bg-mint/10 disabled:opacity-50 transition-colors"
              >
                {indexing ? "Indexing…" : "Index"}
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="text-[13px] font-medium text-ink">Ready · {index.symbols} symbols indexed</div>
            <p className="mt-2 text-[12.5px] leading-relaxed text-sub">Try a question, or press ⌘K.</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {EXAMPLES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => {
                    setQuery(q);
                    void runSearch(q);
                  }}
                  className="h-7 px-2.5 rounded-md border border-line font-mono text-[11.5px] text-sub hover:text-ink hover:bg-card transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
