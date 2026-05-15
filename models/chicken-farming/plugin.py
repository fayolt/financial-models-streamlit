"""Chicken-farming plugin — wraps broiler_model.generate_model_outputs."""
from __future__ import annotations

import io
import sys
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, PrivateAttr

# Legacy broiler code lives at <repo_root>/chicken-farming/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _REPO_ROOT / "chicken-farming"
if str(_LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGACY_DIR))

from broiler_model import Assumptions, generate_model_outputs  # noqa: E402

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


class ChickenFarmingInputs(BaseModel):
    """Top-level knobs. All other Assumptions fields use baked-in defaults
    from broiler_model.Assumptions (more will be exposed as UI matures)."""

    flock_size: int = 20_000
    batches_per_year: int = 6
    mortality_pct: float = 5.0
    feed_cost_per_kg: float = 0.42
    selling_price_per_kg: float = 1.85
    chick_cost_per_bird: float = 0.55
    capex_total: float = 1_230_000.0


class ChickenFarmingResults(ModelResults):
    valuation: dict[str, Any]
    timeline: dict[str, Any]

    _raw_outputs: Any = PrivateAttr(default=None)


def _build_assumptions(inputs: ChickenFarmingInputs) -> Assumptions:
    """Map the top-level plugin knobs onto the legacy Assumptions dataclass.

    CapEx total is split 77/23 between housing/equipment to mirror the
    defaults (950k/280k = ~77/23)."""
    housing_share = 0.77
    return replace(
        Assumptions(),
        birds_per_cycle=int(inputs.flock_size),
        cycles_per_year=int(inputs.batches_per_year),
        mortality_rate=float(inputs.mortality_pct) / 100.0,
        feed_cost_per_kg=float(inputs.feed_cost_per_kg),
        live_price_per_kg=float(inputs.selling_price_per_kg),
        chick_cost=float(inputs.chick_cost_per_bird),
        capex_housing=float(inputs.capex_total) * housing_share,
        capex_equipment=float(inputs.capex_total) * (1.0 - housing_share),
    )


def _rows_to_df(rows: Any) -> pd.DataFrame:
    """Convert a list of dataclasses / dicts / arbitrary objects to a DataFrame."""
    if rows is None:
        return pd.DataFrame()
    if isinstance(rows, pd.DataFrame):
        return rows
    records: list[dict[str, Any]] = []
    for row in rows:
        if is_dataclass(row):
            records.append(asdict(row))
        elif isinstance(row, dict):
            records.append(row)
        else:
            records.append({"value": row})
    return pd.DataFrame(records)


class ChickenFarmingPlugin:
    slug: str = "chicken-farming"
    name: str = "Chicken Farming Financial Model"
    version: str = "0.1.0"
    description: str = (
        "Broiler chicken farm financial model with production cycles, "
        "annual P&L, financial statements, and DCF valuation."
    )
    icon: str | None = "🐔"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    supported_formats: set[Format] = {Format.XLSX}
    input_schema: type[BaseModel] = ChickenFarmingInputs
    results_schema: type[ModelResults] = ChickenFarmingResults

    def default_inputs(self) -> ChickenFarmingInputs:
        return ChickenFarmingInputs()

    def compute(self, inputs: BaseModel) -> ChickenFarmingResults:
        assert isinstance(inputs, ChickenFarmingInputs)
        assumptions = _build_assumptions(inputs)
        raw = generate_model_outputs(assumptions)

        valuation = {
            k: (float(v) if isinstance(v, (int, float)) and v is not None else v)
            for k, v in (raw.get("valuation") or {}).items()
        }
        timeline = dict(raw.get("timeline") or {})

        result = ChickenFarmingResults(
            valuation=valuation,
            timeline=timeline,
        )
        result._raw_outputs = raw
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running model..."):
            results = self.compute(inputs)
        npv_val = results.valuation.get("npv", 0.0) or 0.0
        irr_val = results.valuation.get("irr")
        col1, col2 = st.columns(2)
        col1.metric("NPV (USD)", f"{float(npv_val):,.0f}")
        if irr_val is not None:
            col2.metric("IRR", f"{float(irr_val) * 100:,.2f}%")

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
        assert isinstance(results, ChickenFarmingResults)
        raw = results._raw_outputs
        if raw is None:
            assert isinstance(inputs, ChickenFarmingInputs)
            recomputed = self.compute(inputs)
            raw = recomputed._raw_outputs

        out: dict[Format, bytes] = {}

        if Format.XLSX in formats:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                # Assumptions schedule
                assumptions_df = pd.DataFrame(raw.get("assumptions_schedule") or [])
                if not assumptions_df.empty:
                    assumptions_df.to_excel(writer, sheet_name="Assumptions", index=False)

                # Production cycles
                cycles_df = _rows_to_df(raw.get("cycles"))
                if not cycles_df.empty:
                    cycles_df.to_excel(writer, sheet_name="Production Cycles", index=False)

                # Annual P&L summary (single AnnualSummary dataclass)
                annual = raw.get("annual")
                if annual is not None:
                    annual_record = asdict(annual) if is_dataclass(annual) else dict(annual)
                    pd.DataFrame([annual_record]).to_excel(
                        writer, sheet_name="Annual Summary", index=False
                    )

                # Discounted cash flow rows
                cashflows_df = _rows_to_df(raw.get("cashflows"))
                if not cashflows_df.empty:
                    cashflows_df.to_excel(writer, sheet_name="Cash Flows", index=False)

                # Financial statements
                statements = raw.get("financial_statements") or {}
                for key, sheet_name in (
                    ("income_statement", "Income Statement"),
                    ("balance_sheet", "Balance Sheet"),
                    ("cash_flow_statement", "Cash Flow Statement"),
                ):
                    stmt_df = _rows_to_df(statements.get(key))
                    if not stmt_df.empty:
                        stmt_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # Revenue summary (dict of category -> list[dict])
                revenue_summary = raw.get("revenue_summary") or {}
                if isinstance(revenue_summary, dict):
                    for key, rows in revenue_summary.items():
                        rev_df = _rows_to_df(rows)
                        if not rev_df.empty:
                            sheet = f"Revenue {key}"[:31]
                            rev_df.to_excel(writer, sheet_name=sheet, index=False)

                # Valuation + timeline metrics
                metrics_rows: list[dict[str, Any]] = []
                for k, v in (raw.get("valuation") or {}).items():
                    metrics_rows.append({"metric": f"valuation.{k}", "value": v})
                for k, v in (raw.get("timeline") or {}).items():
                    metrics_rows.append({"metric": f"timeline.{k}", "value": v})
                if metrics_rows:
                    pd.DataFrame(metrics_rows).to_excel(
                        writer, sheet_name="Valuation & Metrics", index=False
                    )

            out[Format.XLSX] = buf.getvalue()

        return out


MODEL: ModelPlugin = ChickenFarmingPlugin()
