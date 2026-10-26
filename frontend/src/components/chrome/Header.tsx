"use client";

import { CommandBar } from "@/components/command-bar/CommandBar";
import { basename } from "@/lib/format";
import { useWorkspace, workspaceStore } from "@/store/workspace";

import { Logo, MoonIcon, SunIcon } from "./Icons";

export function Header() {
  const index = useWorkspace((s) => s.index);
  const busy = useWorkspace((s) => s.searching || s.focusLoading || s.indexing);
  const theme = useWorkspace((s) => s.theme);
  const { setTheme } = workspaceStore.getState();
  const repo = index ? basename(index.repository.replace(/[\\/]+$/, "").replace(/\\/g, "/")) : null;

  return (
    <header className="relative h-12 shrink-0 flex items-center gap-3 px-4 border-b border-line bg-panel">
      <div className="flex items-center gap-3 min-w-0 shrink-0">
        <div className="flex items-center gap-2">
          <Logo />
          <span className="font-semibold tracking-tight text-[14px]">Tracex</span>
        </div>
        {repo && (
          <span
            className="hidden sm:flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-line font-mono text-[11px] text-sub"
            title={index?.repository}
          >
            {repo}
            <span className="text-muted">/</span>
            <span className="text-ink/80">{index?.symbols} symbols</span>
          </span>
        )}
      </div>

      <div className="flex-1 flex justify-center min-w-0">
        <CommandBar />
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        <span className="hidden lg:flex items-center gap-1 text-[10.5px] text-muted mr-1" aria-hidden="true">
          <kbd className="h-5 min-w-5 px-1 inline-flex items-center justify-center rounded border border-line">[</kbd>
          <kbd className="h-5 min-w-5 px-1 inline-flex items-center justify-center rounded border border-line">]</kbd>
          <span className="ml-0.5">panels</span>
          <kbd className="ml-2 h-5 min-w-5 px-1 inline-flex items-center justify-center rounded border border-line">?</kbd>
        </span>
        <button
          type="button"
          aria-label="Toggle theme"
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          className="w-8 h-8 inline-flex items-center justify-center rounded-md text-sub hover:text-ink hover:bg-card transition-colors"
        >
          {theme === "light" ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
      {busy && <div className="absolute left-0 right-0 -bottom-px progress" />}
    </header>
  );
}
