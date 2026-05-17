"""SSRF guard for fetch_url."""

from __future__ import annotations

import pytest

from agloom.cli_tools.web import _ssrf_check_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
    ],
)
def test_ssrf_blocks_private_hosts(url: str) -> None:
    assert _ssrf_check_url(url) is not None


def test_ssrf_allows_public_host() -> None:
    assert _ssrf_check_url("https://example.com/") is None
