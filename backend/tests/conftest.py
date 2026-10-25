import hashlib
from pathlib import Path

import numpy as np
import pytest

from app.evaluation.dataset import load_dataset
from app.nlp.embeddings import CodeEmbedder
from app.nlp.tokenizer import CodeTokenizer
from app.parser import ASTEngine

BACKEND = Path(__file__).resolve().parents[1]
BILLING_DATASET = BACKEND / "eval" / "datasets" / "billing_service.json"


class HashingBackend:
    """Bag-of-sub-tokens hashing-trick encoder: deterministic, lexical, model-free."""

    dim = 256

    def __init__(self) -> None:
        self.tokenizer = CodeTokenizer(keep_keywords=False)
        self.calls = 0

    def encode(self, sentences, **kwargs):
        self.calls += 1
        out = np.zeros((len(sentences), self.dim), dtype=np.float32)
        for row, text in enumerate(sentences):
            for token in self.tokenizer.tokenize(text):
                bucket = int.from_bytes(hashlib.sha1(token.encode()).digest()[:4], "little") % self.dim
                out[row, bucket] += 1.0
        return out

    def get_sentence_embedding_dimension(self):
        return self.dim


def make_hashing_embedder() -> CodeEmbedder:
    backend = HashingBackend()
    return CodeEmbedder("hashing", fallback_models=(), device="cpu", loader=lambda name, device: backend)


@pytest.fixture(scope="session")
def billing_dataset():
    return load_dataset(BILLING_DATASET)


@pytest.fixture(scope="session")
def billing_symbols(billing_dataset):
    parsed = ASTEngine().parse_repository(billing_dataset.corpus_root)
    return [s for f in parsed for s in f.symbols]
