"""Render the benchmark figures in docs/assets/figures from the committed report.

    cd backend
    uv run --group docs python ../docs/scripts/make_figures.py

Every figure is drawn twice (light + dark), each against its own surface, and
embedded in Markdown with <picture> so it matches the reader's GitHub theme.
Statistics reuse app.evaluation.stats, the same code the benchmark runs.

Colour roles (validated with the dataviz palette checks, both modes):
  * categorical: one fixed hue per retrieval configuration, never re-ordered;
  * sequential: one blue ramp for heatmaps;
  * diverging: blue (win) / gray (tie) / red (loss).
Significance is encoded by marker fill (filled = Holm-significant), never by hue.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
# SVG text keeps weight 600 for browser fonts (Inter); the raster fallback lookup is irrelevant.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgb  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator, NullLocator  # noqa: E402

from app.evaluation.stats import bootstrap_ci  # noqa: E402
from app.parser import ASTEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "backend" / "eval" / "reports" / "billing_service.json"
DATASET = ROOT / "backend" / "eval" / "datasets" / "billing_service.json"
OUT = ROOT / "docs" / "assets" / "figures"

FONT_STACK = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"
SEED, RESAMPLES = 0, 10_000

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0f172a",
        "sub": "#475569",
        "muted": "#64748b",
        "grid": "#e2e8f0",
        "base": "#cbd5e1",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
        "seq": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
        "win": "#2a78d6",
        "tie": "#d6d4ce",
        "loss": "#e34948",
    },
    "dark": {
        "surface": "#0d121d",
        "ink": "#e2e8f0",
        "sub": "#94a3b8",
        "muted": "#64748b",
        "grid": "#1e293b",
        "base": "#334155",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
        "seq": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
        "win": "#3987e5",
        "tie": "#383835",
        "loss": "#e66767",
    },
}

# Entity -> fixed categorical slot (colour follows the system, in every figure).
SYSTEMS = [
    "BM25",
    "Dense",
    "Dense + BM25",
    "Dense + BM25 + Graph",
    "Full Tracex (+ Reranker)",
    "Full Tracex (+ Reranker) (CV-tuned)",
]
SHORT = dict(
    zip(
        SYSTEMS,
        ["BM25", "Dense", "Dense + BM25", "+ Graph", "Full (default w)", "Full (CV-tuned)"],
        strict=True,
    )
)
CATEGORIES = ["lexical", "semantic", "structural"]


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


def load():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    qids = [q["id"] for q in queries]
    per_query = {}
    for name, rows in report["per_query"].items():
        per_query[name] = {m: np.array([rows[q][m] for q in qids]) for m in ("MRR@5", "NDCG@5", "Recall@5")}
    for cv in report["cross_validation"]:
        rows = cv["per_query"]
        per_query[cv["name"]] = {
            m: np.array([rows[q][m] for q in qids]) for m in ("MRR@5", "NDCG@5", "Recall@5")
        }
    return report, dataset, queries, per_query


def paired_delta_ci(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """95% percentile bootstrap CI of mean(a - b), resampling queries jointly."""
    return bootstrap_ci(a - b, n_resamples=RESAMPLES, seed=SEED)


def win_tie_loss(a: np.ndarray, b: np.ndarray, eps: float = 1e-9) -> tuple[int, int, int]:
    d = a - b
    return int((d > eps).sum()), int((np.abs(d) <= eps).sum()), int((d < -eps).sum())


# --------------------------------------------------------------------------- #
# drawing helpers
# --------------------------------------------------------------------------- #


def setup(theme: dict) -> None:
    plt.rcParams.update(
        {
            "font.family": ["DejaVu Sans"],
            "font.size": 10,
            "svg.fonttype": "none",
            "svg.hashsalt": "tracex",
            "figure.facecolor": theme["surface"],
            "axes.facecolor": theme["surface"],
            "axes.edgecolor": theme["base"],
            "axes.labelcolor": theme["sub"],
            "axes.titlecolor": theme["ink"],
            "axes.titleweight": "semibold",
            "axes.titlesize": 11,
            "axes.titlelocation": "left",
            "axes.titlepad": 10,
            "axes.linewidth": 1,
            "xtick.color": theme["muted"],
            "ytick.color": theme["muted"],
            "xtick.labelcolor": theme["sub"],
            "ytick.labelcolor": theme["sub"],
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "grid.color": theme["grid"],
            "grid.linewidth": 1,
            "grid.linestyle": "-",
            "legend.frameon": False,
            "legend.labelcolor": theme["sub"],
            "text.color": theme["ink"],
        }
    )


def clean_axes(ax, grid_axis: str = "y", keep: tuple[str, ...] = ("bottom",)) -> None:
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)
    if grid_axis:
        ax.grid(axis=grid_axis)
    ax.set_axisbelow(True)


def rounded_columns(ax, xs, heights, width, color, theme, radius_px: float = 4) -> None:
    """Columns with a 4px rounded data-end and a square baseline (mark spec)."""
    fig = ax.figure
    fig.canvas.draw()
    to_px = ax.transData.transform
    px_per_x = abs(to_px((1, 0))[0] - to_px((0, 0))[0])
    px_per_y = abs(to_px((0, 1))[1] - to_px((0, 0))[1])
    rx = radius_px / px_per_x
    aspect = px_per_x / px_per_y
    for x, h in zip(xs, heights, strict=True):
        if h <= 0:
            continue
        ax.add_patch(
            FancyBboxPatch(
                (x - width / 2, 0),
                width,
                h,
                boxstyle=f"round,pad=0,rounding_size={rx}",
                mutation_aspect=aspect,
                facecolor=color,
                edgecolor="none",
                zorder=2,
            )
        )
        ax.add_patch(
            Rectangle(
                (x - width / 2, 0),
                width,
                min(h, rx * aspect * 1.05),
                facecolor=color,
                edgecolor="none",
                zorder=2,
            )
        )


def ink_on(fill: str, theme: dict) -> str:
    r, g, b = to_rgb(fill)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#0b0b0b" if lum > 0.5 else "#ffffff"


def save(fig, name: str, mode: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{mode}.svg"
    fig.savefig(
        path,
        format="svg",
        bbox_inches="tight",
        pad_inches=0.22,
        metadata={"Date": None, "Creator": "tracex docs"},
    )
    plt.close(fig)
    svg = path.read_text(encoding="utf-8")
    svg = re.sub(r"font-family:\s*[^;\"]+", f"font-family: {FONT_STACK}", svg)
    svg = re.sub(r"font:\s*([^;\"]*?)'DejaVu Sans'", rf"font: \1{FONT_STACK}", svg)
    path.write_text(svg, encoding="utf-8")


def legend_top(ax, handles_labels, ncol, theme):
    handles, labels = handles_labels
    ax.legend(
        handles,
        labels,
        ncol=ncol,
        loc="lower left",
        bbox_to_anchor=(0, 1.02),
        handlelength=0.9,
        handleheight=0.9,
        columnspacing=1.4,
        fontsize=9,
        borderaxespad=0.2,
    )


def swatch(color):
    return Rectangle((0, 0), 1, 1, facecolor=color, edgecolor="none")


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #


def fig_ablation(report, per_query, theme, mode):
    metrics = ["MRR@5", "NDCG@5", "Recall@5"]
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    clean_axes(ax)
    n = len(SYSTEMS)
    width, gap = 0.105, 0.03
    offsets = (np.arange(n) - (n - 1) / 2) * (width + gap)
    ax.set_xlim(-0.6, len(metrics) - 0.4)
    ax.set_ylim(0, 1.0)
    for i, system in enumerate(SYSTEMS):
        means = [per_query[system][m].mean() for m in metrics]
        xs = np.arange(len(metrics)) + offsets[i]
        rounded_columns(ax, xs, means, width, theme["series"][i], theme)
        for x, m in zip(xs, metrics, strict=True):
            lo, hi = bootstrap_ci(per_query[system][m], n_resamples=RESAMPLES, seed=SEED)
            ax.plot(
                [x, x],
                [lo, hi],
                color=theme["ink"],
                alpha=0.55,
                linewidth=1.2,
                zorder=3,
                solid_capstyle="round",
            )
        if system == "Full Tracex (+ Reranker) (CV-tuned)":
            ndcg_x = xs[1]
            ax.annotate(
                f"{means[1]:.3f}",
                (ndcg_x, means[1]),
                xytext=(0, 14),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color=theme["ink"],
                fontweight="semibold",
            )
    ax.set_xticks(range(len(metrics)), metrics)
    ax.set_yticks(np.linspace(0, 1, 6))
    ax.set_ylabel("Mean over 37 queries")
    legend_top(ax, ([swatch(c) for c in theme["series"]], [SHORT[s] for s in SYSTEMS]), 6, theme)
    ax.set_title("Retrieval effectiveness by configuration  ·  whiskers = 95% bootstrap CI", pad=34)
    save(fig, "fig1-ablation", mode)


def fig_category_heatmap(per_query, queries, theme, mode):
    cats = np.array([q["category"] for q in queries])
    data = np.array([[per_query[s]["NDCG@5"][cats == c].mean() for c in CATEGORIES] for s in SYSTEMS])
    cmap = LinearSegmentedColormap.from_list("seq", theme["seq"])
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    im = ax.imshow(data, cmap=cmap, vmin=0.4, vmax=1.0, aspect="auto")
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xticks(range(3), [f"{c}\n(n={int((cats == c).sum())})" for c in CATEGORIES])
    ax.set_yticks(range(len(SYSTEMS)), [SHORT[s] for s in SYSTEMS])
    ax.tick_params(axis="x", labeltop=True, labelbottom=False)
    ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(SYSTEMS), 1), minor=True)
    ax.grid(which="minor", color=theme["surface"], linewidth=2)
    ax.tick_params(which="minor", length=0)
    for i in range(len(SYSTEMS)):
        for j in range(3):
            fill = cmap((data[i, j] - 0.4) / 0.6)
            hexfill = matplotlib.colors.to_hex(fill)
            best = data[:, j].max() == data[i, j]
            ax.text(
                j,
                i,
                f"{data[i, j]:.3f}",
                ha="center",
                va="center",
                fontsize=9,
                color=ink_on(hexfill, theme),
                fontweight="semibold" if best else "normal",
            )
    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(colors=theme["muted"], labelcolor=theme["sub"], length=0)
    ax.set_title("NDCG@5 by query category  ·  bold = best in column", pad=12)
    save(fig, "fig2-category-heatmap", mode)
    return data


def fig_delta_forest(report, per_query, theme, mode):
    rows = SYSTEMS[1:]
    padj = {}
    for c in report["significance"]:
        padj[(c["system"], c["metric"])] = c["p_adjusted"]
    for c in report["cv_significance"]:
        if c["baseline"] == "BM25" and c["system"].startswith("Full"):
            padj[("Full Tracex (+ Reranker) (CV-tuned)", c["metric"])] = c["p_adjusted"]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5), sharey=True)
    stats = {}
    for ax, metric in zip(axes, ["NDCG@5", "MRR@5"], strict=True):
        clean_axes(ax, grid_axis="x", keep=())
        ax.axvline(0, color=theme["base"], linewidth=1, zorder=1)
        for r, system in enumerate(rows):
            color = theme["series"][SYSTEMS.index(system)]
            a, b = per_query[system][metric], per_query["BM25"][metric]
            delta = float((a - b).mean())
            lo, hi = paired_delta_ci(a, b)
            p = padj[(system, metric)]
            y = len(rows) - 1 - r
            ax.plot([lo, hi], [y, y], color=color, linewidth=2, solid_capstyle="round", zorder=2)
            ax.scatter(
                [delta],
                [y],
                s=64,
                zorder=3,
                linewidths=2,
                facecolors=color if p < 0.05 else theme["surface"],
                edgecolors=color,
            )
            ax.text(
                0.47,
                y,
                f"p_adj {p:.3f}" if p >= 0.001 else "p_adj <0.001",
                va="center",
                ha="left",
                fontsize=8.5,
                color=theme["ink"] if p < 0.05 else theme["muted"],
                fontweight="semibold" if p < 0.05 else "normal",
            )
            stats[(system, metric)] = (delta, lo, hi, p)
        ax.set_xlim(-0.3, 0.46)
        ax.set_title(f"Δ {metric} vs BM25", pad=10)
        ax.set_xlabel("Paired difference (95% bootstrap CI)")
    axes[0].set_yticks(range(len(rows)), [SHORT[s] for s in reversed(rows)])
    axes[0].set_ylim(-0.6, len(rows) - 0.4)
    fig.text(
        0.0,
        -0.06,
        "●  filled = significant after Holm–Bonferroni (p_adj < 0.05)      ○  hollow = not significant",
        fontsize=8.5,
        color=theme["sub"],
        transform=fig.transFigure,
    )
    fig.subplots_adjust(wspace=0.55)
    save(fig, "fig3-delta-forest", mode)
    return stats


def fig_win_loss(per_query, theme, mode):
    rows = SYSTEMS[1:]
    fig, ax = plt.subplots(figsize=(8.0, 3.2))
    clean_axes(ax, grid_axis="", keep=())
    counts = {}
    for r, system in enumerate(rows):
        w, t, l_ = win_tie_loss(per_query[system]["NDCG@5"], per_query["BM25"]["NDCG@5"])
        counts[system] = (w, t, l_)
        y = len(rows) - 1 - r
        left = 0
        for value, key in ((w, "win"), (t, "tie"), (l_, "loss")):
            if value:
                ax.barh(
                    y, value, left=left, height=0.5, color=theme[key], edgecolor=theme["surface"], linewidth=2
                )
                if value >= 3:
                    ax.text(
                        left + value / 2,
                        y,
                        str(value),
                        ha="center",
                        va="center",
                        fontsize=8.5,
                        color=ink_on(theme[key], theme),
                        fontweight="semibold",
                    )
            left += value
    ax.set_yticks(range(len(rows)), [SHORT[s] for s in reversed(rows)])
    ax.set_xlim(0, 37)
    ax.set_xticks([0, 10, 20, 30, 37])
    ax.set_xlabel("Queries (NDCG@5 compared with BM25 on the same query)")
    legend_top(
        ax,
        (
            [swatch(theme["win"]), swatch(theme["tie"]), swatch(theme["loss"])],
            ["better than BM25", "tie", "worse than BM25"],
        ),
        3,
        theme,
    )
    ax.set_title("Per-query wins, ties and losses against BM25", pad=30)
    save(fig, "fig4-win-tie-loss", mode)
    return counts


def fig_sensitivity(report, theme, mode):
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    clean_axes(ax)
    lines = {}
    for cv in report["cross_validation"]:
        base = cv["base"]
        color = theme["series"][SYSTEMS.index(base)]
        xs, ys = zip(*cv["sensitivity"], strict=True)
        ax.plot(xs, ys, color=color, linewidth=2, solid_joinstyle="round", zorder=2)
        ax.scatter(xs, ys, s=64, color=color, edgecolors=theme["surface"], linewidths=2, zorder=3)
        oof = cv["metrics"]["NDCG@5"]
        ax.axhline(oof, color=color, linewidth=1, alpha=0.6, zorder=1)
        full = base.startswith("Full")
        label = "Full (+ reranker)" if full else "Dense + BM25 + Graph"
        ax.annotate(
            label,
            (xs[-1], ys[-1]),
            xytext=(8, 9 if full else 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=theme["ink"],
        )
        ax.annotate(
            f"CV-tuned, out-of-fold {oof:.3f}",
            (0.77, oof),
            xytext=(0, -11),
            textcoords="offset points",
            ha="right",
            fontsize=8,
            color=theme["sub"],
        )
        lines[base] = list(zip(xs, ys, strict=True))
    ax.set_xlim(-0.02, 0.78)
    ax.set_ylim(0.55, 0.85)
    ax.set_xticks(np.round(np.arange(0, 0.65, 0.1), 1))
    ax.set_xlabel("Graph weight w_graph   (w_dense = w_bm25 = (1 − w_graph) / 2)")
    ax.set_ylabel("NDCG@5 (in-sample)")
    ax.set_title("Sensitivity to the graph pillar's RRF weight", pad=10)
    save(fig, "fig5-graph-sensitivity", mode)
    return lines


def fig_cv(report, theme, mode):
    cvs = report["cross_validation"]
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.4), gridspec_kw={"width_ratios": [1, 1, 1.15]})
    for ax, cv in zip(axes[:2], cvs, strict=True):
        clean_axes(ax, grid_axis="x", keep=())
        color = theme["series"][SYSTEMS.index(cv["base"])]
        freq = Counter(tuple(s["weights"][p] for p in ("dense", "bm25", "graph")) for s in cv["selections"])
        items = freq.most_common()
        labels = [f"({d:.1f}, {b:.1f}, {g:.1f})" for (d, b, g), _ in items]
        ys = np.arange(len(items))[::-1]
        ax.barh(ys, [c for _, c in items], height=0.32, color=color)
        ax.set_ylim(-0.7, max(len(items), 4) - 0.3)
        for y, (_, c) in zip(ys, items, strict=True):
            ax.text(c + 0.2, y, str(c), va="center", fontsize=8.5, color=theme["ink"])
        ax.set_yticks(ys, labels, fontfamily="monospace", fontsize=8.5)
        ax.set_xlim(0, 15)
        ax.set_xlabel("Folds selecting it (of 15)")
        short = "Full (+ reranker)" if cv["base"].startswith("Full") else "Dense + BM25 + Graph"
        ax.set_title(f"{short}\nweights chosen (dense, bm25, graph)", fontsize=10, pad=8)
    ax = axes[2]
    clean_axes(ax, grid_axis="both", keep=("bottom", "left"))
    ax.plot([0.4, 1.0], [0.4, 1.0], color=theme["base"], linewidth=1, zorder=1)
    for cv in cvs:
        color = theme["series"][SYSTEMS.index(cv["base"])]
        tr = [s["train_score"] for s in cv["selections"]]
        te = [s["test_score"] for s in cv["selections"]]
        ax.scatter(
            tr,
            te,
            s=52,
            color=color,
            edgecolors=theme["surface"],
            linewidths=2,
            zorder=3,
            label="Full (+ reranker)" if cv["base"].startswith("Full") else "Dense + BM25 + Graph",
        )
    ax.set_xlim(0.7, 0.86)
    ax.set_ylim(0.4, 0.95)
    ax.set_xlabel("NDCG@5 on training folds")
    ax.set_ylabel("NDCG@5 on held-out fold")
    ax.legend(loc="lower right", fontsize=8.5, handletextpad=0.3)
    ax.text(0.845, 0.875, "y = x", fontsize=8, color=theme["muted"], ha="right")
    ax.set_title("Train vs held-out per fold\n(3 × 5-fold stratified CV)", fontsize=10, pad=8)
    fig.subplots_adjust(wspace=0.55)
    save(fig, "fig6-cross-validation", mode)


def fig_per_query(per_query, queries, theme, mode):
    data = np.array([per_query[s]["NDCG@5"] for s in SYSTEMS]).T
    cmap = LinearSegmentedColormap.from_list("seq", theme["seq"])
    fig, ax = plt.subplots(figsize=(7.6, 10.4))
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for side in ax.spines.values():
        side.set_visible(False)
    labels = [f"{q['id']}  {q['query'][:44] + ('…' if len(q['query']) > 44 else '')}" for q in queries]
    ax.set_yticks(range(len(queries)), labels, fontsize=8)
    ax.set_xticks(range(len(SYSTEMS)), [SHORT[s] for s in SYSTEMS], rotation=30, ha="left", fontsize=8.5)
    ax.tick_params(axis="x", labeltop=True, labelbottom=False)
    ax.set_xticks(np.arange(-0.5, len(SYSTEMS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(queries), 1), minor=True)
    ax.grid(which="minor", color=theme["surface"], linewidth=1.5)
    ax.tick_params(which="minor", length=0)
    cats = [q["category"] for q in queries]
    for boundary in [i for i in range(1, len(cats)) if cats[i] != cats[i - 1]]:
        ax.axhline(boundary - 0.5, color=theme["surface"], linewidth=5)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, orientation="horizontal", location="bottom")
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(colors=theme["muted"], labelcolor=theme["sub"], length=0)
    cbar.set_label("NDCG@5 (0 = no relevant symbol in the top 5)", color=theme["sub"], fontsize=8.5)
    ax.set_title("NDCG@5 per query  ·  grouped: lexical, semantic, structural", pad=58)
    save(fig, "fig7-per-query", mode)


def fig_latency(report, theme, mode):
    rows = SYSTEMS[:5]
    fig, ax = plt.subplots(figsize=(7.6, 2.9))
    clean_axes(ax, grid_axis="x", keep=())
    color = theme["series"][0]
    for r, system in enumerate(rows):
        lat = report["latency_ms"][system]
        y = len(rows) - 1 - r
        ax.plot([lat["p50"], lat["p95"]], [y, y], color=color, linewidth=2, zorder=2, solid_capstyle="round")
        ax.scatter([lat["p50"]], [y], s=64, color=color, edgecolors=theme["surface"], linewidths=2, zorder=3)
        ax.scatter(
            [lat["p95"]], [y], s=64, facecolors=theme["surface"], edgecolors=color, linewidths=2, zorder=3
        )
        if system in ("BM25", "Full Tracex (+ Reranker)"):
            ax.annotate(
                f"p50 {lat['p50']:.1f} ms" if lat["p50"] >= 1 else f"p50 {lat['p50']:.2f} ms",
                (lat["p50"], y),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color=theme["ink"],
            )
    ax.set_xscale("log")
    ax.set_xlim(0.1, 5000)
    ax.xaxis.set_major_locator(FixedLocator([0.1, 1, 10, 100, 1000]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g} ms"))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_yticks(range(len(rows)), [SHORT[s] for s in reversed(rows)])
    ax.set_ylim(-0.6, len(rows) - 0.2)
    ax.set_xlabel("Latency per query, ms (log scale, CPU)   ●  p50     ○  p95")
    ax.set_title("End-to-end query latency", pad=10)
    save(fig, "fig8-latency", mode)


def fig_dataset(dataset, queries, theme, mode):
    corpus = (DATASET.parent / dataset["corpus"]).resolve()
    symbols = [s for f in ASTEngine().parse_repository(corpus) for s in f.symbols]
    by = Counter((("Python" if s.language == "python" else "TypeScript"), s.kind) for s in symbols)
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.0), gridspec_kw={"width_ratios": [1.4, 1, 1]})
    color = theme["series"][0]
    ax = axes[0]
    clean_axes(ax, grid_axis="x", keep=())
    keys = [(lang, kind) for lang in ("Python", "TypeScript") for kind in ("function", "method", "class")]
    ys = np.arange(len(keys))[::-1]
    vals = [by[k] for k in keys]
    ax.barh(ys, vals, height=0.5, color=color)
    for y, v in zip(ys, vals, strict=True):
        ax.text(v + 0.4, y, str(v), va="center", fontsize=8.5, color=theme["ink"])
    ax.set_yticks(ys, [f"{lang} · {kind}" for lang, kind in keys])
    ax.set_title(f"Corpus: {len(symbols)} AST chunks", fontsize=10, pad=8)
    ax = axes[1]
    clean_axes(ax, grid_axis="x", keep=())
    cats = Counter(q["category"] for q in queries)
    ys = np.arange(3)[::-1]
    vals = [cats[c] for c in CATEGORIES]
    ax.barh(ys, vals, height=0.32, color=color)
    for y, v in zip(ys, vals, strict=True):
        ax.text(v + 0.2, y, str(v), va="center", fontsize=8.5, color=theme["ink"])
    ax.set_yticks(ys, CATEGORIES)
    ax.set_ylim(-0.8, 2.8)
    ax.set_xlim(0, 16)
    ax.set_title(f"Queries: {len(queries)} by category", fontsize=10, pad=8)
    ax = axes[2]
    clean_axes(ax, grid_axis="y")
    sizes = Counter(len(q["relevant"]) for q in queries)
    xs = sorted(sizes)
    ax.set_xlim(min(xs) - 0.7, max(xs) + 0.7)
    ax.set_ylim(0, max(sizes.values()) * 1.25)
    rounded_columns(ax, xs, [sizes[x] for x in xs], 0.5, color, theme)
    ax.set_xticks(xs)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Relevant symbols per query")
    grades = Counter(g for q in queries for g in q["relevant"].values())
    ax.set_title(f"Judgements: {grades[2]} primary · {grades[1]} partial", fontsize=10, pad=8)
    fig.subplots_adjust(wspace=0.6)
    save(fig, "fig9-dataset", mode)
    return by, cats, sizes, grades


# --------------------------------------------------------------------------- #


def main() -> int:
    report, dataset, queries, per_query = load()
    summary = {}
    for mode, theme in THEMES.items():
        setup(theme)
        fig_ablation(report, per_query, theme, mode)
        heat = fig_category_heatmap(per_query, queries, theme, mode)
        forest = fig_delta_forest(report, per_query, theme, mode)
        wtl = fig_win_loss(per_query, theme, mode)
        fig_sensitivity(report, theme, mode)
        fig_cv(report, theme, mode)
        fig_per_query(per_query, queries, theme, mode)
        fig_latency(report, theme, mode)
        by, cats, sizes, grades = fig_dataset(dataset, queries, theme, mode)
        summary = {"heat": heat, "forest": forest, "wtl": wtl}

    print("## Paired deltas vs BM25 (95% bootstrap CI)")
    for (system, metric), (d, lo, hi, p) in summary["forest"].items():
        print(f"| {SHORT[system]} | {metric} | {d:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {p:.4f} |")
    print("## Win / tie / loss vs BM25 (NDCG@5)")
    for system, (w, t, l_) in summary["wtl"].items():
        print(f"| {SHORT[system]} | {w} | {t} | {l_} |")
    print("## Category heatmap")
    for system, row in zip(SYSTEMS, summary["heat"], strict=True):
        print(f"| {SHORT[system]} | " + " | ".join(f"{v:.3f}" for v in row) + " |")
    print("## Dataset", dict(by), dict(cats), dict(sorted(sizes.items())), dict(grades))
    for name, rows in per_query.items():
        if name in SYSTEMS:
            ci = {
                m: bootstrap_ci(rows[m], n_resamples=RESAMPLES, seed=SEED)
                for m in ("MRR@5", "NDCG@5", "Recall@5")
            }
            print(
                "CI",
                SHORT[name],
                {m: (round(rows[m].mean(), 3), round(lo, 3), round(hi, 3)) for m, (lo, hi) in ci.items()},
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
