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
    supported_formats: set[Format] = {Format.XLSX, Format.PDF}
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
        if Format.PDF in formats:
            out[Format.PDF] = self._build_pdf(results, options, user)
        return out

    def _build_pdf(
        self,
        results: "SolarFarmResults",
        options: ReportOptions,
        user: User,
    ) -> bytes:
        from app.reports.pdf_style import (
            body,
            build_pdf,
            dataframe_table,
            heading,
            metric_grid,
        )
        from reportlab.platypus import PageBreak

        def _fmt_usd(v) -> str:
            if not isinstance(v, (int, float)) or v != v:
                return "n/a"
            return f"USD {v:,.0f}"

        def _fmt_pct(v) -> str:
            if not isinstance(v, (int, float)) or v != v:
                return "n/a"
            return f"{v * 100:.2f}%"

        def _fmt_dscr(v) -> str:
            if not isinstance(v, (int, float)) or v != v:
                return "n/a"
            return f"{v:.2f}x"

        def _fmt_years(v) -> str:
            if not isinstance(v, (int, float)) or v != v:
                return "n/a"
            return f"{v / 12:.1f} yrs"

        val = results.valuation
        metrics = {
            "Project NPV": _fmt_usd(val.get("project_npv")),
            "Project IRR": _fmt_pct(val.get("project_irr")),
            "Payback": _fmt_years(val.get("project_payback_months")),
            "Min DSCR": _fmt_dscr(val.get("min_dscr")),
        }

        outputs = results._outputs
        annual = getattr(outputs, "annual_summary", None) if outputs is not None else None
        monthly = getattr(outputs, "monthly_results", None) if outputs is not None else None

        revenue_cols = [
            c for c in (
                "revenue_total", "total_opex", "ebitda", "depreciation",
                "ebit", "tax_payment", "net_income",
            ) if annual is not None and c in annual.columns
        ]
        position_cols = [
            c for c in (
                "cfads", "debt_service", "dscr", "debt_free_cash_flow",
                "equity_cash_flow", "capex",
            ) if annual is not None and c in annual.columns
        ]

        metrics_df = None
        if results.metrics:
            metrics_df = (
                pd.Series(results.metrics, name="value")
                .to_frame()
                .rename_axis("metric")
                .reset_index()
            )

        sections = [
            heading("Executive summary"),
            body(self.description),
            metric_grid(metrics, columns=4),
            PageBreak(),
            heading("Annual revenue & P&L summary"),
            *(
                dataframe_table(annual[revenue_cols], max_rows=15)
                if annual is not None and revenue_cols
                else [body("Annual P&L data not available.")]
            ),
            PageBreak(),
            heading("Annual cash flow & coverage"),
            *(
                dataframe_table(annual[position_cols], max_rows=15)
                if annual is not None and position_cols
                else [body("Annual cash flow data not available.")]
            ),
            PageBreak(),
            heading("Investor metrics dashboard"),
            *(
                dataframe_table(metrics_df, max_rows=30)
                if metrics_df is not None
                else [body("Metrics not available.")]
            ),
        ]

        return build_pdf(
            title=self.name,
            subtitle=f"Prepared for {user.email}",
            sections=sections,
            watermark=options.watermark,
        )


MODEL: ModelPlugin = SolarFarmPlugin()
