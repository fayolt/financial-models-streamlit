"""Plugin contract every financial model must implement.

Plugins live under `models/<slug>/plugin.py` and export a module-level
`MODEL` constant whose value implements `ModelPlugin`. The orchestrator
discovers them via `app.plugin.registry.load_plugins`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Format(str, Enum):
    XLSX = "xlsx"
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"


class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class NotSupportedError(RuntimeError):
    """Raised when a plugin is asked to produce a format it does not declare."""


class BrandingProfile(BaseModel):
    organization_name: str | None = None
    logo_png: bytes | None = None
    primary_color_hex: str | None = None


class ReportOptions(BaseModel):
    include_charts: bool = True
    include_commentary: bool = False
    branding: BrandingProfile | None = None
    watermark: str | None = None


class User(BaseModel):
    id: UUID
    email: str
    tier: SubscriptionTier
    paystack_customer_id: str | None = None


class Scenario(BaseModel):
    id: UUID
    user_id: UUID
    model_slug: str
    name: str
    inputs_json: dict[str, Any]


class ModelResults(BaseModel):
    """Marker base for per-model results. Subclasses define their own fields."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


@runtime_checkable
class ModelPlugin(Protocol):
    slug: str
    name: str
    version: str
    description: str
    icon: str | None
    minimum_tier: SubscriptionTier
    supported_formats: set[Format]
    input_schema: type[BaseModel]
    results_schema: type[ModelResults]

    def default_inputs(self) -> BaseModel: ...

    def compute(self, inputs: BaseModel) -> ModelResults: ...

    def render(self, *, user: User, scenario: Scenario | None = None) -> None: ...

    def generate_report(
        self,
        inputs: BaseModel,
        results: ModelResults,
        formats: set[Format],
        options: ReportOptions,
        user: User,
    ) -> dict[Format, bytes]: ...
