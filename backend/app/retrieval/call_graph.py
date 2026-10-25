"""Pillar 3: Code Property Graph (CPG) over AST chunks.

G = (V, E) is a NetworkX ``MultiDiGraph``. V contains one vertex per symbol chunk
plus one ``module::<path>`` vertex per file. E is a subset of V x V x
{CALLS, INHERITS, IMPORTS}, with one edge per (u, v, kind) triple:

* ``CALLS``    symbol -> symbol    call site in u resolves to definition v
                                    (edge attribute ``lines``: call-site lines in u)
* ``INHERITS`` class  -> class     v is a base class of u
* ``IMPORTS``  module -> symbol | module

Name resolution is static. It follows lexical scope, ``self``/``this``/
``super()`` receivers, inherited methods, import bindings (aliases, relative
modules, TS namespace imports) and a repository-unique-name fallback. Receivers
are typed by lightweight flow-insensitive inference over parameter annotations,
constructor assignments (``repo = PaymentRepository()``, ``self.audit =
AuditLog()``) and return annotations (``UsageStore.default().increment``). Calls
into external libraries are unresolvable by design and counted in
:class:`GraphStats`.

Graph expansion (spec 3.4): given seed scores over S_0 from the dense and
sparse pillars, each 1-hop neighbour u is scored by degree-damped proximity:

    Score_Graph(u) = sum_{v in S_0, (u,v) in E or (v,u) in E}  Score_Seed(v) / (1 + ln(1 + deg(u)))

Only symbol-level edges (CALLS, INHERITS) are traversed, so module vertices
never surface as search results. The damping keeps hub utilities (loggers,
generic helpers) from dominating every expansion.
"""

from __future__ import annotations

import math
import posixpath
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import networkx as nx

from app.parser.ast_engine import SymbolNode

EdgeKind = Literal["CALLS", "INHERITS", "IMPORTS"]
SYMBOL_EDGE_KINDS: tuple[EdgeKind, ...] = ("CALLS", "INHERITS")
_TS_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts")
_NULL_TYPES = frozenset({"None", "null", "undefined"})
_MAX_TYPE_DEPTH = 4


@dataclass(frozen=True, slots=True)
class _ModuleRef:
    file_path: str


@dataclass(frozen=True, slots=True)
class _Binding:
    """A name bound by an import: a whole module, or a member of a module."""

    file_path: str
    member: str | None = None


@dataclass(frozen=True, slots=True)
class GraphStats:
    symbols: int
    modules: int
    edges: Mapping[str, int]
    call_names: int
    resolved_calls: int
    unresolved_samples: tuple[str, ...]

    @property
    def resolution_rate(self) -> float:
        return self.resolved_calls / self.call_names if self.call_names else 0.0


def module_node(file_path: str) -> str:
    return f"module::{file_path}"


def _python_module_keys(file_path: str) -> list[str]:
    """``billing/payments.py`` -> ``billing.payments``, ``payments`` (all dotted suffixes)."""
    stem = file_path.removesuffix(".pyi").removesuffix(".py")
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts)) if parts[i:]]


class _Resolver:
    def __init__(self, symbols: list[SymbolNode]) -> None:
        self.by_id = {s.symbol_id: s for s in symbols}
        self.by_file_qual: dict[tuple[str, str], str] = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.members: dict[tuple[str, str], list[SymbolNode]] = defaultdict(list)
        files: set[str] = set()
        for s in symbols:
            files.add(s.file_path)
            if s.enclosing_class is not None:
                self.members[(s.file_path, s.enclosing_class)].append(s)
            self.by_file_qual.setdefault((s.file_path, s.qualified_name), s.symbol_id)
            if s.kind != "method" and s.parent_scope is None:
                self.by_name[s.name].append(s.symbol_id)
        self.files = files
        self.py_modules: dict[str, list[str]] = defaultdict(list)
        for f in sorted(files):
            if f.endswith((".py", ".pyi")):
                for key in _python_module_keys(f):
                    self.py_modules[key].append(f)
        self.bindings: dict[str, dict[str, _Binding]] = {}
        self.wildcards: dict[str, list[str]] = defaultdict(list)
        for s in symbols:
            if s.file_path not in self.bindings:
                self.bindings[s.file_path] = self._bind_imports(s)

    # -- modules & imports --------------------------------------------------- #
    def resolve_module(self, importer: str, module: str) -> str | None:
        if importer.endswith(_TS_EXTENSIONS):
            if not module.startswith("."):
                return None  # package import (node_modules)
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), module))
            for candidate in [base + ext for ext in _TS_EXTENSIONS] + [
                f"{base}/index{ext}" for ext in _TS_EXTENSIONS
            ]:
                if candidate in self.files:
                    return candidate
            return None
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            base = posixpath.dirname(importer)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            rest = module.lstrip(".").replace(".", "/")
            stem = posixpath.join(base, rest) if rest else base
            for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
                if candidate in self.files:
                    return candidate
            return None
        candidates = self.py_modules.get(module, [])
        return candidates[0] if candidates else None

    def _bind_imports(self, symbol: SymbolNode) -> dict[str, _Binding]:
        bindings: dict[str, _Binding] = {}
        importer = symbol.file_path
        for ref in symbol.imports:
            target = self.resolve_module(importer, ref.module)
            if ref.name is None:  # import a.b [as c]
                if target is not None:
                    bindings[ref.alias or ref.module] = _Binding(target)
            elif ref.name == "*":
                if target is None:
                    continue
                if ref.alias:  # TS: import * as ns
                    bindings[ref.alias] = _Binding(target)
                else:  # Python: from m import *
                    self.wildcards[importer].append(target)
            elif ref.name != "default":
                local = ref.alias or ref.name
                if target is not None and (target, ref.name) in self.by_file_qual:
                    bindings[local] = _Binding(target, ref.name)
                elif not importer.endswith(_TS_EXTENSIONS):
                    # `from pkg import submodule` / `from . import submodule`
                    sep = "" if ref.module.endswith(".") else "."
                    submodule = self.resolve_module(importer, f"{ref.module}{sep}{ref.name}")
                    if submodule is not None:
                        bindings[local] = _Binding(submodule)
        return bindings

    # -- symbol lookup -------------------------------------------------------- #
    def resolve_bare(self, symbol: SymbolNode, name: str) -> str | _ModuleRef | None:
        file_path = symbol.file_path
        # 1. Lexical scope chain (class bodies are not enclosing scopes for names).
        scope = symbol.qualified_name
        while True:
            owner = self.by_file_qual.get((file_path, scope)) if scope else None
            if owner is None or self.by_id[owner].kind != "class":
                candidate = self.by_file_qual.get((file_path, f"{scope}.{name}" if scope else name))
                if candidate is not None:
                    return candidate
            if not scope:
                break
            scope = scope.rpartition(".")[0]
        # 2. Import bindings.
        binding = self.bindings.get(file_path, {}).get(name)
        if binding is not None:
            if binding.member is None:
                return _ModuleRef(binding.file_path)
            return self.by_file_qual.get((binding.file_path, binding.member))
        for module_file in self.wildcards.get(file_path, []):
            candidate = self.by_file_qual.get((module_file, name))
            if candidate is not None:
                return candidate
        # 3. Repository-unique top-level name.
        matches = self.by_name.get(name, [])
        return matches[0] if len(matches) == 1 else None

    # -- type inference --------------------------------------------------- #
    def _is_class(self, target: object) -> bool:
        return isinstance(target, str) and self.by_id[target].kind == "class"

    def as_class(self, target: str | _ModuleRef | None, depth: int = 0) -> str | None:
        """Class an expression evaluates to: a class itself, or a callable's return type."""
        if not isinstance(target, str) or depth > _MAX_TYPE_DEPTH:
            return None
        symbol = self.by_id[target]
        if symbol.kind == "class":
            return target
        return_type = symbol.ast_scope_details.return_type
        return self.class_from_type(symbol, return_type, depth + 1) if return_type else None

    def class_from_type(self, context: SymbolNode, type_text: str, depth: int = 0) -> str | None:
        """Resolve a type hint (annotation or constructor/factory callee) to a class id."""
        if depth > _MAX_TYPE_DEPTH:
            return None
        text = type_text.strip().strip("'\"")
        if text.startswith("Optional[") and text.endswith("]"):
            text = text[len("Optional[") : -1]
        options = [t.strip() for t in text.split("|") if t.strip() not in _NULL_TYPES]
        if len(options) != 1:
            return None
        name = options[0].split("<")[0].split("[")[0].strip()
        return self.as_class(self.resolve_dotted(context, name, depth + 1), depth + 1)

    def _scope_chain(self, symbol: SymbolNode) -> list[SymbolNode]:
        """The symbol and its enclosing function scopes (innermost first)."""
        chain = [symbol]
        scope = symbol.parent_scope
        while scope:
            owner = self.by_file_qual.get((symbol.file_path, scope))
            if owner is None or self.by_id[owner].kind == "class":
                break
            chain.append(self.by_id[owner])
            scope = scope.rpartition(".")[0]
        return chain

    def is_local(self, symbol: SymbolNode, name: str) -> bool:
        """True if ``name`` is a plain local/parameter (not a nested named definition)."""
        for scope in self._scope_chain(symbol):
            if (scope.file_path, f"{scope.qualified_name}.{name}") in self.by_file_qual:
                return False  # e.g. `const toggleSort = () => ...`: resolve to the definition
            details = scope.ast_scope_details
            if name in details.locals or any(p.name.lstrip("*.") == name for p in details.params):
                return True
        return False

    def variable_class(self, symbol: SymbolNode, name: str, depth: int = 0) -> str | None:
        for scope in self._scope_chain(symbol):
            details = scope.ast_scope_details
            for key, hint in details.type_hints:
                if key == name and (cls := self.class_from_type(scope, hint, depth + 1)):
                    return cls
            for param in details.params:
                if (
                    param.name == name
                    and param.annotation
                    and (cls := self.class_from_type(scope, param.annotation, depth + 1))
                ):
                    return cls
        return None

    def attribute_class(
        self, class_id: str, attr: str, depth: int = 0, seen: frozenset[str] = frozenset()
    ) -> str | None:
        """Type of ``self.attr`` / ``this.attr``, from assignments anywhere in the class."""
        if class_id in seen or depth > _MAX_TYPE_DEPTH:
            return None
        cls = self.by_id[class_id]
        keys = {f"self.{attr}", f"this.{attr}"}
        for member in [cls, *self.members.get((cls.file_path, cls.qualified_name), [])]:
            for key, hint in member.ast_scope_details.type_hints:
                matches = key in keys or (member is cls and key == attr)
                if matches and (found := self.class_from_type(member, hint, depth + 1)):
                    return found
        for base in self.base_classes(class_id):
            if found := self.attribute_class(base, attr, depth, seen | {class_id}):
                return found
        return None

    def class_of(self, symbol: SymbolNode) -> str | None:
        if symbol.enclosing_class is None:
            return None
        return self.by_file_qual.get((symbol.file_path, symbol.enclosing_class))

    def base_classes(self, class_id: str) -> list[str]:
        cls = self.by_id[class_id]
        bases = []
        for base in cls.bases:
            target = self.resolve_dotted(cls, base.split("<")[0].split("[")[0].strip())
            if isinstance(target, str) and self.by_id[target].kind == "class" and target != class_id:
                bases.append(target)
        return bases

    def method_lookup(self, class_id: str, name: str, seen: frozenset[str] = frozenset()) -> str | None:
        if class_id in seen:
            return None
        cls = self.by_id[class_id]
        found = self.by_file_qual.get((cls.file_path, f"{cls.qualified_name}.{name}"))
        if found is not None:
            return found
        for base in self.base_classes(class_id):
            found = self.method_lookup(base, name, seen | {class_id})
            if found is not None:
                return found
        return None

    def _member(self, target: str | _ModuleRef | None, part: str, final: bool) -> str | _ModuleRef | None:
        if isinstance(target, _ModuleRef):
            return self.by_file_qual.get((target.file_path, part))
        if self._is_class(target):
            method = self.method_lookup(target, part)
            if method is None and not final:
                return self.attribute_class(target, part)
            return method
        return None

    def resolve_dotted(self, symbol: SymbolNode, callee: str, depth: int = 0) -> str | _ModuleRef | None:
        parts = callee.split(".")
        # Longest dotted prefix bound to a module import, e.g. `os.path`.
        file_bindings = self.bindings.get(symbol.file_path, {})
        target: str | _ModuleRef | None = None
        rest = parts
        for k in range(len(parts) - 1, 1, -1):
            binding = file_bindings.get(".".join(parts[:k]))
            if binding is not None and binding.member is None:
                target, rest = _ModuleRef(binding.file_path), parts[k:]
                break
        else:
            head, rest = parts[0], parts[1:]
            if head in {"self", "this", "cls"}:
                target = self.class_of(symbol)
                if not rest:
                    return None
            elif head in {"super", "super()"}:
                own = self.class_of(symbol)
                bases = self.base_classes(own) if own else []
                if not bases:
                    return None
                if not rest:
                    if not symbol.file_path.endswith(_TS_EXTENSIONS):
                        return None  # Python `super()` itself just builds a proxy
                    return self.method_lookup(bases[0], "constructor") or bases[0]  # TS `super(...)`
                return (
                    next((m for b in bases if (m := self.method_lookup(b, rest[0]))), None)
                    if len(rest) == 1
                    else None
                )
            else:
                name = head.removesuffix("()")
                if head.endswith("()"):
                    target = self.as_class(self.resolve_bare(symbol, name), depth)
                    if target is None:
                        return None  # receiver is a call whose return type is unknown
                elif rest and (typed := self.variable_class(symbol, name, depth)):
                    target = typed
                elif self.is_local(symbol, name):
                    return None  # an untyped local shadows any global of that name
                else:
                    target = self.resolve_bare(symbol, name)
        for index, part in enumerate(rest):
            final = index == len(rest) - 1
            if part.endswith("()"):
                target = self.as_class(self._member(target, part[:-2], final=True), depth)
            else:
                target = self._member(target, part, final)
            if target is None:
                return None
        return target

    def resolve_call(self, symbol: SymbolNode, callee: str) -> str | None:
        if not callee or callee.startswith("."):
            return None
        target = self.resolve_dotted(symbol, callee)
        return target if isinstance(target, str) and target != symbol.symbol_id else None


class CallGraph:
    """Directed multigraph of CALLS / INHERITS / IMPORTS relations."""

    def __init__(self, symbols: Iterable[SymbolNode]) -> None:
        self.symbols = list(symbols)
        self.graph = nx.MultiDiGraph()
        self._resolved: dict[tuple[str, str], str] = {}
        resolver = _Resolver(self.symbols)
        for s in self.symbols:
            self.graph.add_node(s.symbol_id, kind=s.kind, name=s.qualified_name, file_path=s.file_path)
        for f in sorted(resolver.files):
            self.graph.add_node(module_node(f), kind="module", name=f, file_path=f)

        call_names = resolved = 0
        unresolved: list[str] = []
        for s in self.symbols:
            lines_by_callee: dict[str, list[int]] = defaultdict(list)
            for site in s.call_sites:
                lines_by_callee[site.callee].append(site.line)
            for callee in s.calls:
                call_names += 1
                target = resolver.resolve_call(s, callee)
                if target is None:
                    unresolved.append(f"{s.symbol_id} -> {callee}")
                    continue
                resolved += 1
                self._resolved[(s.symbol_id, callee)] = target
                if not self.graph.has_edge(s.symbol_id, target, key="CALLS"):
                    self.graph.add_edge(s.symbol_id, target, key="CALLS", lines=[])
                self.graph.edges[s.symbol_id, target, "CALLS"]["lines"].extend(lines_by_callee[callee])
            if s.kind == "class":
                for base in resolver.base_classes(s.symbol_id):
                    self.graph.add_edge(s.symbol_id, base, key="INHERITS")
        for f, bindings in resolver.bindings.items():
            for binding in bindings.values():
                if binding.member is None:
                    target = module_node(binding.file_path)
                else:
                    target = resolver.by_file_qual.get((binding.file_path, binding.member))
                if target is not None:
                    self.graph.add_edge(module_node(f), target, key="IMPORTS")

        edge_counts: dict[str, int] = defaultdict(int)
        for _, _, kind in self.graph.edges(keys=True):
            edge_counts[kind] += 1
        self.stats = GraphStats(
            symbols=len(self.symbols),
            modules=len(resolver.files),
            edges=dict(sorted(edge_counts.items())),
            call_names=call_names,
            resolved_calls=resolved,
            unresolved_samples=tuple(unresolved[:50]),
        )

    def __contains__(self, symbol_id: str) -> bool:
        return symbol_id in self.graph

    def _edges(self, symbol_id: str, kind: EdgeKind, outgoing: bool) -> list[str]:
        if symbol_id not in self.graph:
            return []
        edges = (
            self.graph.out_edges(symbol_id, keys=True)
            if outgoing
            else self.graph.in_edges(symbol_id, keys=True)
        )
        return sorted({(v if outgoing else u) for u, v, k in edges if k == kind})

    def callees(self, symbol_id: str) -> list[str]:
        """Downstream: symbols that ``symbol_id`` calls."""
        return self._edges(symbol_id, "CALLS", outgoing=True)

    def resolve(self, caller: str, callee: str) -> str | None:
        """Definition that the callee name ``callee`` in ``caller`` resolved to, if any."""
        return self._resolved.get((caller, callee))

    def call_lines(self, caller: str, callee: str) -> list[int]:
        """Sorted lines in ``caller`` where it calls ``callee`` (empty if no CALLS edge)."""
        if not self.graph.has_edge(caller, callee, key="CALLS"):
            return []
        return sorted(set(self.graph.edges[caller, callee, "CALLS"]["lines"]))

    def callers(self, symbol_id: str) -> list[str]:
        """Upstream: symbols that call ``symbol_id``."""
        return self._edges(symbol_id, "CALLS", outgoing=False)

    def fan_in(self, symbol_id: str) -> int:
        return len(self.callers(symbol_id))

    def fan_out(self, symbol_id: str) -> int:
        return len(self.callees(symbol_id))

    def neighbors(self, symbol_id: str, kinds: tuple[EdgeKind, ...] = SYMBOL_EDGE_KINDS) -> list[str]:
        """Undirected 1-hop neighbourhood over the given edge kinds."""
        if symbol_id not in self.graph:
            return []
        out = {v for _, v, k in self.graph.out_edges(symbol_id, keys=True) if k in kinds}
        inc = {u for u, _, k in self.graph.in_edges(symbol_id, keys=True) if k in kinds}
        return sorted((out | inc) - {symbol_id})

    def degree(self, symbol_id: str, kinds: tuple[EdgeKind, ...] = SYMBOL_EDGE_KINDS) -> int:
        return len(self.neighbors(symbol_id, kinds))

    def expand(
        self, seed_scores: Mapping[str, float], kinds: tuple[EdgeKind, ...] = SYMBOL_EDGE_KINDS
    ) -> dict[str, float]:
        """Degree-damped 1-hop expansion scores (see module docstring)."""
        scores: dict[str, float] = defaultdict(float)
        for seed, seed_score in seed_scores.items():
            for u in self.neighbors(seed, kinds):
                scores[u] += seed_score
        return {u: total / (1 + math.log(1 + self.degree(u, kinds))) for u, total in scores.items()}
