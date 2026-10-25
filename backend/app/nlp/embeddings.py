"""Dense bi-encoder embeddings for the semantic pillar.

Queries Q and serialized chunks c_i are projected into a shared latent space
by a code-pretrained Transformer encoder E_theta and compared by cosine
similarity:

    Score_Dense(c_i, Q) = E(Q)^T E(c_i) / (||E(Q)||_2 * ||E(c_i)||_2)

Vectors are L2-normalized here, so downstream retrieval reduces cosine
similarity to a plain dot product.

Determinism: texts are deduplicated, ordered by (descending length, first
occurrence) and cut into fixed-size batches before encoding, so the batches
sent to the model depend only on the input set, never on caller batching.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol

import numpy as np

from app.nlp.serializer import serialize_chunk
from app.parser.ast_engine import SymbolNode

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"
FALLBACK_MODELS: tuple[str, ...] = ("BAAI/bge-m3",)
# Small (~90 MB) general-purpose model for fast CPU CI runs.
CI_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Models whose architectures ship as custom code on the Hugging Face Hub.
REMOTE_CODE_MODELS = frozenset({"jinaai/jina-embeddings-v2-base-code"})


class EncoderBackend(Protocol):
    """The subset of ``SentenceTransformer`` used by :class:`CodeEmbedder`."""

    def encode(self, sentences: list[str], **kwargs: Any) -> Any: ...

    def get_sentence_embedding_dimension(self) -> int | None: ...


Loader = Callable[[str, str], EncoderBackend]


def detect_device() -> str:
    """Pick the best available accelerator: CUDA > XPU > NPU > MPS > CPU.

    ``TRACEX_DEVICE`` overrides detection. XPU is Intel GPUs via PyTorch's
    native backend; NPU is Huawei Ascend via the ``torch_npu`` extension.
    """
    override = os.environ.get("TRACEX_DEVICE")
    if override:
        return override
    import torch

    if torch.cuda.is_available():
        return "cuda"
    xpu = getattr(torch, "xpu", None)
    if xpu is not None and xpu.is_available():
        return "xpu"
    try:
        import torch_npu  # noqa: F401  # registers torch.npu

        if torch.npu.is_available():
            return "npu"
    except ImportError:
        pass
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def sentence_transformer_loader(model_name: str, device: str) -> EncoderBackend:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device, trust_remote_code=model_name in REMOTE_CODE_MODELS)


def l2_normalize(vectors: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Row-wise L2 normalization; all-zero rows are left as zeros."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms < eps, 1.0, norms)


class CodeEmbedder:
    """Lazily loaded, cached, deterministic sentence-transformers wrapper."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        fallback_models: Sequence[str] = FALLBACK_MODELS,
        device: str | None = None,
        batch_size: int = 32,
        max_seq_length: int | None = 512,
        cache_size: int = 10_000,
        loader: Loader = sentence_transformer_loader,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.candidate_models = (model_name, *fallback_models)
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self.cache_size = cache_size
        self._device = device
        self._loader = loader
        self._model: EncoderBackend | None = None
        self._model_name: str | None = None
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = detect_device()
        return self._device

    @property
    def model(self) -> EncoderBackend:
        if self._model is None:
            self._load()
        assert self._model is not None
        return self._model

    @property
    def model_name(self) -> str:
        """Name of the model actually loaded (may be a fallback)."""
        if self._model is None:
            self._load()
        assert self._model_name is not None
        return self._model_name

    @property
    def dimension(self) -> int:
        dim = self.model.get_sentence_embedding_dimension()
        if dim is None:
            dim = int(np.asarray(self.model.encode(["probe"], convert_to_numpy=True)).shape[-1])
        return dim

    def _load(self) -> None:
        errors = []
        for name in self.candidate_models:
            try:
                model = self._loader(name, self.device)
            except Exception as exc:  # noqa: BLE001 - any load failure triggers fallback
                logger.warning("Failed to load embedding model %s: %s", name, exc)
                errors.append(f"{name}: {exc}")
                continue
            if self.max_seq_length is not None and hasattr(model, "max_seq_length"):
                model.max_seq_length = self.max_seq_length
            self._model, self._model_name = model, name
            logger.info("Loaded embedding model %s on %s", name, self.device)
            return
        raise RuntimeError("No embedding model could be loaded:\n" + "\n".join(errors))

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Encode texts into an ``(n, d)`` float32 array of unit vectors."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        keys = [self._key(t) for t in texts]
        pending: dict[str, tuple[int, str]] = {}
        for index, (key, text) in enumerate(zip(keys, texts, strict=True)):
            if key not in self._cache and key not in pending:
                pending[key] = (index, text)

        fresh: dict[str, np.ndarray] = {}
        if pending:
            ordered = sorted(pending.items(), key=lambda kv: (-len(kv[1][1]), kv[1][0]))
            for start in range(0, len(ordered), self.batch_size):
                batch = ordered[start : start + self.batch_size]
                raw = self.model.encode(
                    [text for _, (_, text) in batch],
                    batch_size=len(batch),
                    convert_to_numpy=True,
                    normalize_embeddings=False,
                    show_progress_bar=False,
                )
                for (key, _), vector in zip(batch, l2_normalize(raw), strict=True):
                    fresh[key] = vector

        rows = []
        for key in keys:
            vector = fresh.get(key)
            if vector is None:
                vector = self._cache[key]
                self._cache.move_to_end(key)
            rows.append(vector)
        self._remember(fresh)
        return np.stack(rows)

    def _remember(self, vectors: dict[str, np.ndarray]) -> None:
        if self.cache_size <= 0:
            return
        for key, vector in vectors.items():
            self._cache[key] = vector
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def encode_query(self, query: str) -> np.ndarray:
        return self.encode([query])[0]

    def encode_symbols(self, symbols: Iterable[SymbolNode], *, include_context: bool = True) -> np.ndarray:
        return self.encode([serialize_chunk(s, include_context=include_context) for s in symbols])

    def clear_cache(self) -> None:
        self._cache.clear()
