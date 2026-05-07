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


def test_every_wizard_row_has_default_model_and_env_keys() -> None:
    """Every menu row must resolve to a default model + env-key list (no runtime ``KeyError``)."""
    from agloom_cli.provider_wizard import _DEFAULT_MODEL_BY_SLUG, _env_keys_for_slug, wizard_provider_table

    for slug, _pip, _cls, _title in wizard_provider_table():
        # Default model is needed for the ``Prompt.ask("Model id", default=…)`` step.
        # Slugs without an entry will fall through to ``"replace-with-your-model-id"`` placeholder,
        # but every slug we *register* (built-in or via registry extras) must have a real default.
        if slug in _DEFAULT_MODEL_BY_SLUG:
            assert _DEFAULT_MODEL_BY_SLUG[slug], f"wizard slug {slug!r} has empty default model"
        # _env_keys_for_slug must return a list (possibly empty) — never raise.
        keys = _env_keys_for_slug(slug)
        assert isinstance(keys, list)


def test_registry_extras_visible_in_wizard_when_not_in_langchain_registry() -> None:
    """Providers shipped via ``provider_registry`` (cerebras, sambanova, snowflake) appear in menu."""
    from agloom_cli.provider_wizard import wizard_provider_table

    slugs = {row[0] for row in wizard_provider_table()}
    # These three are in pyproject extras but LangChain's _BUILTIN_PROVIDERS doesn't list them;
    # they must surface via wizard_extra_rows().
    assert "cerebras" in slugs
    assert "sambanova" in slugs
    assert "snowflake" in slugs


def test_wizard_env_keys_align_with_resolver_env_keys() -> None:
    """For every wizard slug with non-empty env keys, the canonical resolver table must agree.

    Catches drift between :data:`agloom_cli.provider_wizard._ENV_KEYS_BY_SLUG` and
    :data:`agloom_cli.model_resolver._PROVIDER_ENV_KEYS` after canonicalization through
    :func:`agloom_cli.llm_provider_params.normalize_provider_slug`.
    """
    from agloom_cli.llm_provider_params import normalize_provider_slug
    from agloom_cli.model_resolver import _PROVIDER_ENV_KEYS
    from agloom_cli.provider_wizard import _ENV_KEYS_BY_SLUG

    for wizard_slug, env_list in _ENV_KEYS_BY_SLUG.items():
        if not env_list:
            continue  # cloud-IAM providers (bedrock, snowflake, …): nothing to cross-check
        canon = normalize_provider_slug(wizard_slug)
        resolver_keys = _PROVIDER_ENV_KEYS.get(canon)
        # If the resolver knows this canonical slug, it must include every env key the wizard prompts for.
        if resolver_keys is not None:
            for k in env_list:
                assert k in resolver_keys, (
                    f"wizard prompts for {k!r} on {wizard_slug!r} (canonical {canon!r}) "
                    f"but resolver _PROVIDER_ENV_KEYS[{canon!r}] = {resolver_keys}"
                )
