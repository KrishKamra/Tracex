"""Prefix-aware query parsing for the command palette.

    @symbol   restrict to symbols whose (qualified) name contains ``symbol``
    #route    restrict to handlers whose effective route contains ``route``
    /path     restrict to files whose path contains ``path`` at a segment boundary

Remaining tokens form the free-text query ranked by the hybrid engine. Filters
combine with AND. With no free text, matches are ordered by filter match
quality (exact name > name prefix > qualified suffix > substring).

Effective routes join class-level and method-level decorator paths, so
``@Controller("/webhooks")`` + ``@Post("/stripe")`` matches ``#/webhooks/stripe``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.parser.ast_engine import SymbolNode

_ROUTE_LITERAL_RE = re.compile(r"""["'`](/[^"'`]*)["'`]""")


@dataclass(frozen=True)
class ParsedQuery:
    raw: str
    text: str
    symbol: str | None = None
    route: str | None = None
    path: str | None = None

    @property
    def has_filters(self) -> bool:
        return any((self.symbol, self.route, self.path))


def parse_query(raw: str) -> ParsedQuery:
    text_tokens: list[str] = []
    filters: dict[str, str] = {}
    for token in raw.split():
        if len(token) > 1 and token[0] == "@":
            filters["symbol"] = token[1:]
        elif len(token) > 1 and token[0] == "#":
            filters["route"] = token[1:] if token[1] == "/" else "/" + token[1:]
        elif len(token) > 1 and token[0] == "/":
            filters["path"] = token[1:]
        else:
            text_tokens.append(token)
    return ParsedQuery(raw=raw, text=" ".join(text_tokens), **filters)


def route_paths(decorators: Iterable[str]) -> list[str]:
    return [m for d in decorators for m in _ROUTE_LITERAL_RE.findall(d)]


def _join(prefix: str, path: str) -> str:
    return "/" + "/".join(part for part in (prefix + "/" + path).split("/") if part)


def effective_routes(symbol: SymbolNode, by_qualified: Mapping[tuple[str, str], SymbolNode]) -> list[str]:
    """Routes declared on the symbol, prefixed by routes on its enclosing classes."""
    own = route_paths(symbol.decorators)
    if not own:
        return []
    prefixes = [""]
    scope = symbol.enclosing_class
    while scope:
        owner = by_qualified.get((symbol.file_path, scope))
        if owner is not None:
            class_routes = route_paths(owner.decorators)
            if class_routes:
                prefixes = [_join(c, p) for c in class_routes for p in prefixes]
        scope = scope.rpartition(".")[0]
    return sorted({_join(prefix, path) for prefix in prefixes for path in own} | {_join("", p) for p in own})


def _symbol_quality(symbol: SymbolNode, needle: str) -> int | None:
    """Lower is better; None means no match."""
    name, qualified = symbol.name.lower(), symbol.qualified_name.lower()
    if name == needle:
        return 0
    if name.startswith(needle):
        return 1
    if qualified.endswith(needle):
        return 2
    if needle in qualified:
        return 3
    return None


def _path_matches(file_path: str, fragment: str) -> bool:
    """Segment-anchored match: ``hooks`` matches ``src/hooks/``, not ``webhooks.py``."""
    return f"/{fragment.lower().lstrip('/')}" in f"/{file_path.lower()}"


def apply_filters(parsed: ParsedQuery, symbols: Iterable[SymbolNode]) -> list[SymbolNode]:
    """Symbols passing every filter, ordered by match quality then source position."""
    symbols = list(symbols)
    by_qualified = {(s.file_path, s.qualified_name): s for s in symbols}
    matches: list[tuple[tuple[int, str, int], SymbolNode]] = []
    for s in symbols:
        quality = 0
        if parsed.symbol is not None:
            q = _symbol_quality(s, parsed.symbol.lower())
            if q is None:
                continue
            quality = q
        if parsed.route is not None:
            needle = parsed.route.lower()
            if not any(needle in r.lower() for r in effective_routes(s, by_qualified)):
                continue
        if parsed.path is not None and not _path_matches(s.file_path, parsed.path):
            continue
        matches.append(((quality, s.file_path, s.start_line), s))
    return [s for _, s in sorted(matches, key=lambda m: m[0])]
