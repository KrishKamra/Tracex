from pathlib import Path

import pytest

from app.nlp import serialize_chunk, tokenize
from app.parser import ASTEngine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def symbols():
    engine = ASTEngine()
    parsed = [
        engine.parse_file(FIXTURES / name, FIXTURES) for name in ("sample_service.py", "sample_router.ts")
    ]
    return {s.qualified_name: s for f in parsed for s in f.symbols}


def test_serialize_python_method(symbols):
    assert serialize_chunk(symbols["WebhookReceiver.validate_signature"]) == (
        "[DOC] Return True when the HMAC signature matches the payload.\n"
        "[SIG] @staticmethod\n"
        "@retry(times=3)\n"
        "def validate_signature(payload: bytes, signature: str) -> bool\n"
        "[CODE] digest = hashlib.sha256(payload).hexdigest()\n"
        "if digest != signature:\n"
        '    raise SignatureError("bad signature")\n'
        "return True"
    )


def test_serialize_without_docstring_keeps_empty_doc_segment(symbols):
    assert serialize_chunk(symbols["WebhookReceiver.__init__"]) == (
        "[DOC]\n"
        "[SIG] def __init__(self, secret: str, timeout: float = 2.5) -> None\n"
        "[CODE] self.secret = secret\n"
        "self.timeout = timeout"
    )


def test_serialize_with_context_header(symbols):
    assert serialize_chunk(symbols["parseEvent"], include_context=True) == (
        "[FILE] sample_router.ts\n"
        "[SCOPE] parseEvent (function)\n"
        "[DOC]\n"
        "[SIG] export function parseEvent(raw: string): StripeEvent\n"
        "[CODE] return JSON.parse(raw) as StripeEvent;"
    )


def test_serialized_chunk_tokenizes_without_tag_noise(symbols):
    tokens = tokenize(serialize_chunk(symbols["check_limit"], include_context=True))
    assert {"check_limit", "check", "limit", "fetch_usage", "fetch", "usage"} <= set(tokens)
    assert not {"doc", "sig", "code", "file", "scope"} & set(tokens)
