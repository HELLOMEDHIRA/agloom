"""Unit tests for LLM-json argument coercion helpers."""

from __future__ import annotations

import pytest

from agloom_cli.tool_arg_coerce import (
    absent_to_none,
    coerce_headers,
    coerce_http_body,
    coerce_int,
    coerce_json_object,
    coerce_optional_int,
    coerce_query_params,
)


def test_absent_to_none() -> None:
    assert absent_to_none(None) is None
    assert absent_to_none("") is None
    assert absent_to_none("  ") is None
    assert absent_to_none(0) == 0


def test_coerce_int_strings_and_floats() -> None:
    n, err = coerce_int("42", "n")
    assert err is None and n == 42
    n2, err2 = coerce_int(3.0, "n")
    assert err2 is None and n2 == 3
    _, err3 = coerce_int(3.5, "n")
    assert err3 and "whole number" in err3
    _, err4 = coerce_int(True, "n")
    assert err4 and "boolean" in err4.lower()


def test_coerce_int_bounds() -> None:
    _, err = coerce_int(0, "n", min_value=1)
    assert err and ">=" in err
    _, err2 = coerce_int(100, "n", max_value=10)
    assert err2 and "<=" in err2


def test_coerce_optional_int_absent() -> None:
    n, err = coerce_optional_int(None, "n", min_value=1)
    assert n is None and err is None
    n2, err2 = coerce_optional_int("", "n")
    assert n2 is None and err2 is None


@pytest.mark.parametrize(
    "raw,ok",
    [
        ({"a": 1}, True),
        ('{"a": 1}', True),
        ("{}", True),
    ],
)
def test_coerce_json_object(raw: object, ok: bool) -> None:
    d, err = coerce_json_object(raw, "params")
    assert (err is None) is ok
    if ok:
        assert isinstance(d, dict)


def test_coerce_json_object_rejects_list_top_level() -> None:
    _, err = coerce_json_object("[1,2]", "params")
    assert err and "dict" in err.lower()


def test_coerce_headers_stringifies_values() -> None:
    h, err = coerce_headers({"X-A": 1, "X-B": True}, "headers")
    assert err is None and h == {"X-A": "1", "X-B": "true"}


def test_coerce_http_body_json_string() -> None:
    body, err = coerce_http_body('{"x": 1}', "body")
    assert err is None and body == {"x": 1}


def test_coerce_http_body_raw_string_not_json() -> None:
    body, err = coerce_http_body("plain text", "body")
    assert err is None and body == "plain text"


def test_coerce_http_body_list_for_json() -> None:
    body, err = coerce_http_body("[1, 2]", "body")
    assert err is None and body == [1, 2]
