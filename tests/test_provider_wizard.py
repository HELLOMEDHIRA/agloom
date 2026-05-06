"""Provider wizard — LangChain registry table."""

from __future__ import annotations

from agloom_cli.provider_wizard import langchain_init_chat_provider_table, wizard_provider_table


def test_langchain_init_chat_provider_table_matches_langchain() -> None:
    rows = langchain_init_chat_provider_table()
    assert rows, "expected LangChain _BUILTIN_PROVIDERS to be non-empty"
    slugs = [r[0] for r in rows]
    assert "openai" in slugs
    assert "anthropic" in slugs
    assert slugs == sorted(slugs)


def test_wizard_provider_table_includes_extra_cerebras_sorted_by_title() -> None:
    rows = wizard_provider_table()
    assert len(rows) >= len(langchain_init_chat_provider_table())
    slugs = [r[0] for r in rows]
    assert "cerebras" in slugs
    titles = [r[3] for r in rows]
    assert titles == sorted(titles, key=str.lower)


def test_non_chat_brands_tuple_nonempty() -> None:
    from agloom_cli.langchain_index_overview import NON_CHAT_INDEX_BRANDS

    assert "ClickHouse" in NON_CHAT_INDEX_BRANDS
    assert "Qdrant" in NON_CHAT_INDEX_BRANDS
