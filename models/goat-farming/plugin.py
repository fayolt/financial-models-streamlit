"""Goat-farming plugin — wraps goat_financial_model.GoatModel."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, PrivateAttr

# Legacy code lives at <repo_root>/goat-farming/src/goat_financial_model/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_SRC = _REPO_ROOT / "goat-farming" / "src"
if str(_LEGACY_SRC) not in sys.path:
    sys.path.insert(0, str(_LEGACY_SRC))

from goat_financial_model import GoatModel, InputSchedule  # noqa: E402

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


class GoatFarmingInputs(BaseModel):
    """Top-level knobs. The base schedule is generated synthetically for v1;
    Phase 1.5 will let users upload/edit it."""

    horizon_months: int = 24
    start_period: str = "2024-01-31"
    milk_price_change_pct: float = 0.0
    feed_cost_change_pct: float = 10.0
    wacc: float = 0.12
    terminal_value: float = 0.0


class GoatFarmingResults(ModelResults):
    valuation_inputs: dict[str, float]
    kpi_summary: dict[str, Any]

    _model: Any = PrivateAttr(default=None)
    _base_df: Any = PrivateAttr(default=None)
    _scenario_df: Any = PrivateAttr(default=None)
    _kpis_df: Any = PrivateAttr(default=None)
    _break_even_df: Any = PrivateAttr(default=None)


def _build_sample_schedule(horizon_months: int, start_period: str) -> pd.DataFrame:
    """Synthesise a plausible monthly P&L/cash/balance schedule.

    Adapted from goat-farming/tests/test_model_integration.py::_build_sample_schedule
    so we don't fork the test fixture but keep the plugin self-contained."""
    periods = pd.date_range(start_period, periods=horizon_months, freq="ME")
    revenue = pd.Series(100_000 + (periods.month - 1) * 5_000.0, index=periods)
    cogs = revenue * 0.45
    gross_profit = revenue - cogs
    variable_expenses = revenue * 0.12
    direct_wages = revenue * 0.08
    fixed_expenses = pd.Series(10_000.0, index=periods)
    admin_wages = pd.Series(3_000.0, index=periods)

    ebitda = gross_profit - variable_expenses - direct_wages - fixed_expenses - admin_wages
    depreciation = pd.Series(2_000.0, index=periods)
    ebit = ebitda - depreciation
    interest = pd.Series(500.0, index=periods)
    npbt = ebit - interest
    tax = npbt * 0.25
    npat = npbt - tax

    cfo = ebitda - 1_000
    capex = pd.Series(5_000.0, index=periods)
    cfi = -capex
    cff = pd.Series(2_000.0, index=periods)
    net_cash = cfo + cfi + cff

    opening_cash = pd.Series(50_000.0, index=periods).cumsum().shift(1).fillna(50_000.0)
    closing_cash = opening_cash + net_cash

    current_assets = closing_cash + 20_000.0
    non_current_assets = pd.Series(100_000.0, index=periods)
    current_liabilities = pd.Series(15_000.0, index=periods)
    non_current_liabilities = pd.Series(50_000.0, index=periods)
    equity = current_assets + non_current_assets - current_liabilities - non_current_liabilities

    return pd.DataFrame({
        "Revenue": revenue,
        "COGS": cogs,
        "Gross Margin": gross_profit,
        "Variable Expenses": variable_expenses,
        "Direct Wages": direct_wages,
        "Fixed Expenses": fixed_expenses,
        "Admin Wages": admin_wages,
        "EBITDA": ebitda,
        "Depreciation & Amortization": depreciation,
        "EBIT": ebit,
        "Interest Expense": interest,
        "NPBT": npbt,
        "Tax Expense": tax,
        "NPAT": npat,
        "CFO": cfo,
        "CFI": cfi,
        "CFF": cff,
        "Net Cash Flow": net_cash,
        "Capex": capex,
        "Opening Cash Balance": opening_cash,
        "Closing Cash Balance": closing_cash,
        "Cash and Cash Equivalents": closing_cash,
        "Current Assets": current_assets,
        "Non-current Assets": non_current_assets,
        "Current Liabilities": current_liabilities,
        "Non-current Liabilities": non_current_liabilities,
        "Equity": equity,
    })


class GoatFarmingPlugin:
    slug: str = "goat-farming"
    name: str = "Goat Farming Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Manual-input goat farm model with scenario analysis, "
        "KPIs, financial statements, and break-even."
    )
    icon: str | None = "🐐"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX, Format.CSV, Format.PDF}
    input_schema: type[BaseModel] = GoatFarmingInputs
    results_schema: type[ModelResults] = GoatFarmingResults

    def default_inputs(self) -> GoatFarmingInputs:
        return GoatFarmingInputs()

    def compute(self, inputs: BaseModel) -> GoatFarmingResults:
        assert isinstance(inputs, GoatFarmingInputs)
        schedule_df = _build_sample_schedule(inputs.horizon_months, inputs.start_period)
        valuation_inputs = {"WACC": inputs.wacc, "Terminal Value": inputs.terminal_value}
        schedule = InputSchedule(data=schedule_df, valuation_inputs=valuation_inputs)
        model = schedule.to_model()
        base_df = model.to_tidy()
        scenario_df = model.scenario(
            milk_price_pct=inputs.milk_price_change_pct / 100.0,
            feed_cost_pct=inputs.feed_cost_change_pct / 100.0,
        )
        kpis_df = model.kpis(scenario_df, annual=True)
        try:
            break_even_df = model.break_even(scenario_df, annual=True)
        except Exception:
            break_even_df = None

        kpi_summary: dict[str, Any] = {}
        if kpis_df is not None and not kpis_df.empty:
            kpi_summary = {str(k): v.to_dict() for k, v in kpis_df.items()}

        result = GoatFarmingResults(
            valuation_inputs=valuation_inputs,
            kpi_summary=kpi_summary,
        )
        result._model = model
        result._base_df = base_df
        result._scenario_df = scenario_df
        result._kpis_df = kpis_df
        result._break_even_df = break_even_df
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)
        st.dataframe(results._kpis_df)

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
        assert isinstance(results, GoatFarmingResults)
        if results._model is None:
            assert isinstance(inputs, GoatFarmingInputs)
            results = self.compute(inputs)

        out: dict[Format, bytes] = {}

        if Format.XLSX in formats:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                results._base_df.to_excel(writer, sheet_name="Input Schedule")
                results._scenario_df.to_excel(writer, sheet_name="Scenario Timeline")
                if results._kpis_df is not None and not results._kpis_df.empty:
                    results._kpis_df.mul(100).to_excel(writer, sheet_name="KPIs (Annual)")
                for sheet_name, builder in (
                    ("Statement of Financial Performance",
                     results._model.statement_of_financial_performance),
                    ("Statement of Financial Position",
                     results._model.statement_of_financial_position),
                    ("Statement of Cash Flows",
                     results._model.statement_of_cash_flow),
                ):
                    try:
                        df = builder(results._scenario_df, annual=True)
                        df.to_excel(writer, sheet_name=sheet_name)
                    except (ValueError, KeyError):
                        continue
                if results._break_even_df is not None and not results._break_even_df.empty:
                    results._break_even_df.to_excel(writer, sheet_name="Break-even")
            out[Format.XLSX] = buf.getvalue()

        if Format.CSV in formats:
            out[Format.CSV] = results._scenario_df.to_csv().encode("utf-8")

        if Format.PDF in formats:
            out[Format.PDF] = self._build_pdf(results, options, user)

        return out

    def _build_pdf(
        self,
        results: "GoatFarmingResults",
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

        sections: list = [
            heading("Executive summary"),
            body(self.description),
        ]

        kpis_df = results._kpis_df
        if kpis_df is None or kpis_df.empty:
            sections.append(body("KPIs not available"))
        else:
            headline_rows = kpis_df.head(6)
            first_col = headline_rows.columns[0]
            metrics: dict[str, str] = {}
            for label, value in headline_rows[first_col].items():
                try:
                    metrics[str(label)] = f"{float(value) * 100:.2f}%"
                except (TypeError, ValueError):
                    metrics[str(label)] = str(value)
            if metrics:
                sections.append(metric_grid(metrics))
            else:
                sections.append(body("KPIs not available"))

        sections.append(PageBreak())

        scenario_df = results._scenario_df
        sections.extend(
            dataframe_table(
                scenario_df, title="Scenario timeline", max_rows=12,
            )
        )

        if kpis_df is not None and not kpis_df.empty:
            sections.extend(
                dataframe_table(kpis_df, title="Annual KPIs", max_rows=18)
            )

        statements = (
            ("Statement of Financial Performance",
             results._model.statement_of_financial_performance),
            ("Statement of Financial Position",
             results._model.statement_of_financial_position),
            ("Statement of Cash Flows",
             results._model.statement_of_cash_flow),
        )
        for title, builder in statements:
            try:
                df = builder(scenario_df, annual=True)
            except (ValueError, KeyError):
                continue
            sections.extend(dataframe_table(df, title=title, max_rows=18))

        if results._break_even_df is not None and not results._break_even_df.empty:
            sections.extend(
                dataframe_table(
                    results._break_even_df, title="Break-even", max_rows=18,
                )
            )

        return build_pdf(
            title=self.name,
            subtitle=f"Prepared for {user.email}",
            sections=sections,
            watermark=options.watermark,
        )


MODEL: ModelPlugin = GoatFarmingPlugin()
