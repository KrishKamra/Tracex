import hashlib
import os

import numpy as np
import pytest

from app.nlp.embeddings import CI_MODEL, CodeEmbedder, detect_device, l2_normalize
from app.parser import ASTEngine


class FakeBackend:
    """Deterministic hash-seeded vectors; records every batch it receives."""

    dim = 8

    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self.max_seq_length = 8192

    def encode(self, sentences, **kwargs):
        self.batches.append(list(sentences))
        rows = []
        for text in sentences:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "little")
            rows.append(np.random.default_rng(seed).normal(size=self.dim) * 5)
        return np.array(rows, dtype=np.float32)

    def get_sentence_embedding_dimension(self):
        return self.dim


def make_embedder(**kwargs):
    backend = FakeBackend()
    embedder = CodeEmbedder(
        "fake/model", fallback_models=(), device="cpu", loader=lambda name, device: backend, **kwargs
    )
    return embedder, backend


def test_vectors_are_l2_normalized():
    embedder, _ = make_embedder()
    vectors = embedder.encode(["def a(): pass", "def b(): pass", "x"])
    assert vectors.shape == (3, FakeBackend.dim)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-6)


def test_l2_normalize_leaves_zero_rows():
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.testing.assert_allclose(out, [[0.6, 0.8], [0.0, 0.0]])


def test_batching_is_deterministic_and_length_ordered():
    texts = ["bb", "a", "dddd", "ccc", "eeeee"]
    embedder, backend = make_embedder(batch_size=2)
    out = embedder.encode(texts)
    assert backend.batches == [["eeeee", "dddd"], ["ccc", "bb"], ["a"]]

    other, other_backend = make_embedder(batch_size=2)
    shuffled = other.encode(list(reversed(texts)))
    assert other_backend.batches == backend.batches
    np.testing.assert_array_equal(shuffled, out[::-1])


def test_cache_and_in_call_dedup():
    embedder, backend = make_embedder()
    first = embedder.encode(["a", "b", "a"])
    np.testing.assert_array_equal(first[0], first[2])
    assert backend.batches == [["a", "b"]]

    second = embedder.encode(["b", "c"])
    assert backend.batches[-1] == ["c"]
    np.testing.assert_array_equal(second[0], first[1])


def test_cache_is_bounded_lru():
    embedder, backend = make_embedder(cache_size=2)
    embedder.encode(["a", "b"])
    embedder.encode(["a"])  # refresh "a"
    embedder.encode(["c"])  # evicts "b"
    embedder.encode(["a", "b"])
    assert backend.batches[-1] == ["b"]


def test_encode_query_and_empty_input():
    embedder, _ = make_embedder()
    assert embedder.encode_query("verify webhook signature").shape == (FakeBackend.dim,)
    assert embedder.encode([]).shape == (0, FakeBackend.dim)


def test_encode_symbols_uses_contextual_serialization():
    parsed = ASTEngine().parse_source("def f():\n    return 1\n", "python", "m.py")
    embedder, backend = make_embedder()
    embedder.encode_symbols(parsed.symbols)
    assert backend.batches == [["[FILE] m.py\n[SCOPE] f (function)\n[DOC]\n[SIG] def f()\n[CODE] return 1"]]


def test_fallback_model_chain_and_max_seq_length():
    backend = FakeBackend()
    attempts = []

    def loader(name, device):
        attempts.append((name, device))
        if name == "primary/model":
            raise OSError("remote code incompatible")
        return backend

    embedder = CodeEmbedder(
        "primary/model", fallback_models=("fallback/model",), device="cpu", loader=loader, max_seq_length=256
    )
    assert embedder.model_name == "fallback/model"
    assert attempts == [("primary/model", "cpu"), ("fallback/model", "cpu")]
    assert backend.max_seq_length == 256


def test_all_models_failing_raises():
    def loader(name, device):
        raise OSError("offline")

    embedder = CodeEmbedder("a", fallback_models=("b",), device="cpu", loader=loader)
    with pytest.raises(RuntimeError, match="a: offline"):
        embedder.encode(["x"])


def test_device_detection(monkeypatch):
    monkeypatch.setenv("TRACEX_DEVICE", "npu")
    assert detect_device() == "npu"
    monkeypatch.delenv("TRACEX_DEVICE")
    assert detect_device() in {"cuda", "xpu", "npu", "mps", "cpu"}


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("TRACEX_RUN_SLOW") != "1", reason="set TRACEX_RUN_SLOW=1 to download a real model"
)
def test_real_model_ranks_relevant_code_higher():
    embedder = CodeEmbedder(os.environ.get("TRACEX_EMBED_MODEL", CI_MODEL), fallback_models=())
    query = embedder.encode_query("verify the HMAC signature of a webhook payload")
    docs = embedder.encode(
        [
            "def validate_signature(payload, signature):\n"
            "    return hmac.compare_digest(sign(payload), signature)",
            "def render_invoice_pdf(invoice):\n    return pdf.build(invoice.lines)",
        ]
    )
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), 1.0, rtol=1e-5)
    relevant, irrelevant = docs @ query
    assert relevant > irrelevant
