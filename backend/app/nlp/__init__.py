"""Phase 1 inference layer: code tokenization, serialization and dense embeddings.

``app.nlp.embeddings`` is not re-exported here so that importing the tokenizer
never pulls in torch.
"""

from app.nlp.serializer import serialize_chunk
from app.nlp.tokenizer import CodeTokenizer, split_identifier, tokenize

__all__ = ["CodeTokenizer", "serialize_chunk", "split_identifier", "tokenize"]
