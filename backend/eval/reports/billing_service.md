# Tracex Retrieval Benchmark: `billing_service`

Hand-labeled code search queries over a multi-file Python billing backend and TypeScript/React web client. Categories: lexical (identifier-bearing queries), semantic (paraphrases with little identifier overlap), structural (questions about call relationships and data flow).

- **Queries:** 37 (lexical: 12, semantic: 13, structural: 12); **judgements:** 85
- **Corpus:** 12 files, 65 AST chunks
- **Embedding model:** `jinaai/jina-embeddings-v2-base-code`; **reranker:** `cross-encoder/ms-marco-MiniLM-L-6-v2`; **device:** `cpu`
- **Generated:** 2026-10-25 22:04 UTC

## Effectiveness (mean over 37 queries)

Best value per column in **bold**.

| Configuration | MRR@5 | NDCG@5 | Recall@5 | P@5 | MAP@5 | Hit@1 | Recall@10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | 0.789 | 0.670 | 0.715 | 0.286 | 0.612 | 0.676 | 0.822 |
| Dense | 0.845 | 0.766 | **0.791** | **0.330** | 0.698 | 0.784 | **0.909** |
| Dense + BM25 | 0.864 | 0.748 | 0.790 | **0.330** | 0.694 | 0.811 | 0.897 |
| Dense + BM25 + Graph | 0.764 | 0.690 | 0.737 | **0.330** | 0.628 | 0.676 | 0.893 |
| Full Tracex (+ Reranker) | **0.909** | **0.796** | 0.790 | 0.324 | **0.715** | **0.865** | 0.875 |

## 95% bootstrap confidence intervals

| Configuration | MRR@5 | NDCG@5 | Recall@5 |
| --- | --- | --- | --- |
| BM25 | 0.789 [0.681, 0.887] | 0.670 [0.562, 0.773] | 0.715 [0.610, 0.814] |
| Dense | 0.845 [0.742, 0.939] | 0.766 [0.672, 0.853] | 0.791 [0.692, 0.884] |
| Dense + BM25 | 0.864 [0.766, 0.951] | 0.748 [0.649, 0.843] | 0.790 [0.696, 0.877] |
| Dense + BM25 + Graph | 0.764 [0.642, 0.876] | 0.690 [0.577, 0.798] | 0.737 [0.625, 0.844] |
| Full Tracex (+ Reranker) | 0.909 [0.826, 0.978] | 0.796 [0.714, 0.873] | 0.790 [0.700, 0.874] |

## Significance vs. `BM25`

Paired approximate randomization test (two-sided), Holm-Bonferroni adjusted across all comparisons below; `*` marks p_adj < 0.05.

| Configuration | Metric | Δ vs BM25 | p | p_adj |  |
| --- | --- | --- | --- | --- | --- |
| Dense | MRR@5 | +0.056 | 0.3655 | 1.0000 |  |
| Dense | NDCG@5 | +0.096 | 0.0336 | 0.1680 |  |
| Dense + BM25 | MRR@5 | +0.075 | 0.0692 | 0.2768 |  |
| Dense + BM25 | NDCG@5 | +0.078 | 0.0112 | 0.0672 |  |
| Dense + BM25 + Graph | MRR@5 | -0.025 | 0.7205 | 1.0000 |  |
| Dense + BM25 + Graph | NDCG@5 | +0.020 | 0.7358 | 1.0000 |  |
| Full Tracex (+ Reranker) | MRR@5 | +0.120 | 0.0011 | 0.0077 | * |
| Full Tracex (+ Reranker) | NDCG@5 | +0.126 | 0.0001 | 0.0008 | * |

## NDCG@5 by query category

| Configuration | lexical (n=12) | semantic (n=13) | structural (n=12) |
| --- | --- | --- | --- |
| BM25 | 0.957 | 0.570 | 0.492 |
| Dense | 0.975 | 0.720 | 0.606 |
| Dense + BM25 | 0.971 | 0.709 | 0.567 |
| Dense + BM25 + Graph | 0.839 | 0.576 | 0.666 |
| Full Tracex (+ Reranker) | 1.000 | 0.727 | 0.667 |

## Cross-validated fusion weights

RRF weights (w_dense, w_bm25, w_graph) were selected by 3× repeated, category-stratified 5-fold cross-validation over a 65-point simplex grid (step 0.1), maximizing NDCG@5 on the training folds. Every query below is scored **only** by weights chosen without it (out-of-fold, averaged over repeats). Ties break toward the default (0.4, 0.4, 0.2).

| System | MRR@5 | NDCG@5 | Recall@5 |
| --- | --- | --- | --- |
| Dense + BM25 + Graph (default weights) | 0.764 [0.642, 0.876] | 0.690 [0.577, 0.798] | 0.737 [0.625, 0.844] |
| Dense + BM25 + Graph (CV-tuned) | 0.800 [0.690, 0.899] | 0.729 [0.631, 0.819] | 0.803 [0.700, 0.896] |
| Full Tracex (+ Reranker) (default weights) | 0.909 [0.826, 0.978] | 0.796 [0.714, 0.873] | 0.790 [0.700, 0.874] |
| Full Tracex (+ Reranker) (CV-tuned) | 0.897 [0.809, 0.968] | 0.784 [0.699, 0.864] | 0.775 [0.679, 0.863] |

Paired randomization tests, Holm-Bonferroni adjusted within this family; `*` marks p_adj < 0.05.

| System | vs | Metric | Δ | p | p_adj |  |
| --- | --- | --- | --- | --- | --- | --- |
| Dense + BM25 + Graph (CV-tuned) | BM25 | MRR@5 | +0.011 | 0.8541 | 1.0000 |  |
| Dense + BM25 + Graph (CV-tuned) | BM25 | NDCG@5 | +0.059 | 0.2145 | 1.0000 |  |
| Dense + BM25 + Graph (CV-tuned) | Dense + BM25 + Graph | MRR@5 | +0.036 | 0.2577 | 1.0000 |  |
| Dense + BM25 + Graph (CV-tuned) | Dense + BM25 + Graph | NDCG@5 | +0.038 | 0.2403 | 1.0000 |  |
| Full Tracex (+ Reranker) (CV-tuned) | BM25 | MRR@5 | +0.108 | 0.0066 | 0.0462 | * |
| Full Tracex (+ Reranker) (CV-tuned) | BM25 | NDCG@5 | +0.114 | 0.0002 | 0.0016 | * |
| Full Tracex (+ Reranker) (CV-tuned) | Full Tracex (+ Reranker) | MRR@5 | -0.013 | 0.2544 | 1.0000 |  |
| Full Tracex (+ Reranker) (CV-tuned) | Full Tracex (+ Reranker) | NDCG@5 | -0.012 | 0.1243 | 0.7457 |  |

### Weights selected across folds

Stable selections across folds indicate the optimum reflects the task, not one lucky split.

| System | (dense, bm25, graph) | Chosen | Train NDCG@5 | Held-out NDCG@5 |
| --- | --- | --- | --- | --- |
| Dense + BM25 + Graph (CV-tuned) | (0.9, 0.1, 0.0) | 7/15 | 0.769 | 0.777 |
| Dense + BM25 + Graph (CV-tuned) | (0.8, 0.1, 0.1) | 5/15 | 0.797 | 0.595 |
| Dense + BM25 + Graph (CV-tuned) | (1.0, 0.0, 0.0) | 3/15 | 0.754 | 0.809 |
| Full Tracex (+ Reranker) (CV-tuned) | (0.7, 0.1, 0.2) | 11/15 | 0.795 | 0.820 |
| Full Tracex (+ Reranker) (CV-tuned) | (0.6, 0.1, 0.3) | 1/15 | 0.816 | 0.560 |
| Full Tracex (+ Reranker) (CV-tuned) | (0.0, 0.7, 0.3) | 1/15 | 0.821 | 0.710 |
| Full Tracex (+ Reranker) (CV-tuned) | (0.9, 0.1, 0.0) | 1/15 | 0.827 | 0.686 |
| Full Tracex (+ Reranker) (CV-tuned) | (0.4, 0.2, 0.4) | 1/15 | 0.803 | 0.765 |

### Sensitivity of NDCG@5 to the graph weight (w_dense = w_bm25)

> [!NOTE]
> Descriptive, in-sample curve over all queries: it shows the shape of the trade-off and is
> **not** an unbiased estimate. The cross-validated rows above are the reportable numbers.

| w_graph | Dense + BM25 + Graph | Full Tracex (+ Reranker) |
| --- | --- | --- |
| 0.0 | 0.752 | 0.796 |
| 0.1 | 0.729 | 0.796 |
| 0.2 | 0.690 | 0.796 |
| 0.3 | 0.663 | 0.796 |
| 0.4 | 0.653 | 0.800 |
| 0.5 | 0.631 | 0.784 |
| 0.6 | 0.606 | 0.786 |

In-sample optimum (optimistic upper bound, for reference only):

- `Dense + BM25 + Graph`: (0.9, 0.1, 0.0) → NDCG@5 0.771
- `Full Tracex (+ Reranker)`: (0.7, 0.1, 0.2) → NDCG@5 0.800

## Latency per query (ms)

| Configuration | p50 | p95 | mean |
| --- | --- | --- | --- |
| BM25 | 0.2 | 0.3 | 0.2 |
| Dense | 26.9 | 37.1 | 28.1 |
| Dense + BM25 | 52.0 | 84.2 | 55.6 |
| Dense + BM25 + Graph | 57.4 | 91.5 | 63.8 |
| Full Tracex (+ Reranker) | 891.2 | 1513.3 | 994.3 |

## Index

| Property | Value |
| --- | --- |
| AST chunks | 65 |
| Graph edges | CALLS: 51, IMPORTS: 17 |
| Call resolution | 51/140 (36.4%); unresolved calls are mostly builtins and third-party APIs |
| Index build (ms) | bm25_index_ms: 4, embedding_index_ms: 35352, graph_build_ms: 5 |
