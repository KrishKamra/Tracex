"""Cross-encoder reranking of fused candidates.

A bi-encoder embeds query and chunk independently. A cross-encoder instead
reads the concatenation Q (+) Serialize(d) jointly, so every query token can
attend to every code token:

    f_cross(Q (+) Serialize(d)) = sigma(logit) in [0, 1]

It is far more expensive (one forward pass per pair), so it rescores only the
top fused candidates.

Note: the default ``ms-marco-MiniLM`` model was trained on natural-language
web passages, not code. Whether it helps on code is an empirical question,
and the benchmark's "+ Reranker" ablation answers it.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np

from app.nlp.embeddings import detect_device

DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderBackend(Protocol):
    def predict(self, sentences: list[tuple[str, str]], **kwargs: Any) -> Any: ...


RerankerLoader = Callable[[str, str, int], CrossEncoderBackend]


def cross_encoder_loader(model_name: str, device: str, max_length: int) -> CrossEncoderBackend:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device=device, max_length=max_length)


def _identity(x: Any) -> Any:
    return x


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER,
        *,
        device: str | None = None,
        batch_size: int = 16,
        max_length: int = 512,
        cache_size: int = 50_000,
        loader: RerankerLoader = cross_encoder_loader,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._device = device
        self._loader = loader
        self._model: CrossEncoderBackend | None = None
        self.cache_size = cache_size
        self._cache: OrderedDict[str, float] = OrderedDict()

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = detect_device()
        return self._device

    @property
    def model(self) -> CrossEncoderBackend:
        if self._model is None:
            self._model = self._loader(self.model_name, self.device, self.max_length)
        return self._model

    @staticmethod
    def _key(query: str, text: str) -> str:
        return hashlib.sha256(f"{query}\0{text}".encode()).hexdigest()

    def score(self, query: str, texts: Sequence[str]) -> np.ndarray:
        """Relevance probabilities in [0, 1], aligned with ``texts``.

        Pair scores are cached (LRU), so rescoring the same candidates under
        different fusion weights, as weight tuning does, costs no extra passes.
        """
        if not texts:
            return np.zeros(0, dtype=np.float32)
        keys = [self._key(query, t) for t in texts]
        missing: dict[str, int] = {}  # key -> first index, so duplicate texts are scored once
        for index, key in enumerate(keys):
            if key not in self._cache:
                missing.setdefault(key, index)
        fresh: dict[str, float] = {}
        if missing:
            logits = self.model.predict(
                [(query, texts[i]) for i in missing.values()],
                batch_size=self.batch_size,
                activation_fn=_identity,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            logits = np.asarray(logits, dtype=np.float64).reshape(len(missing), -1)[:, -1]
            probabilities = 1.0 / (1.0 + np.exp(-logits))
            fresh = {key: float(prob) for key, prob in zip(missing, probabilities, strict=True)}
        scores = []
        for key in keys:
            if key in fresh:
                scores.append(fresh[key])
            else:
                scores.append(self._cache[key])
                self._cache.move_to_end(key)
        if self.cache_size > 0:
            self._cache.update(fresh)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return np.asarray(scores, dtype=np.float32)

    def clear_cache(self) -> None:
        self._cache.clear()

    def warm_up(self) -> None:
        """Load the model and run one forward pass, outside any request's latency budget."""
        self.score("warm up", ["def warm_up(): pass"])
        self.clear_cache()

    def rerank(self, query: str, candidates: Sequence[tuple[str, str]]) -> list[tuple[str, float]]:
        """Reorder ``(doc_id, text)`` candidates by cross-encoder score (stable on ties)."""
        scores = self.score(query, [text for _, text in candidates])
        order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        return [(candidates[i][0], float(scores[i])) for i in order]
