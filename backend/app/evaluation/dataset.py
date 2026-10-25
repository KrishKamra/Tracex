"""Gold-standard query sets with graded relevance judgements.

Dataset JSON format::

    {
      "name": "billing_service",
      "description": "...",
      "corpus": "../corpora/billing_service",      # relative to this file
      "grades": {"2": "primary answer", "1": "partially relevant"},
      "queries": [
        {"id": "lex-01", "category": "lexical", "query": "check_limit",
         "relevant": {"billing/limits.py::check_limit": 2}}
      ]
    }

Judgements reference ``symbol_id`` values, so every dataset is validated
against the parsed corpus. A renamed or moved symbol fails loudly instead of
silently deflating every metric.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    text: str
    category: str
    qrels: Mapping[str, int]


@dataclass(frozen=True)
class EvalDataset:
    name: str
    description: str
    corpus_root: Path
    queries: tuple[EvalQuery, ...]

    @property
    def qrels(self) -> dict[str, Mapping[str, int]]:
        return {q.query_id: q.qrels for q in self.queries}

    @property
    def categories(self) -> list[str]:
        return list(dict.fromkeys(q.category for q in self.queries))


def load_dataset(path: str | os.PathLike[str]) -> EvalDataset:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = tuple(
        EvalQuery(
            query_id=q["id"],
            text=q["query"],
            category=q.get("category", "uncategorized"),
            qrels={doc: int(grade) for doc, grade in q["relevant"].items()},
        )
        for q in raw["queries"]
    )
    dataset = EvalDataset(
        name=raw["name"],
        description=raw.get("description", ""),
        corpus_root=(path.parent / raw["corpus"]).resolve(),
        queries=queries,
    )
    _check_structure(dataset)
    return dataset


def _check_structure(dataset: EvalDataset) -> None:
    ids = [q.query_id for q in dataset.queries]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate query ids: {duplicates}")
    for q in dataset.queries:
        if not any(g > 0 for g in q.qrels.values()):
            raise ValueError(f"query {q.query_id} has no relevant documents")
        if any(g < 0 for g in q.qrels.values()):
            raise ValueError(f"query {q.query_id} has a negative grade")


def validate_against_corpus(dataset: EvalDataset, symbol_ids: Iterable[str]) -> None:
    known = set(symbol_ids)
    missing = sorted({(q.query_id, d) for q in dataset.queries for d in q.qrels if d not in known})
    if missing:
        listing = "\n".join(f"  {qid}: {doc}" for qid, doc in missing)
        raise ValueError(f"dataset {dataset.name!r} references unknown symbols:\n{listing}")
