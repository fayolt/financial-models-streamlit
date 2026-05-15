"""Discover, validate, and register plugins from `models/<slug>/plugin.py`."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel

from .contract import Format, ModelPlugin, ModelResults, SubscriptionTier


_REQUIRED_ATTRS: tuple[tuple[str, type], ...] = (
    ("slug", str),
    ("name", str),
    ("version", str),
    ("description", str),
    ("minimum_tier", SubscriptionTier),
    ("supported_formats", set),
    ("input_schema", type),
    ("results_schema", type),
)

_REQUIRED_METHODS: tuple[str, ...] = (
    "default_inputs",
    "compute",
    "render",
    "generate_report",
)


def validate_plugin(plugin: Any) -> None:
    """Deep structural check. Protocol's isinstance() only checks method names;
    this catches missing class attributes and wrong types too."""
    for attr, expected_type in _REQUIRED_ATTRS:
        if not hasattr(plugin, attr):
            raise TypeError(f"Plugin missing attribute: {attr!r}")
        value = getattr(plugin, attr)
        if not isinstance(value, expected_type):
            raise TypeError(
                f"Plugin.{attr} must be {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
    if not issubclass(plugin.input_schema, BaseModel):
        raise TypeError("Plugin.input_schema must subclass pydantic.BaseModel")
    if not issubclass(plugin.results_schema, ModelResults):
        raise TypeError("Plugin.results_schema must subclass ModelResults")
    for fmt in plugin.supported_formats:
        if not isinstance(fmt, Format):
            raise TypeError(f"supported_formats must contain Format members, got {fmt!r}")
    for method in _REQUIRED_METHODS:
        if not callable(getattr(plugin, method, None)):
            raise TypeError(f"Plugin missing callable: {method!r}")


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ModelPlugin] = {}

    def register(self, plugin: ModelPlugin) -> None:
        validate_plugin(plugin)
        if plugin.slug in self._plugins:
            raise ValueError(f"Duplicate plugin slug: {plugin.slug!r}")
        self._plugins[plugin.slug] = plugin

    def get(self, slug: str) -> ModelPlugin:
        return self._plugins[slug]

    def __iter__(self) -> Iterator[ModelPlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def slugs(self) -> list[str]:
        return list(self._plugins.keys())


def load_plugins(models_dir: Path) -> PluginRegistry:
    registry = PluginRegistry()
    for plugin_path in sorted(models_dir.glob("*/plugin.py")):
        # Sanitize hyphens so the synthetic module name is a valid Python identifier
        # (pydantic and others look up cls.__module__ in sys.modules by attribute).
        sanitized = plugin_path.parent.name.replace("-", "_")
        spec = importlib.util.spec_from_file_location(
            f"_plugin_{sanitized}", plugin_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin spec from {plugin_path}")
        module = importlib.util.module_from_spec(spec)
        # Register in sys.modules so pydantic can resolve forward-ref type hints
        # (it looks up cls.__module__ in sys.modules).
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        model = getattr(module, "MODEL", None)
        if model is None:
            raise AttributeError(f"{plugin_path} must export a MODEL constant")
        registry.register(model)
    return registry
