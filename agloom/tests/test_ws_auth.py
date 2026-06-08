"""WebSocket bearer auth helpers."""

from __future__ import annotations

from agloom.runtime.ws import _bearer_authorized


def test_bearer_authorized_accepts_exact_match() -> None:
    assert _bearer_authorized("Bearer secret-token", "secret-token") is True


def test_bearer_authorized_rejects_wrong_token() -> None:
    assert _bearer_authorized("Bearer wrong", "secret-token") is False


def test_bearer_authorized_rejects_missing_prefix() -> None:
    assert _bearer_authorized("secret-token", "secret-token") is False


def test_bearer_authorized_rejects_empty_config_token() -> None:
    assert _bearer_authorized("Bearer x", "") is False


def test_bearer_authorized_rejects_mismatched_length_without_error() -> None:
    """Digest compare must not raise when presented token length differs."""
    assert _bearer_authorized("Bearer short", "much-longer-expected-token") is False


def test_bearer_authorized_accepts_bearer_with_extra_whitespace() -> None:
    assert _bearer_authorized("Bearer   secret-token", "secret-token") is True
