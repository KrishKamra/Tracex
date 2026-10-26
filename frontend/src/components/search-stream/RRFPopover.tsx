"use client";

import { contributionBreakdown, justification, PILLARS } from "@/lib/rrf";
import type { SearchHit } from "@/lib/types";

/** Explains a hit's fused score: stacked RRF contribution bar plus per-pillar ranks. */
export function RRFPopover({ hit, open }: { hit: SearchHit; open: boolean }) {
  const parts = contributionBreakdown(hit);
  const color = Object.fromEntries(PILLARS.map((p) => [p.key, p.color]));
  const short = Object.fromEntries(PILLARS.map((p) => [p.key, p.short]));
  const filterOnly = hit.match_origin[0] === "filter";

  return (
    <div
      role="tooltip"
      data-open={open}
      className="pop glass absolute right-3 top-9 z-40 w-[268px] rounded-xl border border-line shadow-2xl shadow-black/40 p-3 text-[11.5px]"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[10.5px] font-medium uppercase tracking-[.08em] text-muted">RRF breakdown</span>
        <span className="font-mono text-ink">{filterOnly ? "filter" : hit.rrf_score.toFixed(4)}</span>
      </div>
      {!filterOnly && (
        <>
          <div className="mt-2 flex h-1.5 rounded-full overflow-hidden bg-line" aria-hidden="true">
            {parts.map((p) => (
              <span
                key={p.pillar}
                className="block h-full"
                style={{ width: `${p.share * 100}%`, background: `rgb(${color[p.pillar]})` }}
              />
            ))}
          </div>
          <div className="mt-2.5 grid grid-cols-[1fr_auto_auto] gap-x-3 gap-y-1 font-mono">
            {parts.map((p) => (
              <div key={p.pillar} className="contents">
                <span className="flex items-center gap-1.5 text-sub font-sans">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: `rgb(${color[p.pillar]})` }} />
                  {short[p.pillar]}
                </span>
                <span className="text-muted text-right">{p.rank ? `#${p.rank}` : "—"}</span>
                <span className="text-ink text-right">{p.value ? `${(p.share * 100).toFixed(0)}%` : "—"}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <ul className="mt-2.5 pt-2.5 border-t border-line flex flex-col gap-1 text-sub leading-snug">
        {justification(hit).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {!filterOnly && (
        <div className="mt-2 text-[10.5px] text-muted font-mono">Σ w·1/(60 + rank) over active pillars</div>
      )}
    </div>
  );
}
