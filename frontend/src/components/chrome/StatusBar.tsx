"use client";

import { ms, percent } from "@/lib/format";
import { useWorkspace, workspaceStore } from "@/store/workspace";

import { CloseIcon } from "./Icons";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1">
      <span className="text-sub">{k}</span>
      <span className="font-mono text-ink text-right truncate">{v}</span>
    </div>
  );
}

function Telemetry() {
  const results = useWorkspace((s) => s.results);
  const index = useWorkspace((s) => s.index);
  const focusId = useWorkspace((s) => s.focusId);
  const { setPopover } = workspaceStore.getState();
  const t = results?.timings;
  const stages: [string, number][] = t
    ? [
        ["Embeddings", t.embedding_ms + t.dense_ms],
        ["BM25", t.bm25_ms],
        ["AST graph", t.ast_graph_ms],
        ["RRF fusion", t.rrf_ms],
        ["Rerank", t.rerank_ms],
      ]
    : [];
  const max = Math.max(1e-6, ...stages.map(([, v]) => v));
  const active = results?.hits.find((h) => h.symbol_id === focusId) ?? results?.hits[0];

  return (
    <>
      <div className="flex items-center justify-between px-4 h-11 border-b border-line">
        <span className="text-[12.5px] font-medium text-ink">Index telemetry</span>
        <button
          type="button"
          aria-label="Close telemetry"
          onClick={() => setPopover(null)}
          className="w-7 h-7 inline-flex items-center justify-center rounded-md text-muted hover:text-ink hover:bg-card"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="p-4 flex flex-col gap-4 text-[12px] max-h-[70vh] overflow-y-auto scroll">
        <section>
          <div className="flex items-baseline justify-between mb-2">
            <span className="text-[10.5px] uppercase tracking-[.08em] text-muted">Retrieval latency</span>
            <span className="font-mono text-mint">{t ? ms(t.total_ms) : "no query yet"}</span>
          </div>
          {stages.map(([label, value]) => (
            <div key={label} className="flex items-center gap-3 py-1">
              <span className="w-24 text-sub">{label}</span>
              <span className="flex-1 h-1 rounded-full bg-line overflow-hidden">
                <span className="block h-full rounded-full bg-mint/70" style={{ width: `${Math.round((value / max) * 100)}%` }} />
              </span>
              <span className="w-14 text-right font-mono text-ink">{ms(value)}</span>
            </div>
          ))}
        </section>
        <section className="pt-3 border-t border-line">
          <div className="text-[10.5px] uppercase tracking-[.08em] text-muted mb-1.5">RRF</div>
          <Row k="k" v="60" />
          <Row k="Pillars" v={results?.pillars.join(" + ") || "—"} />
          <Row k="Fused hits" v={results ? `${results.hits.length} of ${results.candidates}` : "—"} />
          {active && <Row k="Active score" v={active.rrf_score.toFixed(4)} />}
          {active && (
            <Row
              k="Ranks (dense / bm25 / graph)"
              v={[active.dense_rank, active.bm25_rank, active.graph_rank].map((r) => (r ? `#${r}` : "—")).join(" / ")}
            />
          )}
        </section>
        {index && (
          <>
            <section className="pt-3 border-t border-line">
              <div className="text-[10.5px] uppercase tracking-[.08em] text-muted mb-1.5">Models</div>
              <Row k="Embedding" v={index.embedding_model.split("/").pop()} />
              <Row k="Reranker" v={index.reranker_model?.split("/").pop() ?? "off"} />
              <Row k="Device" v={index.device} />
            </section>
            <section className="pt-3 border-t border-line">
              <div className="text-[10.5px] uppercase tracking-[.08em] text-muted mb-1.5">Parsers</div>
              {Object.entries(index.parser_versions).map(([name, version]) => (
                <Row key={name} k={name} v={version} />
              ))}
            </section>
            <section className="pt-3 border-t border-line">
              <div className="text-[10.5px] uppercase tracking-[.08em] text-muted mb-1.5">Index</div>
              <Row k="Symbols" v={`${index.symbols.toLocaleString()} chunks`} />
              <Row k="Files" v={Object.entries(index.languages).map(([l, n]) => `${n} ${l}`).join(", ")} />
              <Row k="Graph edges" v={Object.entries(index.edges).map(([k, n]) => `${k} ${n}`).join(" · ")} />
              <Row k="Call resolution" v={percent(index.call_resolution_rate, 1)} />
              <Row k="Build" v={ms(index.duration_ms)} />
            </section>
          </>
        )}
      </div>
    </>
  );
}

export function StatusBar() {
  const index = useWorkspace((s) => s.index);
  const indexing = useWorkspace((s) => s.indexing);
  const connectionError = useWorkspace((s) => s.connectionError);
  const popover = useWorkspace((s) => s.popover);
  const focus = useWorkspace((s) => s.focus);
  const { setPopover } = workspaceStore.getState();
  const open = popover === "telemetry";

  const status = connectionError ? "API offline" : indexing ? "Indexing…" : index ? "Index Ready" : "Not indexed";
  const dot = connectionError ? "bg-[rgb(239_68_68)]" : index ? "bg-mint" : "bg-muted";

  return (
    <footer className="relative h-7 shrink-0 flex items-center px-3 border-t border-line bg-panel">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        data-popover
        onClick={() => setPopover(open ? null : "telemetry")}
        className="h-6 px-2 inline-flex items-center gap-2 rounded-md font-mono text-[11px] text-sub hover:text-ink hover:bg-card transition-colors"
      >
        <span className={`w-1.5 h-1.5 rounded-full ${dot} ${index ? "breathe" : ""}`} />
        {status}
        {index && (
          <>
            <span className="text-muted">•</span> {index.nodes.toLocaleString()} nodes
          </>
        )}
      </button>
      <span className="flex-1" />
      {focus && <span className="font-mono text-[11px] text-muted">{focus.language === "python" ? "Python" : "TypeScript"}</span>}
      <div
        className="pop glass absolute left-3 bottom-9 z-30 w-[360px] rounded-xl border border-line shadow-2xl shadow-black/40"
        role="dialog"
        aria-label="Index telemetry"
        data-open={open}
        data-popover
      >
        <Telemetry />
      </div>
    </footer>
  );
}
