"""Tree-sitter AST engine: deterministic, scope-preserving code chunking.

Naive sliding-window chunking severs function bodies and orphans docstrings.
Instead, every AST node u in V_AST of a definition type (function, method,
class) becomes exactly one structured chunk c_i carrying its enclosing scope,
signature, decorators, docstring, body and exact source coordinates.

Span conventions (all line numbers are 1-indexed and inclusive):

* A chunk's span starts at its first decorator (or ``export`` keyword for
  TypeScript) and ends at the last byte of the definition. Leading doc
  comments (JSDoc) are captured in ``docstring`` but are not part of the span.
* ``calls`` / ``raises`` / ``returns`` / ``locals`` belong to the innermost
  enclosing chunk: a nested named definition is its own chunk and is excluded
  from its parent's details. Decorator calls execute in the enclosing scope, so
  they are attributed to the parent chunk.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)

SymbolKind = Literal["function", "method", "class"]
LanguageName = Literal["python", "typescript", "tsx"]

EXTENSION_LANGUAGES: dict[str, LanguageName] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
}

DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".next",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".scratchpad",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)

_RETURN_EXPR_MAX_CHARS = 120


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    annotation: str | None = None
    default: str | None = None


@dataclass(frozen=True, slots=True)
class ScopeDetails:
    """Lexical scope table shown in the code inspector."""

    params: tuple[Parameter, ...] = ()
    locals: tuple[str, ...] = ()
    raises: tuple[str, ...] = ()
    returns: tuple[str, ...] = ()
    return_type: str | None = None
    # (binding, type hint) for assignments whose type is statically evident:
    # an annotation, or the callee of a constructor/factory call, e.g.
    # ("repo", "PaymentRepository"), ("self.audit", "AuditLog").
    type_hints: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ImportRef:
    """One imported binding. ``name`` is None for whole-module imports."""

    module: str
    name: str | None
    alias: str | None
    line: int


@dataclass(frozen=True, slots=True)
class CallSite:
    """One call expression inside a chunk: normalized callee and its 1-indexed line."""

    callee: str
    line: int


@dataclass(frozen=True, slots=True)
class SymbolNode:
    """A single AST scope chunk c_i."""

    symbol_id: str
    qualified_name: str
    name: str
    kind: SymbolKind
    language: LanguageName
    file_path: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    signature: str
    decorators: tuple[str, ...]
    docstring: str
    body: str
    parent_scope: str | None
    enclosing_class: str | None
    bases: tuple[str, ...]
    imports: tuple[ImportRef, ...]
    calls: tuple[str, ...]
    ast_scope_details: ScopeDetails
    call_sites: tuple[CallSite, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedFile:
    file_path: str
    language: LanguageName
    symbols: tuple[SymbolNode, ...]
    imports: tuple[ImportRef, ...]
    has_error: bool
    line_count: int


def detect_language(path: str | os.PathLike[str]) -> LanguageName | None:
    return EXTENSION_LANGUAGES.get(Path(path).suffix.lower())


def iter_source_files(
    root: str | os.PathLike[str], ignored_dirs: frozenset[str] = DEFAULT_IGNORED_DIRS
) -> Iterator[Path]:
    """Yield supported source files under ``root`` in sorted, deterministic order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ignored_dirs)
        for filename in sorted(filenames):
            if detect_language(filename) is not None:
                yield Path(dirpath, filename)


class ASTEngine:
    """Multi-language tree-sitter front end producing :class:`SymbolNode` chunks."""

    def __init__(self) -> None:
        self._languages: dict[LanguageName, Language] = {
            "python": Language(tree_sitter_python.language()),
            "typescript": Language(tree_sitter_typescript.language_typescript()),
            "tsx": Language(tree_sitter_typescript.language_tsx()),
        }
        self._parsers = {name: Parser(lang) for name, lang in self._languages.items()}

    def parse_source(
        self, source: str | bytes, language: LanguageName, file_path: str = "<memory>"
    ) -> ParsedFile:
        src = source.encode("utf-8") if isinstance(source, str) else source
        tree = self._parsers[language].parse(src)
        extractor_cls = _PythonExtractor if language == "python" else _TypeScriptExtractor
        extractor = extractor_cls(src, language, file_path)
        imports = extractor.extract_imports(tree.root_node)
        symbols = extractor.extract_symbols(tree.root_node, imports)
        return ParsedFile(
            file_path=file_path,
            language=language,
            symbols=symbols,
            imports=imports,
            has_error=tree.root_node.has_error,
            line_count=src.count(b"\n") + (0 if src.endswith(b"\n") or not src else 1),
        )

    def parse_file(
        self, path: str | os.PathLike[str], root: str | os.PathLike[str] | None = None
    ) -> ParsedFile:
        path = Path(path)
        language = detect_language(path)
        if language is None:
            raise ValueError(f"Unsupported source file: {path}")
        rel = path.relative_to(root) if root is not None else path
        return self.parse_source(path.read_bytes(), language, rel.as_posix())

    def parse_repository(
        self,
        root: str | os.PathLike[str],
        ignored_dirs: frozenset[str] = DEFAULT_IGNORED_DIRS,
    ) -> list[ParsedFile]:
        parsed = []
        for path in iter_source_files(root, ignored_dirs):
            try:
                parsed.append(self.parse_file(path, root))
            except OSError as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)
        return parsed


# --------------------------------------------------------------------------- #
# Language-agnostic extraction machinery
# --------------------------------------------------------------------------- #


def _collapse(text: str) -> str:
    text = " ".join(text.split())
    return text.replace("( ", "(").replace(" )", ")")


def _dedupe(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _end_line(node: Node) -> int:
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


class _Extractor:
    """Shared traversal; subclasses supply the grammar-specific rules."""

    anonymous_fn_types: frozenset[str] = frozenset()
    callee_name_types: frozenset[str] = frozenset()
    callee_member_types: frozenset[str] = frozenset()
    callee_property_field: str = ""
    callee_call_types: frozenset[str] = frozenset()

    def __init__(self, src: bytes, language: LanguageName, file_path: str) -> None:
        self.src = src
        self.language = language
        self.file_path = file_path
        self._seen_ids: set[str] = set()

    # -- grammar hooks ------------------------------------------------------ #
    def is_target(self, node: Node) -> bool:
        raise NotImplementedError

    def extract_imports(self, root: Node) -> tuple[ImportRef, ...]:
        raise NotImplementedError

    def build_symbol(
        self, node: Node, scope: tuple[tuple[str, SymbolKind], ...], imports: tuple[ImportRef, ...]
    ) -> SymbolNode:
        raise NotImplementedError

    def symbol_name(self, node: Node) -> str:
        raise NotImplementedError

    def symbol_kind(self, node: Node, scope: tuple[tuple[str, SymbolKind], ...]) -> SymbolKind:
        raise NotImplementedError

    # -- traversal ---------------------------------------------------------- #
    def extract_symbols(self, root: Node, imports: tuple[ImportRef, ...]) -> tuple[SymbolNode, ...]:
        """Iterative pre-order walk, so symbols come out in source order."""
        symbols: list[SymbolNode] = []
        stack: list[tuple[Node, tuple[tuple[str, SymbolKind], ...]]] = [(root, ())]
        while stack:
            node, scope = stack.pop()
            child_scope = scope
            if node is not root and self.is_target(node):
                symbols.append(self.build_symbol(node, scope, imports))
                child_scope = scope + ((self.symbol_name(node), self.symbol_kind(node, scope)),)
            stack.extend((child, child_scope) for child in reversed(node.named_children))
        return tuple(symbols)

    def walk_scope(self, root: Node | None) -> Iterator[tuple[Node, bool]]:
        """Yield ``(node, nested)`` for descendants of ``root`` in the same scope.

        Named definitions (separate chunks) are pruned entirely. ``nested`` is
        True inside anonymous functions (lambdas, callbacks): their calls still
        count for the enclosing chunk, but their returns and locals do not.
        """
        if root is None:
            return
        stack = [(child, False) for child in reversed(root.children)]
        while stack:
            node, nested = stack.pop()
            if self.is_target(node):
                continue
            yield node, nested
            child_nested = nested or node.type in self.anonymous_fn_types
            stack.extend((child, child_nested) for child in reversed(node.children))

    # -- text helpers ------------------------------------------------------- #
    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.slice(node.start_byte, node.end_byte)

    def slice(self, start: int, end: int) -> str:
        return self.src[start:end].decode("utf-8", errors="replace").replace("\r\n", "\n")

    def indent_of(self, start_byte: int) -> str:
        line_start = self.src.rfind(b"\n", 0, start_byte) + 1
        prefix = self.slice(line_start, start_byte)
        return prefix if not prefix.strip() else ""

    def block(self, start_byte: int, end_byte: int) -> str:
        """Source text for a statement range, dedented as a standalone block."""
        indent = self.indent_of(start_byte)
        return textwrap.dedent(indent + self.slice(start_byte, end_byte)).strip("\n")

    def callee_name(self, node: Node | None) -> str:
        """Normalize a callee to a dotted path, eliding call arguments.

        ``hashlib.sha256(x).hexdigest`` -> ``hashlib.sha256().hexdigest``;
        receivers that are not names (literals, parenthesized expressions)
        are dropped, leaving a leading dot: ``[1, 2].map`` -> ``.map``.
        """
        if node is None:
            return ""
        if node.type in self.callee_name_types:
            return self.text(node)
        if node.type in self.callee_member_types:
            prop = node.child_by_field_name(self.callee_property_field)
            return f"{self.callee_name(node.child_by_field_name('object'))}.{self.text(prop)}"
        if node.type in self.callee_call_types:
            fn = self.callee_name(node.child_by_field_name("function"))
            return f"{fn}()" if fn else ""
        return ""

    def type_hint(self, value: Node | None, annotation: Node | None) -> str | None:
        """Static type evidence for an assignment: annotation text, else the callee it was built from."""
        if annotation is not None:
            return self.text(annotation).lstrip(":").strip() or None
        while value is not None and value.type in {"await", "await_expression", "parenthesized_expression"}:
            value = value.named_children[0] if value.named_child_count else None
        if value is None:
            return None
        if value.type in self.callee_call_types:
            fn = value.child_by_field_name("function")
        elif value.type == "new_expression":
            fn = value.child_by_field_name("constructor")
        else:
            return None
        return self.callee_name(fn) or None

    def make_id(self, qualified_name: str, start_line: int) -> str:
        symbol_id = f"{self.file_path}::{qualified_name}"
        if symbol_id in self._seen_ids:
            symbol_id = f"{symbol_id}@L{start_line}"
        self._seen_ids.add(symbol_id)
        return symbol_id

    def assemble(
        self,
        *,
        node: Node,
        span_start: Node,
        span_end: Node,
        scope: tuple[tuple[str, SymbolKind], ...],
        imports: tuple[ImportRef, ...],
        signature: str,
        decorators: tuple[str, ...],
        docstring: str,
        body: str,
        bases: tuple[str, ...],
        call_sites: tuple[CallSite, ...],
        details: ScopeDetails,
    ) -> SymbolNode:
        name = self.symbol_name(node)
        names = [n for n, _ in scope]
        qualified_name = ".".join([*names, name])
        enclosing_class = None
        for depth in range(len(scope), 0, -1):
            if scope[depth - 1][1] == "class":
                enclosing_class = ".".join(names[:depth])
                break
        start_line = span_start.start_point[0] + 1
        return SymbolNode(
            symbol_id=self.make_id(qualified_name, start_line),
            qualified_name=qualified_name,
            name=name,
            kind=self.symbol_kind(node, scope),
            language=self.language,
            file_path=self.file_path,
            start_line=start_line,
            end_line=max(start_line, _end_line(span_end)),
            start_byte=span_start.start_byte,
            end_byte=span_end.end_byte,
            signature=signature,
            decorators=decorators,
            docstring=docstring,
            body=body,
            parent_scope=".".join(names) or None,
            enclosing_class=enclosing_class,
            bases=bases,
            imports=imports,
            calls=_dedupe([site.callee for site in call_sites]),
            ast_scope_details=details,
            call_sites=call_sites,
        )


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #

_PY_DEFS = frozenset({"function_definition", "class_definition"})
_PY_TARGET_PATTERNS = frozenset(
    {"pattern_list", "tuple_pattern", "list_pattern", "list_splat_pattern", "tuple", "list"}
)


class _PythonExtractor(_Extractor):
    anonymous_fn_types = frozenset({"lambda"})
    callee_name_types = frozenset({"identifier"})
    callee_member_types = frozenset({"attribute"})
    callee_property_field = "attribute"
    callee_call_types = frozenset({"call"})

    def is_target(self, node: Node) -> bool:
        return node.type in _PY_DEFS

    def symbol_name(self, node: Node) -> str:
        return self.text(node.child_by_field_name("name"))

    def symbol_kind(self, node: Node, scope: tuple[tuple[str, SymbolKind], ...]) -> SymbolKind:
        if node.type == "class_definition":
            return "class"
        return "method" if scope and scope[-1][1] == "class" else "function"

    def extract_imports(self, root: Node) -> tuple[ImportRef, ...]:
        refs: list[ImportRef] = []
        for node in self.walk_all(root):
            line = node.start_point[0] + 1
            if node.type == "import_statement":
                for item in node.children_by_field_name("name"):
                    module, alias = self._aliased(item)
                    refs.append(ImportRef(module, None, alias, line))
            elif node.type == "import_from_statement":
                module = self.text(node.child_by_field_name("module_name"))
                names = node.children_by_field_name("name")
                if not names and any(c.type == "wildcard_import" for c in node.children):
                    refs.append(ImportRef(module, "*", None, line))
                for item in names:
                    name, alias = self._aliased(item)
                    refs.append(ImportRef(module, name, alias, line))
        return tuple(refs)

    def walk_all(self, root: Node) -> Iterator[Node]:
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.named_children))

    def _aliased(self, node: Node) -> tuple[str, str | None]:
        if node.type == "aliased_import":
            return (
                self.text(node.child_by_field_name("name")),
                self.text(node.child_by_field_name("alias")),
            )
        return self.text(node), None

    def build_symbol(
        self, node: Node, scope: tuple[tuple[str, SymbolKind], ...], imports: tuple[ImportRef, ...]
    ) -> SymbolNode:
        wrapper = node.parent if node.parent and node.parent.type == "decorated_definition" else node
        decorators = tuple(_collapse(self.text(c)) for c in wrapper.children if c.type == "decorator")
        body = node.child_by_field_name("body")
        docstring_stmt = self._docstring_stmt(body)
        is_class = node.type == "class_definition"

        bases: tuple[str, ...] = ()
        if is_class:
            superclasses = node.child_by_field_name("superclasses")
            if superclasses is not None:
                bases = tuple(
                    self.text(c)
                    for c in superclasses.named_children
                    if c.type not in {"keyword_argument", "comment"}
                )

        params = () if is_class else self._params(node.child_by_field_name("parameters"))
        return_type = node.child_by_field_name("return_type")
        details = self._scope_details(body, params, self.text(return_type) or None)
        return self.assemble(
            node=node,
            span_start=wrapper,
            span_end=wrapper,
            scope=scope,
            imports=imports,
            signature=self.signature(node),
            decorators=decorators,
            docstring=self._docstring(docstring_stmt),
            body=self._class_skeleton(body, docstring_stmt)
            if is_class
            else self._body_text(body, docstring_stmt),
            bases=bases,
            call_sites=self._call_sites(body),
            details=details,
        )

    def signature(self, node: Node) -> str:
        colon = next((c for c in node.children if c.type == ":"), None)
        end = colon.start_byte if colon is not None else node.child_by_field_name("body").start_byte
        return _collapse(self.slice(node.start_byte, end))

    def _statements(self, body: Node | None, docstring_stmt: Node | None) -> list[Node]:
        if body is None:
            return []
        return [c for c in body.named_children if c != docstring_stmt]

    def _docstring_stmt(self, body: Node | None) -> Node | None:
        if body is None:
            return None
        first = next((c for c in body.named_children if c.type != "comment"), None)
        if (
            first is not None
            and first.type == "expression_statement"
            and first.named_child_count == 1
            and first.named_children[0].type == "string"
        ):
            return first
        return None

    def _docstring(self, stmt: Node | None) -> str:
        if stmt is None:
            return ""
        string = stmt.named_children[0]
        content = "".join(self.text(c) for c in string.named_children if c.type == "string_content")
        return inspect.cleandoc(content)

    def _body_text(self, body: Node | None, docstring_stmt: Node | None) -> str:
        stmts = self._statements(body, docstring_stmt)
        if not stmts:
            return ""
        return self.block(stmts[0].start_byte, stmts[-1].end_byte)

    def _class_skeleton(self, body: Node | None, docstring_stmt: Node | None) -> str:
        """Class body with member bodies elided (``def m(self): ...``).

        Members are their own chunks, so repeating their bodies here would
        duplicate tokens and bias both the sparse and dense pillars.
        """
        lines: list[str] = []
        for stmt in self._statements(body, docstring_stmt):
            definition = stmt
            decorators: list[str] = []
            if stmt.type == "decorated_definition":
                definition = stmt.child_by_field_name("definition")
                decorators = [_collapse(self.text(c)) for c in stmt.children if c.type == "decorator"]
            indent = self.indent_of(stmt.start_byte)
            if definition is not None and definition.type in _PY_DEFS:
                lines.extend(indent + d for d in decorators)
                lines.append(f"{indent}{self.signature(definition)}: ...")
            else:
                lines.append(indent + self.slice(stmt.start_byte, stmt.end_byte))
        return textwrap.dedent("\n".join(lines)).strip("\n")

    def _params(self, params: Node | None) -> tuple[Parameter, ...]:
        if params is None:
            return ()
        result = []
        for p in params.named_children:
            if p.type in {"identifier", "list_splat_pattern", "dictionary_splat_pattern"}:
                result.append(Parameter(self.text(p)))
            elif p.type == "typed_parameter":
                result.append(
                    Parameter(
                        self.text(p.named_children[0]),
                        self.text(p.child_by_field_name("type")) or None,
                    )
                )
            elif p.type in {"default_parameter", "typed_default_parameter"}:
                result.append(
                    Parameter(
                        self.text(p.child_by_field_name("name")),
                        self.text(p.child_by_field_name("type")) or None,
                        self.text(p.child_by_field_name("value")) or None,
                    )
                )
        return tuple(result)

    def _call_sites(self, body: Node | None) -> tuple[CallSite, ...]:
        sites = []
        for node, _ in self.walk_scope(body):
            if node.type == "call":
                name = self.callee_name(node.child_by_field_name("function"))
                if name:
                    sites.append(CallSite(name, node.start_point[0] + 1))
        return tuple(sites)

    def _target_names(self, node: Node | None) -> list[str]:
        if node is None:
            return []
        if node.type == "identifier":
            return [self.text(node)]
        if node.type in _PY_TARGET_PATTERNS:
            return [n for c in node.named_children for n in self._target_names(c)]
        return []

    def _scope_details(
        self, body: Node | None, params: tuple[Parameter, ...], return_type: str | None
    ) -> ScopeDetails:
        local_names: list[str] = []
        raises: list[str] = []
        returns: list[str] = []
        type_hints: list[tuple[str, str]] = []
        for node, nested in self.walk_scope(body):
            if nested:
                continue
            if node.type in {"assignment", "augmented_assignment", "for_statement"}:
                left = node.child_by_field_name("left")
                local_names += self._target_names(left)
                if (
                    node.type == "assignment"
                    and left is not None
                    and left.type in {"identifier", "attribute"}
                ):
                    hint = self.type_hint(node.child_by_field_name("right"), node.child_by_field_name("type"))
                    if hint:
                        type_hints.append(("".join(self.text(left).split()), hint))
            elif node.type == "named_expression":
                local_names += self._target_names(node.child_by_field_name("name"))
            elif node.type == "as_pattern":
                alias = node.child_by_field_name("alias")
                if alias is not None:
                    local_names += [n for c in alias.named_children for n in self._target_names(c)]
            elif node.type == "raise_statement" and node.named_child_count:
                exc = node.named_children[0]
                target = exc.child_by_field_name("function") if exc.type == "call" else exc
                raises.append(_collapse(self.text(target)))
            elif node.type == "return_statement" and node.named_child_count:
                returns.append(_collapse(self.text(node.named_children[0]))[:_RETURN_EXPR_MAX_CHARS])
        param_names = {p.name.lstrip("*") for p in params}
        return ScopeDetails(
            params=params,
            locals=_dedupe([n for n in local_names if n not in param_names]),
            raises=_dedupe(raises),
            returns=_dedupe(returns),
            return_type=return_type,
            type_hints=tuple(dict.fromkeys(type_hints)),
        )


# --------------------------------------------------------------------------- #
# TypeScript / TSX
# --------------------------------------------------------------------------- #

_TS_DECLS = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "abstract_class_declaration",
    }
)
_TS_CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
_TS_FN_EXPRS = frozenset({"arrow_function", "function_expression", "generator_function", "class"})
_TS_ANON_FNS = frozenset({"arrow_function", "function_expression", "generator_function", "method_definition"})


class _TypeScriptExtractor(_Extractor):
    anonymous_fn_types = _TS_ANON_FNS
    callee_name_types = frozenset({"identifier", "this", "super"})
    callee_member_types = frozenset({"member_expression"})
    callee_property_field = "property"
    callee_call_types = frozenset({"call_expression"})

    def is_target(self, node: Node) -> bool:
        if node.type in _TS_DECLS:
            return True
        parent = node.parent
        if parent is None:
            return False
        if node.type == "method_definition":
            return parent.type == "class_body"
        if node.type in _TS_FN_EXPRS and parent.child_by_field_name("value") == node:
            if parent.type == "variable_declarator":
                name = parent.child_by_field_name("name")
                return name is not None and name.type == "identifier"
            return parent.type == "public_field_definition"
        return False

    def _declaration(self, node: Node) -> Node:
        """The node that owns the name: declarator/field for function expressions."""
        parent = node.parent
        if (
            node.type in _TS_FN_EXPRS
            and parent
            and parent.type in {"variable_declarator", "public_field_definition"}
        ):
            return parent
        return node

    def symbol_name(self, node: Node) -> str:
        name = self._declaration(node).child_by_field_name("name")
        return self.text(name) if name is not None else "default"

    def symbol_kind(self, node: Node, scope: tuple[tuple[str, SymbolKind], ...]) -> SymbolKind:
        if node.type in _TS_CLASSES:
            return "class"
        if node.type == "method_definition" or self._declaration(node).type == "public_field_definition":
            return "method"
        return "function"

    def extract_imports(self, root: Node) -> tuple[ImportRef, ...]:
        refs: list[ImportRef] = []
        for node in root.named_children:
            if node.type != "import_statement":
                continue
            line = node.start_point[0] + 1
            source = node.child_by_field_name("source")
            module = self.text(source).strip("'\"`")
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            if clause is None:
                refs.append(ImportRef(module, None, None, line))
                continue
            for part in clause.named_children:
                if part.type == "identifier":
                    refs.append(ImportRef(module, "default", self.text(part), line))
                elif part.type == "namespace_import":
                    ident = next((c for c in part.named_children if c.type == "identifier"), None)
                    refs.append(ImportRef(module, "*", self.text(ident) or None, line))
                elif part.type == "named_imports":
                    for spec in part.named_children:
                        if spec.type == "import_specifier":
                            alias = spec.child_by_field_name("alias")
                            refs.append(
                                ImportRef(
                                    module,
                                    self.text(spec.child_by_field_name("name")),
                                    self.text(alias) or None,
                                    line,
                                )
                            )
        return tuple(refs)

    def _span(self, node: Node) -> tuple[Node, Node, Node, list[Node]]:
        """Return ``(span_start, span_end, signature_anchor, decorators)``."""
        decl = self._declaration(node)
        decorators = [c for c in decl.children if c.type == "decorator"]
        if decl.parent is not None and decl.parent.type == "class_body":
            # Class members: decorators are preceding siblings in class_body.
            sibling = decl.prev_named_sibling
            leading = []
            while sibling is not None and sibling.type == "decorator":
                leading.append(sibling)
                sibling = sibling.prev_named_sibling
            decorators = list(reversed(leading)) + decorators
            start = decorators[0] if decorators else decl
            return start, decl, decl, decorators
        wrapper = decl
        if decl.type == "variable_declarator":
            container = decl.parent
            declarators = [c for c in container.named_children if c.type == "variable_declarator"]
            if len(declarators) == 1:
                wrapper = container
        if wrapper.parent is not None and wrapper.parent.type == "export_statement":
            wrapper = wrapper.parent
            decorators = [c for c in wrapper.children if c.type == "decorator"] + decorators
        return wrapper, wrapper, wrapper, decorators

    def _signature(self, anchor: Node, body: Node | None) -> str:
        first = next((c for c in anchor.children if c.type not in {"decorator", "comment"}), anchor)
        end = body.start_byte if body is not None else anchor.end_byte
        return _collapse(self.slice(first.start_byte, end)).rstrip("{;").strip()

    def _jsdoc(self, span_start: Node) -> str:
        prev = span_start.prev_named_sibling
        if prev is None or prev.type != "comment":
            return ""
        text = self.text(prev)
        if not text.startswith("/**") or prev.end_point[0] < span_start.start_point[0] - 1:
            return ""
        lines = [re.sub(r"^\s*\*\s?", "", line) for line in text[3:-2].splitlines()]
        return inspect.cleandoc("\n".join(lines)).strip()

    def build_symbol(
        self, node: Node, scope: tuple[tuple[str, SymbolKind], ...], imports: tuple[ImportRef, ...]
    ) -> SymbolNode:
        span_start, span_end, anchor, decorator_nodes = self._span(node)
        body = node.child_by_field_name("body")
        is_class = node.type in _TS_CLASSES

        bases: list[str] = []
        if is_class:
            heritage = next((c for c in node.named_children if c.type == "class_heritage"), None)
            for clause in heritage.named_children if heritage is not None else []:
                bases += [self.text(c) for c in clause.named_children if c.type != "type_arguments"]

        return_type = node.child_by_field_name("return_type")
        return self.assemble(
            node=node,
            span_start=span_start,
            span_end=span_end,
            scope=scope,
            imports=imports,
            signature=self._signature(anchor, body),
            decorators=tuple(_collapse(self.text(d)) for d in decorator_nodes),
            docstring=self._jsdoc(span_start),
            body=self._class_skeleton(body) if is_class else self._body_text(body),
            bases=tuple(bases),
            call_sites=self._call_sites(body),
            details=self._scope_details(
                node,
                body,
                () if is_class else self._params(node.child_by_field_name("parameters")),
                self.text(return_type).lstrip(":").strip() or None,
            ),
        )

    def _body_text(self, body: Node | None) -> str:
        if body is None:
            return ""
        if body.type != "statement_block":  # expression-bodied arrow function
            return self.block(body.start_byte, body.end_byte)
        stmts = body.named_children
        if not stmts:
            return ""
        return self.block(stmts[0].start_byte, stmts[-1].end_byte)

    def _class_skeleton(self, body: Node | None) -> str:
        lines: list[str] = []
        for member in body.named_children if body is not None else []:
            indent = self.indent_of(member.start_byte)
            value = member.child_by_field_name("value") if member.type == "public_field_definition" else None
            fn = member if member.type == "method_definition" else value
            if fn is not None and self.is_target(fn):
                fn_body = fn.child_by_field_name("body")
                lines.append(f"{indent}{self._signature(member, fn_body)} {{ ... }}")
            else:
                lines.append(indent + self.slice(member.start_byte, member.end_byte))
        return textwrap.dedent("\n".join(lines)).strip("\n")

    def _params(self, params: Node | None) -> tuple[Parameter, ...]:
        result = []
        for p in params.named_children if params is not None else []:
            if p.type not in {"required_parameter", "optional_parameter"}:
                continue
            annotation = self.text(p.child_by_field_name("type")).lstrip(":").strip()
            result.append(
                Parameter(
                    self.text(p.child_by_field_name("pattern")),
                    annotation or None,
                    self.text(p.child_by_field_name("value")) or None,
                )
            )
        return tuple(result)

    def _call_sites(self, body: Node | None) -> tuple[CallSite, ...]:
        sites = []
        for node, _ in self.walk_scope(body):
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
            elif node.type == "new_expression":
                fn = node.child_by_field_name("constructor")
            else:
                continue
            name = self.callee_name(fn)
            if name:
                sites.append(CallSite(name, node.start_point[0] + 1))
        return tuple(sites)

    def _pattern_names(self, node: Node | None) -> list[str]:
        if node is None:
            return []
        if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
            return [self.text(node)]
        if node.type == "pair_pattern":
            return self._pattern_names(node.child_by_field_name("value"))
        if node.type in {"object_assignment_pattern", "assignment_pattern"}:
            return self._pattern_names(node.child_by_field_name("left"))
        if node.type in {"object_pattern", "array_pattern", "rest_pattern"}:
            return [n for c in node.named_children for n in self._pattern_names(c)]
        return []

    def _scope_details(
        self, node: Node, body: Node | None, params: tuple[Parameter, ...], return_type: str | None
    ) -> ScopeDetails:
        local_names: list[str] = []
        raises: list[str] = []
        returns: list[str] = []
        type_hints: list[tuple[str, str]] = []
        if body is not None and body.type not in {"statement_block", "class_body"}:
            returns.append(_collapse(self.text(body))[:_RETURN_EXPR_MAX_CHARS])
        for child, nested in self.walk_scope(body):
            if nested:
                continue
            if child.type == "variable_declarator":
                name = child.child_by_field_name("name")
                local_names += self._pattern_names(name)
                hint = self.type_hint(child.child_by_field_name("value"), child.child_by_field_name("type"))
                if hint and name is not None and name.type == "identifier":
                    type_hints.append((self.text(name), hint))
            elif child.type == "assignment_expression":
                left = child.child_by_field_name("left")
                hint = self.type_hint(child.child_by_field_name("right"), None)
                if hint and left is not None and left.type in {"identifier", "member_expression"}:
                    type_hints.append(("".join(self.text(left).split()), hint))
            elif child.type == "public_field_definition" and node.type in _TS_CLASSES:
                value = child.child_by_field_name("value")
                if value is not None and self.is_target(value):
                    continue
                field_name = self.text(child.child_by_field_name("name"))
                local_names.append(field_name)
                hint = self.type_hint(value, child.child_by_field_name("type"))
                if hint:
                    type_hints.append((f"this.{field_name}", hint))
            elif child.type == "throw_statement" and child.named_child_count:
                exc = child.named_children[0]
                target = exc.child_by_field_name("constructor") if exc.type == "new_expression" else exc
                raises.append(_collapse(self.text(target)))
            elif child.type == "return_statement" and child.named_child_count:
                returns.append(_collapse(self.text(child.named_children[0]))[:_RETURN_EXPR_MAX_CHARS])
        return ScopeDetails(
            params=params,
            locals=_dedupe(local_names),
            raises=_dedupe(raises),
            returns=_dedupe(returns),
            return_type=return_type,
            type_hints=tuple(dict.fromkeys(type_hints)),
        )
