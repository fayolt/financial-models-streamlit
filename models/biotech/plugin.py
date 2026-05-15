"""Biotech plugin — wraps valuation_codex_package (Pharma/Biotech rNPV DCF).

For v1 we expose a handful of top-level valuation knobs and bake the rest as
defaults. PDF input extraction, Monte Carlo, scenario tooling, and AI/RAG
commentary from the legacy Streamlit app are intentionally deferred to
Phase 4 (Enterprise tier).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, PrivateAttr

# Legacy biotech code lives at <repo_root>/biotech/. Add it to sys.path so we
# can `import valuation_codex_package` without modifying the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _REPO_ROOT / "biotech"
if str(_LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGACY_DIR))

from valuation_codex_package import (  # noqa: E402
    ModelConfig,
    Portfolio,
    Product,
    ProductConfig,
    ValuationEngine,
    ValuationResult,
)

# --- Pandas 3.x / Copy-on-Write compat shim --------------------------------
# `Product.build_revenue_series` in valuation_codex_package writes to
# `series.values[:] = ...`, which is read-only under pandas >= 2.2 CoW (and
# always read-only under pandas 3.0). We can't modify the legacy file, so we
# monkey-patch a CoW-safe replacement here. Logic mirrors the original
# implementation in biotech/valuation_codex_package/core.py.
def _build_revenue_series_cow_safe(self: Product) -> pd.Series:  # noqa: D401
    years = self.model_config.years
    cfg = self.config
    ramp_factors = list(self.model_config.sales_ramp_factors or [])
    if cfg.sales_ramp_shape:
        ramp_len = int(cfg.sales_ramp_length or len(ramp_factors) or 1)
        ramp_factors = self._ramp_shape_values(cfg.sales_ramp_shape, ramp_len)
    elif cfg.sales_ramp_length is not None:
        ramp_len = int(cfg.sales_ramp_length)
        if ramp_len <= 0:
            ramp_factors = []
        elif not ramp_factors:
            ramp_factors = [1.0] * ramp_len
        elif ramp_len <= len(ramp_factors):
            ramp_factors = ramp_factors[:ramp_len]
        else:
            ramp_factors = ramp_factors + [ramp_factors[-1]] * (ramp_len - len(ramp_factors))
    if not cfg.include_in_consolidation:
        return pd.Series(0.0, index=years, name=f"{cfg.name}_revenue")

    years_arr = np.asarray(years, dtype=int)
    launch_year = self._launch_year()
    patent_end = self._patent_end_year()
    years_since_launch = years_arr - launch_year
    in_patent = years_arr <= patent_end

    ramp = self._ramp_factors_array(years_since_launch, ramp_factors)
    base_target = np.where(in_patent, cfg.patent_revenue_target, cfg.post_patent_revenue_target)
    growth_rate = np.where(in_patent, cfg.market_growth_patent, cfg.market_growth_post)
    growth_years = self._growth_years(
        years_arr,
        years_since_launch,
        in_patent,
        len(ramp_factors),
        patent_end,
    )
    target_with_growth = base_target * np.power(1.0 + growth_rate, growth_years)
    years_since_patent_end = years_arr - (patent_end + 1)
    erosion = self._erosion_factors_array(years_since_patent_end, cfg.post_patent_erosion)
    return pd.Series(
        ramp * target_with_growth * erosion,
        index=years,
        name=f"{cfg.name}_revenue",
    )


Product.build_revenue_series = _build_revenue_series_cow_safe
# --- end compat shim --------------------------------------------------------

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


class BiotechInputs(BaseModel):
    """Top-level pharma/biotech valuation knobs.

    Everything else (cost ratios, ramp curves, stage durations, milestones,
    working-capital pct, EV/EBITDA exit multiple, etc.) is baked into the
    plugin for v1; richer schemas come in Phase 2.
    """

    peak_revenue: float = Field(
        default=500_000_000.0,
        description="Peak annual on-patent revenue for the lead asset (USD).",
    )
    launch_year: int = Field(
        default=2027,
        description="Expected commercial launch year of the lead asset.",
    )
    patent_expiry_year: int = Field(
        default=2042,
        description="Patent / exclusivity expiry year; revenue erodes thereafter.",
    )
    gross_margin: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Gross margin during patent life (1 - COGS%).",
    )
    rd_capex: float = Field(
        default=200_000_000.0,
        ge=0.0,
        description="Remaining R&D + capex to launch (USD), spread pre-launch.",
    )
    wacc: float = Field(
        default=0.10,
        gt=0.0,
        lt=1.0,
        description="Discount rate / WACC used for the rNPV DCF.",
    )
    success_probability: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Probability of technical and regulatory success.",
    )


class BiotechResults(ModelResults):
    summary: dict[str, Any]

    # Raw artefacts needed by generate_report without rerunning compute().
    _valuation_result: Any = PrivateAttr(default=None)
    _model_config: Any = PrivateAttr(default=None)


def _compute_irr(cashflows: list[float]) -> float | None:
    """Bisection IRR — mirrors biotech/streamlit_app.py::_compute_irr."""
    if not cashflows or all(cf >= 0 for cf in cashflows) or all(cf <= 0 for cf in cashflows):
        return None

    def npv(rate: float) -> float:
        return sum(cf / ((1 + rate) ** idx) for idx, cf in enumerate(cashflows))

    low, high = -0.9, 1.0
    npv_low, npv_high = npv(low), npv(high)
    attempts = 0
    while npv_low * npv_high > 0 and attempts < 10:
        high += 1.0
        npv_high = npv(high)
        attempts += 1
    if npv_low * npv_high > 0:
        return None
    for _ in range(60):
        mid = (low + high) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-6:
            return mid
        if npv_low * npv_mid <= 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    return (low + high) / 2


def _build_portfolio(inputs: BiotechInputs) -> tuple[Portfolio, ModelConfig]:
    """Build a single-asset Portfolio from the high-level inputs."""
    first_year = min(inputs.launch_year, inputs.launch_year - 1)
    # Make sure we have at least 3 years of pre-launch runway captured.
    first_year = inputs.launch_year - 3
    horizon_end = max(inputs.patent_expiry_year + 5, inputs.launch_year + 15)
    n_years = horizon_end - first_year + 1

    model_cfg = ModelConfig(
        first_year=first_year,
        n_years=n_years,
        currency="USD",
        tax_rate=0.25,
        discount_rate=inputs.wacc,
        ev_ebitda_multiple=8.0,
        working_capital_pct_sales=0.08,
    )

    time_to_market = max(0, inputs.launch_year - first_year)
    patent_years = max(1, inputs.patent_expiry_year - inputs.launch_year + 1)
    cogs_patent = max(0.0, min(1.0, 1.0 - inputs.gross_margin))

    product_cfg = ProductConfig(
        name="Lead Asset",
        stage="Phase II",
        success_prob=inputs.success_probability,
        include_in_consolidation=True,
        time_to_market=time_to_market,
        patent_years=patent_years,
        preexisting_market=False,
        patent_revenue_target=inputs.peak_revenue,
        post_patent_revenue_target=inputs.peak_revenue * 0.30,
        market_growth_patent=0.02,
        market_growth_post=0.0,
        cogs_patent=cogs_patent,
        cogs_post=min(1.0, cogs_patent + 0.15),
        labor_pct=0.08,
        overhead_pct=0.05,
        material_pct=0.05,
        sales_marketing_pct=0.18,
        gna_pct=0.08,
        royalty_pct=0.03,
        rd_remaining_pre_launch=inputs.rd_capex * 0.6,
        rd_annual_post_launch=inputs.peak_revenue * 0.05,
        capex_remaining_pre_launch=inputs.rd_capex * 0.4,
        capex_annual_post_launch=inputs.peak_revenue * 0.02,
        rd_capitalization_ratio=0.5,
        rd_amort_years=10,
        capex_dep_years=10,
    )

    portfolio = Portfolio([Product(product_cfg, model_cfg)], model_cfg)
    return portfolio, model_cfg


def _summarise(
    inputs: BiotechInputs,
    valuation_result: ValuationResult,
    model_cfg: ModelConfig,
) -> dict[str, Any]:
    cons = valuation_result.consolidated
    dcf = valuation_result.dcf_table

    cashflows = dcf["fcff"].tolist()
    if "terminal_value" in dcf.columns:
        cashflows[-1] = cashflows[-1] + float(dcf["terminal_value"].fillna(0.0).iloc[-1])
    irr = _compute_irr(cashflows)

    capex_total = -float(cons["capex_cash"].sum()) if "capex_cash" in cons.columns else 0.0
    opex_cols = [c for c in ("sales_marketing", "gna", "royalty", "rd_cash") if c in cons.columns]
    opex_annual_avg = (
        -float(cons[opex_cols].sum(axis=1).mean()) if opex_cols else 0.0
    )
    revenue_annual_avg = float(cons["revenue"].mean()) if "revenue" in cons.columns else 0.0
    peak_revenue_actual = float(cons["revenue"].max()) if "revenue" in cons.columns else 0.0
    peak_ebitda = float(cons["ebitda"].max()) if "ebitda" in cons.columns else 0.0

    return {
        "currency": model_cfg.currency,
        "rnpv": float(valuation_result.rnpv),
        "npv": float(valuation_result.rnpv),
        "irr": irr,
        "discount_rate": model_cfg.discount_rate,
        "tax_rate": model_cfg.tax_rate,
        "launch_year": inputs.launch_year,
        "patent_expiry_year": inputs.patent_expiry_year,
        "success_probability": inputs.success_probability,
        "peak_revenue_input": inputs.peak_revenue,
        "peak_revenue_modelled": peak_revenue_actual,
        "peak_ebitda_modelled": peak_ebitda,
        "capex_total": capex_total,
        "opex_annual_avg": opex_annual_avg,
        "revenue_annual_avg": revenue_annual_avg,
    }


class BiotechPlugin:
    slug: str = "biotech"
    name: str = "Pharma / Biotech Valuation"
    version: str = "0.1.0"
    description: str = (
        "Risk-adjusted DCF (rNPV) valuation for a pharma/biotech asset: "
        "stage-gated success probabilities, sales ramp, patent erosion, "
        "R&D + capex, and EV/EBITDA terminal value."
    )
    icon: str | None = "🧬"
    minimum_tier: SubscriptionTier = SubscriptionTier.FREE
    # Phase 4 will add Format.DOCX, plus AI commentary via RAG.
    supported_formats: set[Format] = {Format.XLSX, Format.PDF}
    input_schema: type[BaseModel] = BiotechInputs
    results_schema: type[ModelResults] = BiotechResults

    def default_inputs(self) -> BiotechInputs:
        return BiotechInputs()

    def compute(self, inputs: BaseModel) -> BiotechResults:
        assert isinstance(inputs, BiotechInputs)
        portfolio, model_cfg = _build_portfolio(inputs)
        valuation_result = ValuationEngine(portfolio).run()
        summary = _summarise(inputs, valuation_result, model_cfg)
        result = BiotechResults(summary=summary)
        result._valuation_result = valuation_result
        result._model_config = model_cfg
        return result

    def render(self, *, user: User, scenario: Scenario | None = None) -> None:
        import streamlit as st

        st.subheader(self.name)
        st.write(self.description)
        inputs = self.default_inputs()
        with st.spinner("Running rNPV valuation..."):
            results = self.compute(inputs)
        col1, col2, col3 = st.columns(3)
        col1.metric("rNPV (USD)", f"{results.summary['rnpv']:,.0f}")
        irr = results.summary.get("irr")
        col2.metric("IRR", f"{irr:.1%}" if isinstance(irr, (int, float)) else "n/a")
        col3.metric(
            "Peak revenue (USD)",
            f"{results.summary['peak_revenue_modelled']:,.0f}",
        )

        from app.reports.ui import render_commentary_section, render_report_downloads
        render_report_downloads(self, inputs, results, user)
        render_commentary_section(
            self, inputs, results, user, self._commentary_summary
        )

    def _commentary_summary(self, inputs, results) -> dict:
        return {
            "headline_metrics": {
                "rNPV (USD)": results.summary.get("rnpv"),
                "IRR": results.summary.get("irr"),
                "Peak revenue modelled (USD)": results.summary.get(
                    "peak_revenue_modelled"
                ),
            },
            "inputs": {
                "Peak revenue target (USD)": inputs.peak_revenue,
                "Launch year": inputs.launch_year,
                "Patent expiry year": inputs.patent_expiry_year,
                "Gross margin": inputs.gross_margin,
                "R&D capex (USD)": inputs.rd_capex,
                "WACC": inputs.wacc,
                "Probability of technical success": inputs.success_probability,
            },
        }

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
        assert isinstance(results, BiotechResults)
        if results._valuation_result is None:
            assert isinstance(inputs, BiotechInputs)
            results = self.compute(inputs)

        out: dict[Format, bytes] = {}
        if Format.XLSX in formats:
            vr: ValuationResult = results._valuation_result
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                pd.DataFrame(
                    [{"Metric": k, "Value": v} for k, v in results.summary.items()]
                ).to_excel(writer, index=False, sheet_name="Summary")

                cons = vr.consolidated.copy()
                cons.index.name = "Year"
                cons.to_excel(writer, sheet_name="Consolidated P&L+FCFF")

                # Build a slim P&L view for readability.
                pnl_cols = [
                    c
                    for c in (
                        "revenue",
                        "cogs",
                        "labor",
                        "overhead",
                        "materials",
                        "sales_marketing",
                        "gna",
                        "royalty",
                        "rd_expense_pnl",
                        "depreciation",
                        "ebit",
                        "ebitda",
                        "tax",
                        "nopat",
                    )
                    if c in cons.columns
                ]
                if pnl_cols:
                    pnl = cons[pnl_cols].copy()
                    pnl.index.name = "Year"
                    pnl.to_excel(writer, sheet_name="P&L")

                # Revenue projection split out for quick scanning.
                rev_cols = [c for c in ("revenue", "ebitda", "fcff", "fcff_after_wc") if c in cons.columns]
                if rev_cols:
                    rev = cons[rev_cols].copy()
                    rev.index.name = "Year"
                    rev.to_excel(writer, sheet_name="Revenue & FCFF")

                dcf = vr.dcf_table.copy()
                dcf.index.name = "Year"
                dcf.to_excel(writer, sheet_name="DCF")

                for prod_name, prod_df in vr.per_product.items():
                    sheet = f"Product - {prod_name}"[:31]
                    df = prod_df.copy()
                    df.index.name = "Year"
                    df.to_excel(writer, sheet_name=sheet)
            out[Format.XLSX] = buf.getvalue()
        if Format.PDF in formats:
            out[Format.PDF] = self._build_pdf(results, options, user)
        return out

    def _build_pdf(
        self,
        results: "BiotechResults",
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

        summary = results.summary
        rnpv = summary.get("rnpv")
        irr = summary.get("irr")
        peak_rev = summary.get("peak_revenue_modelled")

        def _fmt_usd(v) -> str:
            return f"USD {v:,.0f}" if isinstance(v, (int, float)) else "n/a"

        metrics = {
            "rNPV": _fmt_usd(rnpv),
            "IRR": f"{irr * 100:.2f}%" if isinstance(irr, (int, float)) else "n/a",
            "Peak revenue (modelled)": _fmt_usd(peak_rev),
        }

        vr: ValuationResult | None = results._valuation_result
        cons_df = None
        dcf_df = None
        per_product_df = None
        if vr is not None:
            cons = vr.consolidated.copy()
            cons.index.name = "Year"
            pnl_cols = [
                c for c in (
                    "revenue", "cogs", "sales_marketing", "gna",
                    "ebitda", "ebit", "nopat",
                ) if c in cons.columns
            ]
            if pnl_cols:
                cons_df = cons[pnl_cols]

            dcf = vr.dcf_table.copy()
            dcf.index.name = "Year"
            dcf_cols = [
                c for c in ("fcff", "discount_factor", "pv_fcff", "terminal_value")
                if c in dcf.columns
            ]
            dcf_df = dcf[dcf_cols] if dcf_cols else dcf

            if vr.per_product:
                first_prod = next(iter(vr.per_product))
                pdf_df = vr.per_product[first_prod].copy()
                pdf_df.index.name = "Year"
                prod_cols = [
                    c for c in ("revenue", "ebitda", "fcff") if c in pdf_df.columns
                ]
                if prod_cols:
                    per_product_df = pdf_df[prod_cols]

        sections = [
            heading("Executive summary"),
            body(self.description),
            metric_grid(metrics),
            PageBreak(),
            heading("Consolidated P&L"),
            *(
                dataframe_table(cons_df, max_rows=14)
                if cons_df is not None
                else [body("Consolidated P&L not available.")]
            ),
            PageBreak(),
            heading("DCF schedule"),
            *(
                dataframe_table(dcf_df, max_rows=14)
                if dcf_df is not None
                else [body("DCF schedule not available.")]
            ),
            *(
                [heading("Lead asset summary"), *dataframe_table(per_product_df, max_rows=14)]
                if per_product_df is not None
                else []
            ),
        ]

        return build_pdf(
            title=self.name,
            subtitle=f"Prepared for {user.email}",
            sections=sections,
            watermark=options.watermark,
        )


MODEL: ModelPlugin = BiotechPlugin()
