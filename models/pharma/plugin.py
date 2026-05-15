"""Pharma plugin — wraps pharma_financial.FinancialModel."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, PrivateAttr

# Legacy code lives at <repo_root>/pharma/src/pharma_financial/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_SRC = _REPO_ROOT / "pharma" / "src"
if str(_LEGACY_SRC) not in sys.path:
    sys.path.insert(0, str(_LEGACY_SRC))

from pharma_financial import FinancialModel, FinancialOutputs, load_inputs  # noqa: E402
from pharma_financial.report import (  # noqa: E402
    collect_report_sections,
    generate_report as _legacy_generate_report,
)

from app.plugin.contract import (
    Format,
    ModelPlugin,
    ModelResults,
    NotSupportedError,
    ReportOptions,
    Scenario,
    SubscriptionTier,
    User,
)


class PharmaInputs(BaseModel):
    """Top-level knobs. The full pharma input set (products, capex, debt,
    risk, scenarios, etc.) is loaded from the legacy default JSON; Phase 1.5
    will expose more fields via the UI."""

    tax_rate: float = 0.30
    discount_rate: float = 0.12
    include_scenarios: bool = True


class PharmaResults(ModelResults):
    summary_metrics: dict[str, Any]
    income_statement: dict[str, Any]
    cash_flow: dict[str, Any]
    balance_sheet: dict[str, Any]

    _model: Any = PrivateAttr(default=None)
    _outputs: Any = PrivateAttr(default=None)


def _build_legacy_model(inputs: PharmaInputs) -> FinancialModel:
    legacy_inputs = load_inputs()
    # Override only the top-level knobs we expose. Everything else (products,
    # capex schedule, risk factors, etc.) comes from default_inputs.json.
    legacy_inputs.tax_rate = float(inputs.tax_rate)
    legacy_inputs.financing = replace(
        legacy_inputs.financing, discount_rate=float(inputs.discount_rate)
    )
    return FinancialModel(legacy_inputs)


def _table_to_dict(table: Any) -> dict[str, Any]:
    """Serialise a pharma_financial.table.Table into a plain dict."""
    if table is None:
        return {}
    try:
        return {
            "index": list(table.index),
            "index_name": getattr(table, "index_name", "Year"),
            "columns": {name: list(values) for name, values in table.data.items()},
        }
    except AttributeError:
        return {}


class PharmaPlugin:
    slug: str = "pharma"
    name: str = "Pharmaceutical Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Multi-product pharmaceutical financial model with P&L, cash flow, "
        "balance sheet, scenarios, sensitivity, and risk diagnostics."
    )
    icon: str | None = "💊"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX}
    input_schema: type[BaseModel] = PharmaInputs
    results_schema: type[ModelResults] = PharmaResults

    def default_inputs(self) -> PharmaInputs:
        return PharmaInputs()

    def compute(self, inputs: BaseModel) -> PharmaResults:
        assert isinstance(inputs, PharmaInputs)
        model = _build_legacy_model(inputs)
        # Use run_core() to avoid pulling AI/monte-carlo/scenario heavy paths
        # at compute time; full run() is still invoked for XLSX reports.
        outputs = model.run_core()
        result = PharmaResults(
            summary_metrics=_table_to_dict(outputs.summary_metrics),
            income_statement=_table_to_dict(outputs.income_statement),
            cash_flow=_table_to_dict(outputs.cash_flow),
            balance_sheet=_table_to_dict(outputs.balance_sheet),
        )
        result._model = model
        result._outputs = outputs
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)
        summary = results.summary_metrics
        if summary and summary.get("columns", {}).get("Value"):
            idx = summary.get("index", [])
            values = summary["columns"]["Value"]
            for metric_name in ("NPV", "IRR", "Payback Period"):
                if metric_name in idx:
                    position = idx.index(metric_name)
                    st.metric(metric_name, f"{values[position]:,.2f}")

        from app.reports.ui import render_report_downloads
        render_report_downloads(self, inputs, results, user)

    def generate_report(
        self,
        inputs: BaseModel,
        results: ModelResults,
        formats: set[Format],
        options: ReportOptions,
        user: User,
    ) -> dict[Format, bytes]:
        unsupported = formats - self.supported_formats
        if unsupported:
            raise NotSupportedError(
                f"{self.slug} does not support: {sorted(f.value for f in unsupported)}"
            )
        assert isinstance(results, PharmaResults)
        assert isinstance(inputs, PharmaInputs)

        model = results._model
        outputs: FinancialOutputs | None = results._outputs
        if model is None or outputs is None:
            recomputed = self.compute(inputs)
            model = recomputed._model
            outputs = recomputed._outputs

        out: dict[Format, bytes] = {}
        if Format.XLSX in formats:
            sections = collect_report_sections(model, outputs)
            data, _mime, _filename = _legacy_generate_report(
                sections, "excel", report_name="pharma_financial_report"
            )
            out[Format.XLSX] = data
        return out


MODEL: ModelPlugin = PharmaPlugin()
