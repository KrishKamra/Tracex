from pathlib import Path

import pytest

from app.parser import ASTEngine, ImportRef, Parameter, iter_source_files

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def engine() -> ASTEngine:
    return ASTEngine()


@pytest.fixture(scope="module")
def py_file(engine):
    return engine.parse_file(FIXTURES / "sample_service.py", FIXTURES)


@pytest.fixture(scope="module")
def ts_file(engine):
    return engine.parse_file(FIXTURES / "sample_router.ts", FIXTURES)


def by_name(parsed):
    return {s.qualified_name: s for s in parsed.symbols}


def source_lines(name):
    return (FIXTURES / name).read_text().splitlines()


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #

PY_SPANS = {
    "WebhookReceiver": ("class", 7, 35),
    "WebhookReceiver.__init__": ("method", 12, 14),
    "WebhookReceiver.validate_signature": ("method", 16, 23),
    "WebhookReceiver.handle": ("method", 25, 35),
    "WebhookReceiver.handle._audit": ("function", 30, 31),
    "check_limit": ("function", 38, 45),
}


def test_python_symbols_in_source_order(py_file):
    assert [s.qualified_name for s in py_file.symbols] == list(PY_SPANS)
    assert py_file.language == "python"
    assert not py_file.has_error


@pytest.mark.parametrize("qualified_name", list(PY_SPANS))
def test_python_kinds_and_coordinates(py_file, qualified_name):
    kind, start, end = PY_SPANS[qualified_name]
    symbol = by_name(py_file)[qualified_name]
    assert (symbol.kind, symbol.start_line, symbol.end_line) == (kind, start, end)


def test_python_span_boundaries_match_source_text(py_file):
    lines = source_lines("sample_service.py")
    symbols = by_name(py_file)
    validate = symbols["WebhookReceiver.validate_signature"]
    assert lines[validate.start_line - 1].strip() == "@staticmethod"
    assert lines[validate.end_line - 1].strip() == "return True"
    check = symbols["check_limit"]
    assert lines[check.start_line - 1].startswith("def check_limit")
    assert lines[check.end_line - 1].strip() == "return current + amount <= limit"
    source = (FIXTURES / "sample_service.py").read_bytes()
    assert source[check.start_byte : check.end_byte].startswith(b"def check_limit")


def test_python_decorated_method(py_file):
    symbol = by_name(py_file)["WebhookReceiver.validate_signature"]
    assert symbol.decorators == ("@staticmethod", "@retry(times=3)")
    assert symbol.signature == "def validate_signature(payload: bytes, signature: str) -> bool"
    assert symbol.docstring == "Return True when the HMAC signature matches the payload."
    assert symbol.enclosing_class == "WebhookReceiver"
    assert symbol.parent_scope == "WebhookReceiver"
    assert symbol.symbol_id == "sample_service.py::WebhookReceiver.validate_signature"


def test_python_body_excludes_docstring_and_is_dedented(py_file):
    symbol = by_name(py_file)["WebhookReceiver.validate_signature"]
    assert symbol.body == (
        "digest = hashlib.sha256(payload).hexdigest()\n"
        "if digest != signature:\n"
        '    raise SignatureError("bad signature")\n'
        "return True"
    )


def test_python_multiline_docstring_is_cleaned(py_file):
    assert by_name(py_file)["check_limit"].docstring == (
        "Check whether the account is below its spending limit.\n\n"
        "Args:\n    account_id: The billing account."
    )


def test_python_scope_details(py_file):
    symbols = by_name(py_file)
    validate = symbols["WebhookReceiver.validate_signature"]
    assert validate.calls == ("hashlib.sha256().hexdigest", "hashlib.sha256", "SignatureError")
    assert validate.ast_scope_details.raises == ("SignatureError",)
    assert validate.ast_scope_details.returns == ("True",)
    assert validate.ast_scope_details.locals == ("digest",)
    assert validate.ast_scope_details.return_type == "bool"

    init = symbols["WebhookReceiver.__init__"].ast_scope_details
    assert init.params == (
        Parameter("self"),
        Parameter("secret", "str"),
        Parameter("timeout", "float", "2.5"),
    )
    assert init.locals == ()  # attribute assignments are not locals

    check = symbols["check_limit"].ast_scope_details
    assert check.locals == ("current", "limit")  # tuple unpacking


def test_python_nested_function_is_own_chunk(py_file):
    symbols = by_name(py_file)
    handle = symbols["WebhookReceiver.handle"]
    audit = symbols["WebhookReceiver.handle._audit"]
    # log_entry is called inside _audit, so it belongs to _audit only.
    assert handle.calls == ("enforce_limit", "_audit", "sum")
    assert audit.calls == ("log_entry",)
    assert audit.parent_scope == "WebhookReceiver.handle"
    assert audit.enclosing_class == "WebhookReceiver"
    assert handle.ast_scope_details.locals == ("item", "total")
    assert [p.name for p in handle.ast_scope_details.params] == ["self", "event", "*args", "**kwargs"]


def test_python_class_chunk(py_file):
    cls = by_name(py_file)["WebhookReceiver"]
    assert cls.signature == "class WebhookReceiver(BaseReceiver, metaclass=Registry)"
    assert cls.bases == ("BaseReceiver",)
    assert cls.docstring == "Receives and validates incoming billing webhooks."
    assert cls.ast_scope_details.locals == ("max_retries",)
    assert cls.body == (
        "max_retries = 3\n"
        "def __init__(self, secret: str, timeout: float = 2.5) -> None: ...\n"
        "@staticmethod\n"
        "@retry(times=3)\n"
        "def validate_signature(payload: bytes, signature: str) -> bool: ...\n"
        "async def handle(self, event: dict[str, Any], *args, **kwargs): ..."
    )


def test_python_imports(py_file):
    assert py_file.imports == (
        ImportRef("hashlib", None, None, 2),
        ImportRef("typing", "Any", None, 3),
        ImportRef(".limits", "check_limit", "enforce_limit", 4),
    )
    assert all(s.imports == py_file.imports for s in py_file.symbols)


# --------------------------------------------------------------------------- #
# TypeScript
# --------------------------------------------------------------------------- #

TS_SPANS = {
    "PaymentRouter": ("class", 8, 34),
    "PaymentRouter.constructor": ("method", 12, 14),
    "PaymentRouter.handleStripe": ("method", 17, 29),
    "PaymentRouter.verifySignature": ("method", 31, 33),
    "checkLimit": ("function", 36, 39),
    "parseEvent": ("function", 41, 43),
    "double": ("function", 45, 45),
}


def test_typescript_symbols_in_source_order(ts_file):
    # Interfaces and their method signatures are not chunks.
    assert [s.qualified_name for s in ts_file.symbols] == list(TS_SPANS)
    assert not ts_file.has_error


@pytest.mark.parametrize("qualified_name", list(TS_SPANS))
def test_typescript_kinds_and_coordinates(ts_file, qualified_name):
    kind, start, end = TS_SPANS[qualified_name]
    symbol = by_name(ts_file)[qualified_name]
    assert (symbol.kind, symbol.start_line, symbol.end_line) == (kind, start, end)


def test_typescript_decorated_exported_class(ts_file):
    cls = by_name(ts_file)["PaymentRouter"]
    lines = source_lines("sample_router.ts")
    assert lines[cls.start_line - 1] == '@Controller("/webhooks")'
    assert lines[cls.end_line - 1] == "}"
    assert cls.decorators == ('@Controller("/webhooks")',)
    assert cls.signature == "export class PaymentRouter extends BaseRouter implements Router"
    assert cls.docstring == "Routes incoming payment webhooks."
    assert cls.bases == ("BaseRouter", "Router")
    assert cls.ast_scope_details.locals == ("retries",)  # function-valued fields excluded


def test_typescript_method_with_sibling_decorator_and_jsdoc(ts_file):
    method = by_name(ts_file)["PaymentRouter.handleStripe"]
    assert method.decorators == ('@Post("/stripe")',)
    assert method.docstring == "Verify and dispatch a Stripe event."
    assert method.signature == "async handleStripe(req: Request, res?: Res): Promise<void>"
    assert method.enclosing_class == "PaymentRouter"
    details = method.ast_scope_details
    assert details.params == (Parameter("req", "Request"), Parameter("res", "Res"))
    assert details.return_type == "Promise<void>"
    assert details.raises == ("SignatureError",)
    assert details.locals == ("type", "data", "verified")  # `ignored` lives in a callback
    assert details.returns == ()  # the callback's return is not the method's
    assert method.calls == ("this.verifySignature", "SignatureError", ".forEach", "track", "dispatchEvent")
    assert method.body.splitlines()[0] == "const { type, data } = req.body;"


def test_typescript_arrow_functions(ts_file):
    symbols = by_name(ts_file)
    field = symbols["PaymentRouter.verifySignature"]
    assert field.signature == "verifySignature = (sig: string): boolean =>"
    assert field.calls == ("crypto.timingSafeEqual", "Buffer.from")

    check = symbols["checkLimit"]
    assert check.signature == (
        "export const checkLimit = async (accountId: string, amount = 0): Promise<boolean> =>"
    )
    assert check.ast_scope_details.params[1] == Parameter("amount", None, "0")
    assert check.ast_scope_details.locals == ("usage",)

    double = symbols["double"]
    assert double.body == "x * 2"
    assert double.ast_scope_details.returns == ("x * 2",)


def test_typescript_class_skeleton(ts_file):
    assert by_name(ts_file)["PaymentRouter"].body == (
        "private readonly retries: number = 3\n"
        "constructor(private readonly secret: string) { ... }\n"
        "/** Verify and dispatch a Stripe event. */\n"
        '@Post("/stripe")\n'
        "async handleStripe(req: Request, res?: Res): Promise<void> { ... }\n"
        "verifySignature = (sig: string): boolean => { ... }"
    )


def test_typescript_imports(ts_file):
    assert ts_file.imports == (
        ImportRef("express", "Request", None, 1),
        ImportRef("express", "Response", "Res", 1),
        ImportRef("crypto", "*", "crypto", 2),
        ImportRef("stripe", "default", "Stripe", 3),
    )


# --------------------------------------------------------------------------- #
# Engine behaviour
# --------------------------------------------------------------------------- #


def test_duplicate_symbols_get_unique_ids(engine):
    source = (
        "class A:\n"
        "    @property\n"
        "    def x(self):\n"
        "        return 1\n"
        "\n"
        "    @x.setter\n"
        "    def x(self, value):\n"
        "        pass\n"
    )
    ids = [s.symbol_id for s in engine.parse_source(source, "python", "a.py").symbols]
    assert ids == ["a.py::A", "a.py::A.x", "a.py::A.x@L6"]


def test_crlf_and_single_line_definitions(engine):
    source = b"def f(): return 1\r\n\r\ndef g(a,\r\n      b):\r\n    return a\r\n"
    f, g = engine.parse_source(source, "python", "crlf.py").symbols
    assert (f.start_line, f.end_line, f.body) == (1, 1, "return 1")
    assert (g.start_line, g.end_line) == (3, 5)
    assert g.signature == "def g(a, b)"
    assert "\r" not in g.body


def test_tsx_component(engine):
    source = "export function Card({ title }: Props) {\n  return <div>{title}</div>;\n}\n"
    (card,) = engine.parse_source(source, "tsx", "Card.tsx").symbols
    assert (card.name, card.kind, card.start_line, card.end_line) == ("Card", "function", 1, 3)
    assert card.ast_scope_details.returns == ("<div>{title}</div>",)


def test_syntax_errors_are_tolerated(engine):
    parsed = engine.parse_source("def ok():\n    return 1\n\ndef broken(:\n", "python", "x.py")
    assert parsed.has_error
    assert parsed.symbols[0].qualified_name == "ok"


def test_parsing_is_deterministic(engine):
    first = engine.parse_file(FIXTURES / "sample_router.ts", FIXTURES)
    second = ASTEngine().parse_file(FIXTURES / "sample_router.ts", FIXTURES)
    assert first == second


def test_repository_walk_skips_ignored_dirs(engine, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.py").write_text("def b():\n    pass\n")
    (tmp_path / "a.ts").write_text("function a() {}\n")
    (tmp_path / "node_modules" / "dep").mkdir(parents=True)
    (tmp_path / "node_modules" / "dep" / "index.ts").write_text("function dep() {}\n")
    (tmp_path / "README.md").write_text("# not code\n")

    assert [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)] == [
        "a.ts",
        "src/b.py",
    ]
    parsed = engine.parse_repository(tmp_path)
    assert [s.symbol_id for f in parsed for s in f.symbols] == ["a.ts::a", "src/b.py::b"]


def test_unsupported_extension_raises(engine, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("hi")
    with pytest.raises(ValueError):
        engine.parse_file(path)
