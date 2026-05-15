"""Generic contract test every registered plugin must pass."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.plugin import (
    Format,
    ModelPlugin,
    ModelResults,
    NotSupportedError,
    PluginRegistry,
    ReportOptions,
    SubscriptionTier,
    User,
    load_plugins,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"


@pytest.fixture(scope="session")
def registry() -> PluginRegistry:
    return load_plugins(MODELS_DIR)


@pytest.fixture
def test_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        tier=SubscriptionTier.ENTERPRISE,
    )


def test_registry_not_empty(registry: PluginRegistry):
    assert len(registry) >= 1, "Expected at least one plugin in models/"


def pytest_generate_tests(metafunc):
    if "plugin" in metafunc.fixturenames:
        registry = load_plugins(MODELS_DIR)
        metafunc.parametrize(
            "plugin",
            list(registry),
            ids=[p.slug for p in registry],
        )


def test_implements_protocol(plugin: ModelPlugin):
    assert isinstance(plugin, ModelPlugin)


def test_metadata_present(plugin: ModelPlugin):
    assert plugin.slug
    assert plugin.name
    assert plugin.version
    assert isinstance(plugin.minimum_tier, SubscriptionTier)
    assert isinstance(plugin.supported_formats, set)


def test_default_inputs_matches_schema(plugin: ModelPlugin):
    inputs = plugin.default_inputs()
    assert isinstance(inputs, plugin.input_schema)


def test_compute_returns_results(plugin: ModelPlugin):
    inputs = plugin.default_inputs()
    results = plugin.compute(inputs)
    assert isinstance(results, plugin.results_schema)
    assert isinstance(results, ModelResults)


def test_generate_report_produces_bytes(plugin: ModelPlugin, test_user: User):
    if not plugin.supported_formats:
        pytest.skip(f"{plugin.slug} declares no supported formats")
    inputs = plugin.default_inputs()
    results = plugin.compute(inputs)
    for fmt in plugin.supported_formats:
        out = plugin.generate_report(
            inputs=inputs,
            results=results,
            formats={fmt},
            options=ReportOptions(),
            user=test_user,
        )
        assert fmt in out, f"{plugin.slug} did not return key {fmt}"
        assert isinstance(out[fmt], bytes)
        assert len(out[fmt]) > 0, f"{plugin.slug} produced empty {fmt.value}"


def test_generate_report_rejects_unsupported(plugin: ModelPlugin, test_user: User):
    unsupported = set(Format) - plugin.supported_formats
    if not unsupported:
        pytest.skip(f"{plugin.slug} supports every format")
    inputs = plugin.default_inputs()
    results = plugin.compute(inputs)
    with pytest.raises(NotSupportedError):
        plugin.generate_report(
            inputs=inputs,
            results=results,
            formats=unsupported,
            options=ReportOptions(),
            user=test_user,
        )
