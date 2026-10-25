"""Code-aware lexical tokenizer for the sparse (BM25) pillar.

Standard NLP tokenizers treat ``validateWebhookSignature`` as one
out-of-vocabulary token. This analyzer splits identifiers along camelCase,
PascalCase, snake_case and numeric boundaries while preserving the exact
original identifier, so both exact-symbol and natural-language queries match:

    tau(check_limit) = {check_limit, check, limit}

Language keywords (``async``, ``raise``, ``return``...) are preserved as whole
tokens and never split; ``keep_keywords=False`` drops them for ablations.
"""

from __future__ import annotations

import keyword
import re

PYTHON_KEYWORDS = frozenset(keyword.kwlist) | frozenset(keyword.softkwlist)
TYPESCRIPT_KEYWORDS = frozenset(
    """
    abstract any as async await boolean break case catch class const constructor
    continue debugger declare default delete do else enum export extends false
    finally for from function get if implements import in infer instanceof
    interface is keyof let module namespace never new null number object of
    package private protected public readonly require return satisfies set
    static string super switch symbol this throw true try type typeof undefined
    unique unknown var void while with yield
    """.split()  # noqa: SIM905 - a word list reads better than a 700-char list literal
)
CODE_KEYWORDS = PYTHON_KEYWORDS | TYPESCRIPT_KEYWORDS

# Structural tags emitted by the serializer; they carry no lexical signal.
_STRUCTURAL_TAG_RE = re.compile(r"\[(?:DOC|SIG|CODE|FILE|SCOPE)\]")
_TOKEN_RE = re.compile(r"(?:[^\W\d]|\$)[\w$]*|\d+")
_SEPARATOR_RE = re.compile(r"[_$]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_identifier(identifier: str, *, lowercase: bool = True) -> list[str]:
    """Split an identifier into sub-tokens.

    >>> split_identifier("check_limit")
    ['check', 'limit']
    >>> split_identifier("WebhookReceiver")
    ['webhook', 'receiver']
    >>> split_identifier("parseHTTPResponse2xx")
    ['parse', 'http', 'response', '2', 'xx']
    """
    parts: list[str] = []
    for segment in _SEPARATOR_RE.split(identifier):
        if not segment:
            continue
        # Non-ASCII identifiers have no reliable case boundaries; keep whole.
        parts.extend(_CAMEL_RE.findall(segment) if segment.isascii() else [segment])
    return [p.lower() for p in parts] if lowercase else parts


class CodeTokenizer:
    """Tokenizes code and docstrings into BM25 terms."""

    def __init__(
        self,
        *,
        lowercase: bool = True,
        keep_keywords: bool = True,
        keep_numbers: bool = True,
        keywords: frozenset[str] = CODE_KEYWORDS,
    ) -> None:
        self.lowercase = lowercase
        self.keep_keywords = keep_keywords
        self.keep_numbers = keep_numbers
        self.keywords = keywords

    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw in _TOKEN_RE.findall(_STRUCTURAL_TAG_RE.sub(" ", text)):
            if raw.isdigit():
                if self.keep_numbers:
                    tokens.append(raw)
                continue
            original = raw.lower() if self.lowercase else raw
            if raw in self.keywords:
                if self.keep_keywords:
                    tokens.append(original)
                continue
            tokens.append(original)
            sub_tokens = split_identifier(raw, lowercase=self.lowercase)
            if sub_tokens != [original]:
                tokens.extend(sub_tokens)
        return tokens

    __call__ = tokenize


_default_tokenizer = CodeTokenizer()


def tokenize(text: str) -> list[str]:
    """Tokenize with default settings (lowercased, keywords and numbers kept)."""
    return _default_tokenizer.tokenize(text)
