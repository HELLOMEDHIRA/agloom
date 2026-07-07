"""Workload profile resolution."""

import pytest

from agloom.profiles import WorkloadProfile, normalize_profile_name, resolve_profile_kwargs


def test_default_profile_interactive():
    assert normalize_profile_name(None) == WorkloadProfile.INTERACTIVE


def test_platform_embedded_strict():
    kw = resolve_profile_kwargs("platform_embedded")
    assert kw["strict_execution"] is True
    assert kw["frozen"] is True
    assert kw["harness"] is True


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="Unknown workload profile"):
        normalize_profile_name("not_a_profile")
