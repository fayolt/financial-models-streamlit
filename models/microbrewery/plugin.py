"""Microbrewery plugin — wraps brewery_financial_model_all_in_one.py."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, PrivateAttr

# The legacy microbrewery code currently lives at <repo_root>/microbrewery/.
# Add it to sys.path so we can import it before Phase 0 reorganises files.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _REPO_ROOT / "microbrewery"
if str(_LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGACY_DIR))

from brewery_financial_model_all_in_one import (  # noqa: E402
    CapexItem,
    CostPoolInput,
    DebtFacility,
    DividendPolicy,
    MicrobreweryFinancialModel,
    ModelConfig,
    ModelInputs,
    OtherIncomeItem,
    phase_growth_series,
    write_comprehensive_excel_report,
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


class MicrobreweryInputs(BaseModel):
    """Top-level config knobs. Sales/cost/capex schedules are baked into the
    plugin for v1; more fields will be exposed as the UI grows."""

    horizon_months: int = 120
    start_date: str = "2025-01-01"
    price_inflation_annual: float = 0.015
    cost_inflation_annual: float = 0.015
    tax_rate: float = 0.25
    wacc_annual: float = 0.122
    initial_cash: float = 0.0


class MicrobreweryComputeResults(ModelResults):
    valuation: dict[str, Any]
    annual_dict: dict[str, Any]
    # Hold the raw ModelRunResult for report generation without re-running compute.
    _raw_result: Any = PrivateAttr(default=None)


def _build_legacy_model(inputs: MicrobreweryInputs) -> MicrobreweryFinancialModel:
    cfg = ModelConfig(
        start_date=inputs.start_date,
        months=inputs.horizon_months,
        pricing_cost_basis_month=24,
        price_inflation_annual=inputs.price_inflation_annual,
        cost_inflation_annual=inputs.cost_inflation_annual,
        tax_rate=inputs.tax_rate,
        wacc_annual=inputs.wacc_annual,
        exit_ev_ebitda_multiple=8.0,
        initial_cash=inputs.initial_cash,
    )
    div = DividendPolicy(
        enabled=True,
        model="cash_sweep",
        start_month=60,
        minimum_cash_position=1_500_000.0,
        payout_ratio=0.25,
    )
    idx = pd.date_range(cfg.start_date, periods=cfg.months, freq="MS")

    skus = pd.DataFrame([
        {"sku_id": 1, "name": "Pale Ale 330ml", "direct_cost_per_unit": 0.0,
         "markup_pct": 0.65, "relative_opex_weight": 1.0},
        {"sku_id": 2, "name": "Pilsner 500ml", "direct_cost_per_unit": 0.0,
         "markup_pct": 0.60, "relative_opex_weight": 1.1},
    ])
    channels = pd.DataFrame([
        {"channel": "Wholesale", "price_factor": 1.40},
        {"channel": "Retail", "price_factor": 2.00},
        {"channel": "E-Commerce", "price_factor": 1.75},
        {"channel": "On-Premise", "price_factor": 1.00},
    ])
    u_sku1 = phase_growth_series(idx, start_month=3, start_units=8_000,
                                 monthly_growth=0.04, stop_month=None, cap_units=25_000)
    u_sku2 = phase_growth_series(idx, start_month=3, start_units=6_000,
                                 monthly_growth=0.04, stop_month=None, cap_units=20_000)
    channel_mix = {"Wholesale": 0.45, "Retail": 0.35, "E-Commerce": 0.15, "On-Premise": 0.05}
    rows = []
    for date in idx:
        for sku_id, series in [(1, u_sku1), (2, u_sku2)]:
            total_units = float(series.loc[date])
            for channel, share in channel_mix.items():
                rows.append({"date": date, "sku_id": sku_id, "channel": channel,
                             "units": total_units * share})
    sales_plan = pd.DataFrame(rows)

    cost_pools = [
        CostPoolInput(name="Malt & Grain", cost_type="direct", behavior="variable",
                      allocation_driver="liters", unit_variable_cost=0.22),
        CostPoolInput(name="Hops & Yeast", cost_type="direct", behavior="variable",
                      allocation_driver="liters", unit_variable_cost=0.09),
        CostPoolInput(name="Packaging Materials", cost_type="direct", behavior="variable",
                      allocation_driver="units", unit_variable_cost=0.14),
        CostPoolInput(name="Indirect Labor", cost_type="indirect", behavior="step_fixed",
                      allocation_driver="liters", fixed_monthly_cost=22_000.0,
                      step_threshold=250_000.0, step_increment=2_000.0),
        CostPoolInput(name="Utilities", cost_type="indirect", behavior="variable",
                      allocation_driver="liters", unit_variable_cost=0.035),
        CostPoolInput(name="Marketing & Advertising", cost_type="indirect", behavior="blended",
                      allocation_driver="channel_revenue", fixed_monthly_cost=8_500.0,
                      unit_variable_cost=0.003, channel=None),
        CostPoolInput(name="Insurance", cost_type="indirect", behavior="fixed",
                      allocation_driver="revenue", fixed_monthly_cost=3_000.0),
        CostPoolInput(name="Administrative Expense", cost_type="indirect", behavior="blended",
                      allocation_driver="active_sku", fixed_monthly_cost=9_500.0,
                      unit_variable_cost=250.0),
    ]
    other_income_items = [
        OtherIncomeItem(other_income_name="Sponsorships", amount=15_000.0,
                        active=True, category="Commercial"),
    ]
    capex_items = [
        CapexItem(name="Land (non-depreciable)", amount=875_000, capex_month=0, depreciation_years=0),
        CapexItem(name="Building", amount=1_750_000, capex_month=0, depreciation_years=25),
        CapexItem(name="Brewhouse equipment", amount=1_250_000, capex_month=1, depreciation_years=10),
    ]
    debt_facilities = [
        DebtFacility(name="Mortgage", principal=750_000, annual_interest_rate=0.03,
                     draw_month=0, grace_months=6, term_months=120, repayment_type="linear"),
    ]
    equity_injections = {0: 5_500_000.0}

    legacy_inputs = ModelInputs(
        skus=skus,
        channels=channels,
        sales_plan=sales_plan,
        other_income_items=other_income_items,
        cost_pools=cost_pools,
        capex_items=capex_items,
        debt_facilities=debt_facilities,
        equity_injections=equity_injections,
    )
    return MicrobreweryFinancialModel(cfg, div, legacy_inputs)


class MicrobreweryPlugin:
    slug: str = "microbrewery"
    name: str = "Microbrewery Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Driver-based 10-year microbrewery financial model with full P&L, "
        "cash flow, balance sheet, and valuation."
    )
    icon: str | None = "🍺"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX}
    input_schema: type[BaseModel] = MicrobreweryInputs
    results_schema: type[ModelResults] = MicrobreweryComputeResults

    def default_inputs(self) -> MicrobreweryInputs:
        return MicrobreweryInputs()

    def compute(self, inputs: BaseModel) -> MicrobreweryComputeResults:
        assert isinstance(inputs, MicrobreweryInputs)
        legacy_model = _build_legacy_model(inputs)
        raw = legacy_model.run()
        valuation = {
            k: (float(v) if hasattr(v, "__float__") else v)
            for k, v in raw.valuation.items()
        }
        result = MicrobreweryComputeResults(
            valuation=valuation,
            annual_dict={str(k): v for k, v in raw.annual.to_dict().items()},
        )
        result._raw_result = raw
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)
        ev = results.valuation.get("enterprise_value", 0.0)
        st.metric("Enterprise Value (USD)", f"{ev:,.0f}")

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
        assert isinstance(results, MicrobreweryComputeResults)
        raw = results._raw_result
        if raw is None:
            assert isinstance(inputs, MicrobreweryInputs)
            recomputed = self.compute(inputs)
            raw = recomputed._raw_result

        out: dict[Format, bytes] = {}
        if Format.XLSX in formats:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                write_comprehensive_excel_report(raw, writer)
            out[Format.XLSX] = buf.getvalue()
        return out


MODEL: ModelPlugin = MicrobreweryPlugin()
