import pytest

from app.nlp import CodeTokenizer, split_identifier, tokenize


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("check_limit", ["check", "limit"]),
        ("WebhookReceiver", ["webhook", "receiver"]),
        ("validateWebhookSignature", ["validate", "webhook", "signature"]),
        ("HTTPServer", ["http", "server"]),
        ("parseHTTPResponse2xx", ["parse", "http", "response", "2", "xx"]),
        ("MAX_RETRY_COUNT", ["max", "retry", "count"]),
        ("__init__", ["init"]),
        ("$scope", ["scope"]),
        ("utf8", ["utf", "8"]),
        ("naïve_café", ["naïve", "café"]),
    ],
)
def test_split_identifier(identifier, expected):
    assert split_identifier(identifier) == expected


def test_split_identifier_can_preserve_case():
    assert split_identifier("WebhookReceiver", lowercase=False) == ["Webhook", "Receiver"]


def test_tokenize_preserves_original_identifier_then_subtokens():
    # tau(check_limit) = {check_limit, check, limit}
    assert tokenize("check_limit") == ["check_limit", "check", "limit"]
    assert tokenize("foo") == ["foo"]


def test_tokenize_code_keeps_keywords_whole():
    tokens = tokenize("async def handleEvent(self): raise ValueError(42)")
    assert tokens == [
        "async",
        "def",
        "handleevent",
        "handle",
        "event",
        "self",
        "raise",
        "valueerror",
        "value",
        "error",
        "42",
    ]


def test_keywords_are_case_sensitive():
    # `Set` and `Type` are identifiers, not the TS keywords `set`/`type`.
    tokenizer = CodeTokenizer(keep_keywords=False)
    assert tokenizer.tokenize("type Set = Type") == ["set", "type"]
    assert tokenizer.tokenize("return None") == []


def test_tokenizer_options():
    text = "for retryCount in range(3)"
    assert CodeTokenizer(keep_keywords=False, keep_numbers=False).tokenize(text) == [
        "retrycount",
        "retry",
        "count",
        "range",
    ]
    assert CodeTokenizer(lowercase=False).tokenize("retryCount") == ["retryCount", "retry", "Count"]


def test_tokenize_ignores_structural_tags_and_punctuation():
    text = '[DOC] Validates the signature.\n[SIG] def check(x)\n[CODE] return x["a.b"] != 0'
    assert tokenize(text) == [
        "validates",
        "the",
        "signature",
        "def",
        "check",
        "x",
        "return",
        "x",
        "a",
        "b",
        "0",
    ]
