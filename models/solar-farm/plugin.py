"""Solar-farm plugin — wraps solar_farm_financial_model.SolarFarmFinancialModel."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, PrivateAttr

# Legacy code lives at <repo_root>/solar-farm/solar_farm_financial_model/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _REPO_ROOT / "solar-farm"
if str(_LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGACY_DIR))

from solar_farm_financial_model import (  # noqa: E402
    SolarFarmFinancialModel,
    build_summary_report,
    load_assumptions,
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


class SolarFarmInputs(BaseModel):
    """Top-level knobs for the solar-farm project finance model.

    All other inputs (capex schedules, opex line items, debt, working capital,
    tax schedule, etc.) are baked into the default `Assumptions` returned by
    the legacy `load_assumptions()` helper. Phase 1.5 will expose more fields."""

    capacity_mw: float = 10.0
    contract_years: int = 20
    tariff_per_kwh: float = 0.16  # $/kWh; $160/MWh is the legacy default
    capex_per_mw: float = 1_295_360.8  # ~$12.95M total / 10 MW from legacy defaults
    opex_per_mw_year: float = 15_215.0  # ~$152.15k / 10 MW from legacy fixed opex
    wacc: float = 0.10
    discount_rate_terminal: float = 0.10


class SolarFarmResults(ModelResults):
    metrics: dict[str, float]
    valuation: dict[str, float]

    _outputs: Any = PrivateAttr(default=None)
    _assumptions: Any = PrivateAttr(default=None)
    _summary_tables: dict[str, Any] | None = PrivateAttr(default=None)


def _build_assumptions(inputs: SolarFarmInputs):
    """Hydrate the legacy `Assumptions` object with user-supplied top-level knobs."""
    assumptions = load_assumptions()

    # Forecast horizon driven by contract_years (months).
    assumptions.global_assumptions.forecast_months = int(inputs.contract_years) * 12
    assumptions.global_assumptions.discount_rate = float(inputs.wacc)

    # Capacity drives the production model.
    assumptions.energy.capacity_mw = float(inputs.capacity_mw)

    # PPA tariff: convert $/kWh to $/MWh for the legacy schema.
    assumptions.revenue.ppa.rate_curve.initial = float(inputs.tariff_per_kwh) * 1000.0

    # Scale capex line items so total capex equals capex_per_mw * capacity_mw.
    target_total_capex = float(inputs.capex_per_mw) * float(inputs.capacity_mw)
    current_total_capex = sum(item.amount for item in assumptions.capex_items)
    if current_total_capex > 0 and target_total_capex > 0:
        scale = target_total_capex / current_total_capex
        for item in assumptions.capex_items:
            item.amount = item.amount * scale

    # Scale fixed opex so the per-MW-year aggregate matches the input.
    target_fixed_opex = float(inputs.opex_per_mw_year) * float(inputs.capacity_mw)
    current_fixed_opex = sum(item.annual_cost for item in assumptions.fixed_opex)
    if current_fixed_opex > 0 and target_fixed_opex > 0:
        scale = target_fixed_opex / current_fixed_opex
        for item in assumptions.fixed_opex:
            item.annual_cost = item.annual_cost * scale

    return assumptions


class SolarFarmPlugin:
    slug: str = "solar-farm"
    name: str = "Solar Farm Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Project finance model for a utility-scale solar farm with PPA + merchant "
        "revenue, capex/opex schedule, debt, depreciation, NPV/IRR/DSCR metrics."
    )
    icon: str | None = "☀️"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX}
    input_schema: type[BaseModel] = SolarFarmInputs
    results_schema: type[ModelResults] = SolarFarmResults

    def default_inputs(self) -> SolarFarmInputs:
        return SolarFarmInputs()

    def compute(self, inputs: BaseModel) -> SolarFarmResults:
        assert isinstance(inputs, SolarFarmInputs)
        assumptions = _build_assumptions(inputs)
        model = SolarFarmFinancialModel(assumptions)
        outputs = model.run()

        metrics = {
            k: (float(v) if hasattr(v, "__float__") else v)
            for k, v in outputs.metrics.items()
        }
        valuation = {
            "project_npv": float(metrics.get("project_npv", 0.0)),
            "project_irr": float(metrics.get("project_irr", 0.0)),
            "equity_irr": float(metrics.get("equity_irr", 0.0)),
            "min_dscr": float(metrics.get("min_dscr", 0.0)),
            "project_payback_months": float(metrics.get("project_payback_months", 0.0)),
        }

        try:
            summary_tables = build_summary_report(outputs)
        except Exception:
            summary_tables = None

        result = SolarFarmResults(metrics=metrics, valuation=valuation)
        result._outputs = outputs
        result._assumptions = assumptions
        result._summary_tables = summary_tables
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)
        npv_value = results.valuation.get("project_npv", 0.0)
        st.metric("Project NPV (USD)", f"{npv_value:,.0f}")

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
        assert isinstance(results, SolarFarmResults)
        if results._outputs is None:
            assert isinstance(inputs, SolarFarmInputs)
            results = self.compute(inputs)

        out: dict[Format, bytes] = {}
        if Format.XLSX in formats:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                # Headline metrics sheet.
                metrics_df = (
                    pd.Series(results.metrics, name="value")
                    .to_frame()
                    .rename_axis("metric")
                    .reset_index()
                )
                metrics_df.to_excel(writer, sheet_name="Metrics", index=False)

                # Annual P&L / cash flow summary.
                try:
                    annual = results._outputs.annual_summary
                    annual.to_excel(writer, sheet_name="Annual Summary")
                except Exception:
                    pass

                # Monthly schedule (revenue, opex, capex, debt, equity CFs).
                try:
                    monthly = results._outputs.monthly_results
                    monthly.to_excel(writer, sheet_name="Monthly Results")
                except Exception:
                    pass

                # Asset/capex/depreciation summary.
                try:
                    asset_summaries = results._outputs.asset_summaries
                    if asset_summaries is not None and not asset_summaries.empty:
                        asset_summaries.to_excel(writer, sheet_name="Asset Summary", index=False)
                except Exception:
                    pass

                # Reporting helper tables (key drivers, etc.).
                if results._summary_tables:
                    for sheet_name, df in results._summary_tables.items():
                        try:
                            df.to_excel(writer, sheet_name=f"Report - {sheet_name}"[:31], index=False)
                        except Exception:
                            continue
            out[Format.XLSX] = buf.getvalue()
        return out


MODEL: ModelPlugin = SolarFarmPlugin()
