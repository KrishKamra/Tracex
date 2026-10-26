"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { CallersIcon, GraphIcon, LinkIcon } from "@/components/chrome/Icons";
import { basename, dirname } from "@/lib/format";
import { plainTokenize, tokenize, type CodeLine } from "@/lib/highlighter";
import { permalink, rangeLabel, type LineRange } from "@/lib/permalink";
import type { CallSite, SymbolDetail } from "@/lib/types";
import { currentHighlight, useWorkspace, workspaceStore } from "@/store/workspace";

export const LINE_H = 24;
export const PAD_TOP = 24;

interface TokenInfo {
  title: string;
  detail: string;
  target: string | null;
}

/** What hovering an identifier on a given line should explain, if anything. */
export function describeToken(
  focus: SymbolDetail,
  line: number,
  text: string,
  sitesByLine: Map<number, CallSite[]>,
): TokenInfo | null {
  const site = sitesByLine
    .get(line)
    ?.find((s) => s.callee.split(".").pop()?.replace(/\(\)$/, "") === text);
  if (site) {
    return site.target_id
      ? { title: `calls ${site.target_id.split("::")[1]}`, detail: `${site.target_id.split("::")[0]} · g d to open`, target: site.target_id }
      : { title: `calls ${site.callee}`, detail: "external or unresolved (builtin / third-party)", target: null };
  }
  const { start_line, end_line } = focus.highlight;
  if (line < start_line || line > end_line) return null;
  const param = focus.scope.params.find((p) => p.name.replace(/^\*+/, "") === text);
  if (param) {
    const annotation = param.annotation ? `: ${param.annotation}` : "";
    const fallback = param.default ? ` = ${param.default}` : "";
    return { title: `parameter ${param.name}${annotation}${fallback}`, detail: focus.qualified_name, target: null };
  }
  if (focus.scope.locals.includes(text)) return { title: `local ${text}`, detail: `assigned in ${focus.name}`, target: null };
  if (text === focus.name && line <= start_line + focus.decorators.length) {
    return {
      title: `${focus.kind} ${focus.qualified_name}`,
      detail: `${focus.fan_in} callers · ${focus.fan_out} callees`,
      target: null,
    };
  }
  return null;
}

export function CodeInspector() {
  const focus = useWorkspace((s) => s.focus);
  const focusLoading = useWorkspace((s) => s.focusLoading);
  const selection = useWorkspace((s) => s.selection);
  const lineAnchor = useWorkspace((s) => s.lineAnchor);
  const graph = useWorkspace((s) => s.graph);
  const highlight = useMemo(
    () => currentHighlight({ focus, selection, lineAnchor, graph }),
    [focus, selection, lineAnchor, graph],
  );
  const { anchorLine, togglePanel, setTab, select, showToast, setHoverTarget } = workspaceStore.getState();

  const [lines, setLines] = useState<CodeLine[]>([]);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; info: TokenInfo } | null>(null);
  const [peek, setPeek] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const shownFile = useRef<string | null>(null);

  const source = focus?.file.source ?? "";
  const language = focus?.file.language ?? "python";
  useEffect(() => {
    let cancelled = false;
    setLines(plainTokenize(source));
    tokenize(source, language)
      .then((tokens) => !cancelled && setLines(tokens))
      .catch(() => {
        /* keep plain rendering */
      });
    return () => {
      cancelled = true;
    };
  }, [source, language]);

  const sitesByLine = useMemo(() => {
    const map = new Map<number, CallSite[]>();
    for (const site of focus?.call_sites ?? []) map.set(site.line, [...(map.get(site.line) ?? []), site]);
    return map;
  }, [focus]);

  const ranges: LineRange[] = highlight?.ranges ?? [];
  const first = ranges[0];
  const last = ranges[ranges.length - 1];
  const span: LineRange | null = first && last ? [first[0], last[1]] : null;
  const onLine = (n: number) => ranges.some(([a, b]) => n >= a && n <= b);

  // Glide within a file; jump when the file changes.
  useEffect(() => {
    if (!span || !scrollRef.current) return;
    const sameFile = shownFile.current === focus?.file_path;
    shownFile.current = focus?.file_path ?? null;
    const top = PAD_TOP + (span[0] - 1) * LINE_H;
    scrollRef.current.scrollTo({ top: Math.max(0, top - 140), behavior: sameFile ? "smooth" : "auto" });
    setPeek(true);
    const timer = setTimeout(() => setPeek(false), 1600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.symbol_id, span?.[0], span?.[1]]);

  if (!focus) {
    return (
      <div className="flex-1 flex items-center justify-center text-[12.5px] text-muted">
        {focusLoading ? "Opening symbol…" : "Run a search to open a symbol."}
      </div>
    );
  }

  const dirs = dirname(focus.file_path);
  const scopeParts = focus.qualified_name.split(".");
  const pillTop = span
    ? (() => {
        const top = PAD_TOP + (span[0] - 1) * LINE_H;
        return top - 44 < 4 ? top + (span[1] - span[0] + 1) * LINE_H + 10 : top - 44;
      })()
    : 0;

  const copyLink = () => {
    if (!span) return;
    const link = permalink(window.location.origin, focus.symbol_id, span);
    navigator.clipboard?.writeText(link).catch(() => undefined);
    showToast(`Link copied · ${basename(focus.file_path)}#L${span[0]}${span[1] !== span[0] ? `-L${span[1]}` : ""}`);
  };
  const findCallers = () => {
    togglePanel("right", true);
    setTab("deps");
    const firstCaller = graph?.nodes.find((n) => n.data.role === "caller" && n.data.depth === -1);
    if (firstCaller) select({ kind: "caller", id: firstCaller.id });
    showToast(`${focus.fan_in} caller${focus.fan_in === 1 ? "" : "s"}`);
  };
  const openGraph = () => {
    togglePanel("right", true);
    setTab("graph");
  };

  return (
    <>
      <div className="h-11 shrink-0 flex items-center gap-3 px-5 border-b border-line">
        <nav aria-label="Symbol path" className="flex-1 min-w-0 flex items-center gap-1.5 font-mono text-[12px] truncate">
          {dirs.length > 0 && <span className="text-muted truncate">{dirs.join(" / ")}</span>}
          {dirs.length > 0 && <span className="text-muted/50">/</span>}
          <span className="text-sub">{basename(focus.file_path)}</span>
          {scopeParts.map((part, i) => (
            <Fragment key={i}>
              <span className="text-muted/60">›</span>
              <span className={i === scopeParts.length - 1 ? "text-mint" : "text-sub"}>
                {part}
                {i === scopeParts.length - 1 && focus.kind !== "class" ? "()" : ""}
              </span>
            </Fragment>
          ))}
        </nav>
        {span && (
          <span className="font-mono text-[11px] text-muted whitespace-nowrap">
            {rangeLabel(span)}
            {highlight?.traced ? " · traced" : lineAnchor ? " · anchored" : ""}
          </span>
        )}
      </div>
      <div ref={scrollRef} className="code-wrap scroll relative flex-1 min-h-0 overflow-auto">
        <div ref={innerRef} className="relative min-w-max pt-6 pb-40 font-mono text-[12.5px]">
          {ranges.map(([a, b], i) => (
            <div
              key={i}
              className={`hl-band ${highlight?.traced ? "trace" : ""}`}
              style={{ top: PAD_TOP + (a - 1) * LINE_H - 2, height: (b - a + 1) * LINE_H + 4 }}
            />
          ))}
          <div key={focus.file_path} className="code-fade">
            {lines.map((tokens, i) => {
              const n = i + 1;
              const on = onLine(n);
              return (
                <div key={n} className={`code-line ${on ? "on" : ""} ${on && highlight?.traced ? "trace" : ""}`}>
                  <span
                    className="num"
                    role="button"
                    tabIndex={-1}
                    title="Click to anchor · Shift+Click to select a range"
                    onClick={(e) => anchorLine(n, e.shiftKey)}
                  >
                    {n}
                  </span>
                  <span className="src">
                    {tokens.map((t, j) => {
                      const info = t.identifier ? describeToken(focus, n, t.text, sitesByLine) : null;
                      if (!info) return t.cls ? <span key={j} className={t.cls}>{t.text}</span> : <Fragment key={j}>{t.text}</Fragment>;
                      return (
                        <span
                          key={j}
                          className={`${t.cls ?? ""} ident-link`}
                          onMouseEnter={(e) => {
                            const host = innerRef.current?.getBoundingClientRect();
                            const rect = e.currentTarget.getBoundingClientRect();
                            if (host) setTooltip({ x: rect.left - host.left, y: rect.bottom - host.top + 6, info });
                            setHoverTarget(info.target);
                          }}
                          onMouseLeave={() => setTooltip(null)}
                        >
                          {t.text}
                        </span>
                      );
                    })}
                  </span>
                </div>
              );
            })}
          </div>

          {tooltip && (
            <div
              role="tooltip"
              className="glass absolute z-20 max-w-[420px] px-3 py-2 rounded-lg border border-line shadow-xl shadow-black/30 pointer-events-none"
              style={{ left: tooltip.x, top: tooltip.y }}
            >
              <div className="text-[12px] text-ink">{tooltip.info.title}</div>
              <div className="text-[11px] text-muted">{tooltip.info.detail}</div>
            </div>
          )}

          <div
            className={`hover-pill glass absolute z-10 left-[84px] flex items-center gap-0.5 p-1 rounded-full border border-line shadow-xl shadow-black/30 ${peek ? "peek" : ""}`}
            style={{ top: pillTop }}
            role="toolbar"
            aria-label="Symbol actions"
          >
            <PillButton onClick={copyLink} icon={<LinkIcon />} label="Copy Link" />
            <PillButton onClick={findCallers} icon={<CallersIcon />} label="Find Callers" />
            <PillButton onClick={openGraph} icon={<GraphIcon />} label="Open Graph" />
          </div>
        </div>
      </div>
    </>
  );
}

function PillButton({ onClick, icon, label }: { onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-7 px-3 inline-flex items-center gap-1.5 rounded-full text-[11.5px] text-sub hover:text-ink hover:bg-card transition-colors"
    >
      {icon}
      {label}
    </button>
  );
}
