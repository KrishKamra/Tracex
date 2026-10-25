"""Structured serialization of AST chunks for the dense and sparse encoders.

    Serialized_Chunk = [DOC] docstring (+) [SIG] signature (+) [CODE] body

where (+) is newline-delimited structural concatenation. With
``include_context=True`` the chunk is prefixed with its file path and lexical
scope (spec section 3.1), which disambiguates same-named methods in different
classes for the bi-encoder:

    [FILE] path (+) [SCOPE] qualified_name (kind) (+) [DOC] ... [SIG] ... [CODE] ...

Decorators are part of the ``[SIG]`` segment: routes such as
``@router.post("/webhook")`` are often the strongest lexical signal.
"""

from __future__ import annotations

from app.parser.ast_engine import SymbolNode

DOC_TAG = "[DOC]"
SIG_TAG = "[SIG]"
CODE_TAG = "[CODE]"
FILE_TAG = "[FILE]"
SCOPE_TAG = "[SCOPE]"


def _segment(tag: str, content: str) -> str:
    return f"{tag} {content}".rstrip()


def full_signature(symbol: SymbolNode) -> str:
    """Decorators followed by the signature, one per line."""
    return "\n".join([*symbol.decorators, symbol.signature])


def serialize_chunk(symbol: SymbolNode, *, include_context: bool = False) -> str:
    segments = []
    if include_context:
        segments += [
            _segment(FILE_TAG, symbol.file_path),
            _segment(SCOPE_TAG, f"{symbol.qualified_name} ({symbol.kind})"),
        ]
    segments += [
        _segment(DOC_TAG, symbol.docstring),
        _segment(SIG_TAG, full_signature(symbol)),
        _segment(CODE_TAG, symbol.body),
    ]
    return "\n".join(segments)
