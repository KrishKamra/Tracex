"""Generate docs/assets/tracex-typing.svg: a self-hosted typing animation for the README hero.

    python docs/scripts/build_typing_svg.py

Pure SVG + SMIL, no JavaScript and no external service, so it renders inside
GitHub's <img> sandbox. Each line is typed, held, then erased. Widths are pinned
with textLength, so the reveal is exact regardless of which monospace font the
viewer has. Colours adapt to the viewer's light / dark scheme.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

LINES = [
    "Tracex · AST-aware hybrid code search.",
    "tree-sitter chunks → BM25 + dense + call graph.",
    "Weighted RRF (k = 60) → cross-encoder rerank.",
    "NDCG@5 0.784 · +0.114 over BM25 · p_adj = 0.002.",
    "Ask in English. Land on the exact call site.",
]

WIDTH, HEIGHT = 920, 52
FONT_SIZE = 22
CHAR_W = FONT_SIZE * 0.6  # monospace advance; enforced via textLength
BASELINE = 34
TYPE_S, DELETE_S, HOLD_S, PAUSE_S = 0.055, 0.022, 1.9, 0.35
OUT = Path(__file__).resolve().parents[1] / "assets" / "tracex-typing.svg"


def timeline() -> tuple[list[tuple[float, int, int]], float]:
    """Discrete states (time, active line, visible chars)."""
    events: list[tuple[float, int, int]] = []
    t = 0.0
    for i, line in enumerate(LINES):
        n = len(line)
        for k in range(n + 1):
            events.append((t, i, k))
            t += TYPE_S
        t += HOLD_S - TYPE_S
        for k in range(n - 1, -1, -1):
            events.append((t, i, k))
            t += DELETE_S
        t += PAUSE_S
    return events, t


def dedupe(values: list[str], times: list[float]) -> tuple[list[str], list[float]]:
    out_v, out_t = [], []
    for v, t in zip(values, times, strict=True):
        if not out_v or out_v[-1] != v:
            out_v.append(v)
            out_t.append(t)
    return out_v, out_t


def x0(i: int) -> float:
    return (WIDTH - len(LINES[i]) * CHAR_W) / 2


def build() -> str:
    events, total = timeline()
    key = lambda ts: ";".join(f"{t / total:.5f}" for t in ts)  # noqa: E731
    parts = []
    for i in range(len(LINES)):
        widths = [f"{(k * CHAR_W if a == i else 0):.1f}" for _, a, k in events]
        vals, ts = dedupe(widths, [t for t, _, _ in events])
        parts.append(
            f'<clipPath id="c{i}"><rect x="{x0(i):.1f}" y="0" height="{HEIGHT}" width="0">'
            f'<animate attributeName="width" dur="{total:.3f}s" repeatCount="indefinite" calcMode="discrete" '
            f'values="{";".join(vals)}" keyTimes="{key(ts)}"/></rect></clipPath>'
        )
    texts = [
        f'<text class="t" x="{x0(i):.1f}" y="{BASELINE}" textLength="{len(line) * CHAR_W:.1f}" '
        f'lengthAdjust="spacingAndGlyphs" clip-path="url(#c{i})">{escape(line)}</text>'
        for i, line in enumerate(LINES)
    ]
    cursor_x = [f"{x0(a) + k * CHAR_W + 1:.1f}" for _, a, k in events]
    cx, cts = dedupe(cursor_x, [t for t, _, _ in events])
    cursor = (
        f'<rect class="cur" y="{BASELINE - FONT_SIZE + 3}" width="2.5" height="{FONT_SIZE + 2}" rx="1" x="{cx[0]}">'
        f'<animate attributeName="x" dur="{total:.3f}s" repeatCount="indefinite" calcMode="discrete" '
        f'values="{";".join(cx)}" keyTimes="{key(cts)}"/>'
        '<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1s" repeatCount="indefinite"/></rect>'
    )
    alt = " · ".join(LINES)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="{escape(alt)}">\n'
        f"<title>{escape(alt)}</title>\n"
        "<style>\n"
        "  .t { font: 500 22px 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; fill: #047857; }\n"
        "  .cur { fill: #0284C7; }\n"
        "  @media (prefers-color-scheme: dark) { .t { fill: #34D399; } .cur { fill: #38BDF8; } }\n"
        "</style>\n"
        f"<defs>{''.join(parts)}</defs>\n" + "\n".join(texts) + f"\n{cursor}\n</svg>\n"
    )


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KiB)")
