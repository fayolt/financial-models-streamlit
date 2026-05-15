"""Cassava-ethanol plugin — wraps bioethanol_model.CassavaBioethanolModel."""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, PrivateAttr

# Pandas 3 removed DataFrame.applymap; legacy bioethanol_model.inputs.signature()
# still calls it. Alias to the replacement to avoid touching legacy code.
if not hasattr(pd.DataFrame, "applymap"):
    pd.DataFrame.applymap = pd.DataFrame.map  # type: ignore[attr-defined]

# Legacy code lives at <repo_root>/cassava-ethanol/. Add it to sys.path so the
# internal `bioethanol_model` package imports cleanly without modifying any
# legacy file.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _REPO_ROOT / "cassava-ethanol"
if str(_LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGACY_DIR))

from bioethanol_model import CassavaBioethanolModel  # noqa: E402
from bioethanol_model.exporter import export_to_excel  # noqa: E402
from bioethanol_model.inputs import default_input_page  # noqa: E402

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


class CassavaEthanolInputs(BaseModel):
    """Top-level cassava-ethanol knobs. The full table-driven schedule is baked
    into the legacy `default_input_page()`; these fields override the most
    impactful entries before `CassavaBioethanolModel.build()` runs."""

    annual_cassava_tons: float = 110_000.0
    conversion_yield_litre_per_ton: float = 200.0
    ethanol_price_per_litre: float = 0.70
    capex_usd: float = 40_000_000.0
    wacc: float = 0.12
    horizon_years: int = 10
    scenario: str = "FARM_ONLY"  # FARM_ONLY | BUY_ONLY | HYBRID


class CassavaEthanolResults(ModelResults):
    metrics: dict[str, Any]
    scenario: str

    # Raw payload from `CassavaBioethanolModel.build()` plus the model object,
    # kept private so report generation can reuse them without recomputing.
    _model: Any = PrivateAttr(default=None)
    _build: dict[str, Any] | None = PrivateAttr(default=None)


def _apply_overrides(page: Any, knobs: CassavaEthanolInputs) -> None:
    """Mutate the default `InputLandingPage` to reflect the plugin's top-level
    knobs. Anything not overridden keeps the legacy defaults."""

    # Projection horizon: keep the legacy 2024 start and extend end_year to fit
    # the requested horizon.
    start_year = page.projection.start_year
    page.projection.end_year = start_year + max(1, int(knobs.horizon_years))
    page.projection.clamp_planning_start()

    # Global inputs: override the discount rate (WACC) row.
    gdf = page.global_inputs.data.copy()
    if "Parameter" in gdf.columns:
        mask = gdf["Parameter"].astype(str).str.lower() == "discount rate"
        gdf.loc[mask, "Value"] = float(knobs.wacc)
        page.global_inputs.set_data(gdf, mark_user_input=True)

    # Revenue inputs: set fuel ethanol base price.
    rdf = page.revenue_inputs.data.copy()
    if "Product" in rdf.columns:
        mask = rdf["Product"].astype(str).str.contains("ethanol", case=False, na=False)
        rdf.loc[mask, "Base Price"] = float(knobs.ethanol_price_per_litre)
        page.revenue_inputs.set_data(rdf, mark_user_input=True)

    # Production annual: rebuild from cassava tonnage + conversion yield. Spans
    # the projection horizon so every year produces revenue.
    annual_rows = []
    ethanol_litres = float(knobs.annual_cassava_tons) * float(
        knobs.conversion_yield_litre_per_ton
    )
    animal_feed_ton = float(knobs.annual_cassava_tons) * 0.275
    for year in range(start_year + 1, page.projection.end_year + 1):
        annual_rows.append(
            {
                "Year": year,
                "Start Month": f"{year:04d}-01",
                "Cassava ton": float(knobs.annual_cassava_tons),
                "Ethanol litres": ethanol_litres,
                "Animal Feed ton": animal_feed_ton,
            }
        )
    page.production_annual.set_data(pd.DataFrame(annual_rows), mark_user_input=True)

    # Production monthly: spread one full operational year evenly so the cost
    # and revenue compute steps have non-zero months.
    first_op_year = start_year + 1
    monthly_index = pd.period_range(
        f"{first_op_year:04d}-01", f"{first_op_year:04d}-12", freq="M"
    )
    months = len(monthly_index)
    page.production_monthly.set_data(
        pd.DataFrame(
            {
                "Start Month": monthly_index.astype(str),
                "Cassava ton": [float(knobs.annual_cassava_tons) / months] * months,
                "Ethanol litres": [ethanol_litres / months] * months,
                "Animal Feed ton": [animal_feed_ton / months] * months,
                "Growth %": [0.0] * months,
            }
        ),
        mark_user_input=True,
    )

    # Initial investment: rescale all capex rows proportionally to the
    # requested total capex.
    idf = page.initial_investment.data.copy()
    if "Cost" in idf.columns and not idf.empty:
        current_total = pd.to_numeric(idf["Cost"], errors="coerce").fillna(0.0).sum()
        if current_total > 0:
            factor = float(knobs.capex_usd) / float(current_total)
            idf["Cost"] = pd.to_numeric(idf["Cost"], errors="coerce").fillna(0.0) * factor
            page.initial_investment.set_data(idf, mark_user_input=True)

    # Loan schedule: keep the senior debt sized at 60% of the new capex.
    ldf = page.loan_schedule.data.copy()
    if "Loan Amount" in ldf.columns and not ldf.empty:
        ldf.loc[ldf.index[0], "Loan Amount"] = float(knobs.capex_usd) * 0.6
        page.loan_schedule.set_data(ldf, mark_user_input=True)


class CassavaEthanolPlugin:
    slug: str = "cassava-ethanol"
    name: str = "Cassava Ethanol Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Cassava-to-bioethanol project finance model with full P&L, cash flow, "
        "balance sheet, key metrics, sensitivities and scenario comparison."
    )
    icon: str | None = "🌽"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX}
    input_schema: type[BaseModel] = CassavaEthanolInputs
    results_schema: type[ModelResults] = CassavaEthanolResults

    def default_inputs(self) -> CassavaEthanolInputs:
        return CassavaEthanolInputs()

    def compute(self, inputs: BaseModel) -> CassavaEthanolResults:
        assert isinstance(inputs, CassavaEthanolInputs)
        page = default_input_page()
        _apply_overrides(page, inputs)
        model = CassavaBioethanolModel(input_page=page, scenario=inputs.scenario)
        build = model.build(scenario=inputs.scenario)

        raw_metrics = build.get("metrics", {}) or {}
        metrics: dict[str, Any] = {}
        for key, value in raw_metrics.items():
            try:
                metrics[str(key)] = float(value)
            except (TypeError, ValueError):
                metrics[str(key)] = value

        result = CassavaEthanolResults(
            metrics=metrics,
            scenario=inputs.scenario,
        )
        result._model = model
        result._build = build
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)

        col1, col2, col3 = st.columns(3)
        npv = results.metrics.get("Project NPV")
        irr = results.metrics.get("Project IRR")
        equity_irr = results.metrics.get("Equity IRR")
        col1.metric(
            "Project NPV (USD)",
            f"{npv:,.0f}" if isinstance(npv, (int, float)) else "—",
        )
        col2.metric(
            "Project IRR",
            f"{irr * 100:.2f}%" if isinstance(irr, (int, float)) else "—",
        )
        col3.metric(
            "Equity IRR",
            f"{equity_irr * 100:.2f}%"
            if isinstance(equity_irr, (int, float))
            else "—",
        )

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
        assert isinstance(results, CassavaEthanolResults)
        if results._model is None or results._build is None:
            assert isinstance(inputs, CassavaEthanolInputs)
            recomputed = self.compute(inputs)
            results = recomputed

        out: dict[Format, bytes] = {}

        if Format.XLSX in formats:
            # `export_to_excel` opens its own ExcelWriter from a Path (it uses
            # xlsxwriter for cell formatting), so we route it through a temp
            # file and return the bytes. Falls back to a minimal direct write
            # if the full exporter ever raises.
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    temp_path = Path(tmpdir) / "cassava_ethanol_model.xlsx"
                    export_to_excel(
                        results._model,
                        temp_path,
                        results=results._build,
                        scenario=results.scenario,
                    )
                    out[Format.XLSX] = temp_path.read_bytes()
            except Exception:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    financials = results._build.get("financials")
                    if financials is not None:
                        financials.income_annual.to_excel(
                            writer, sheet_name="Income Statement (Annual)"
                        )
                        financials.cashflow_annual.to_excel(
                            writer, sheet_name="Cash Flow (Annual)"
                        )
                        financials.balance_annual.to_excel(
                            writer, sheet_name="Balance Sheet (Annual)"
                        )
                    revenue = results._build.get("revenue")
                    if revenue is not None and hasattr(revenue, "annual"):
                        revenue.annual.to_excel(writer, sheet_name="Revenue Forecast")
                    pd.DataFrame(
                        {"Metric": list(results.metrics.keys()),
                         "Value": list(results.metrics.values())}
                    ).to_excel(writer, sheet_name="Key Metrics", index=False)
                out[Format.XLSX] = buf.getvalue()

        return out


MODEL: ModelPlugin = CassavaEthanolPlugin()
