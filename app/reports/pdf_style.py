"""Shared reportlab-based PDF style for all plugin reports.

Plugins should NEVER instantiate SimpleDocTemplate or build Flowables from
scratch — call the helpers here. This is the single point of control for
branding, layout, and watermarking across the SaaS.

Typical use:

    from app.reports.pdf_style import (
        build_pdf, heading, body, metric_grid, dataframe_table,
    )

    sections = [
        heading("Executive summary"),
        metric_grid({"NPV": "USD 1.2M", "IRR": "18.4%"}),
        *dataframe_table(annual_df, title="Annual income statement"),
    ]
    pdf_bytes = build_pdf(title="Microbrewery Model", sections=sections)
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# --- Brand palette ----------------------------------------------------------

PRIMARY = colors.HexColor("#1f3a5f")
ACCENT = colors.HexColor("#2e7c5f")
GRAY_LIGHT = colors.HexColor("#f3f4f6")
GRAY_BORDER = colors.HexColor("#d1d5db")
TEXT_MUTED = colors.HexColor("#6b7280")


# --- Style registry ---------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    """Returns a single shared style sheet. Reuse across all helpers."""
    if hasattr(_styles, "_cache"):
        return _styles._cache  # type: ignore[attr-defined]

    base = getSampleStyleSheet()
    base.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=base["Title"],
            fontSize=32,
            leading=38,
            textColor=PRIMARY,
            alignment=TA_CENTER,
            spaceAfter=14,
        )
    )
    base.add(
        ParagraphStyle(
            name="CoverSubtitle",
            parent=base["Normal"],
            fontSize=14,
            leading=18,
            textColor=TEXT_MUTED,
            alignment=TA_CENTER,
            spaceAfter=30,
        )
    )
    base.add(
        ParagraphStyle(
            name="CoverMeta",
            parent=base["Normal"],
            fontSize=10,
            textColor=TEXT_MUTED,
            alignment=TA_CENTER,
        )
    )
    base.add(
        ParagraphStyle(
            name="SectionH1",
            parent=base["Heading1"],
            fontSize=18,
            leading=22,
            textColor=PRIMARY,
            spaceBefore=18,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="SectionH2",
            parent=base["Heading2"],
            fontSize=13,
            leading=17,
            textColor=PRIMARY,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    base.add(
        ParagraphStyle(
            name="Body",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            spaceAfter=8,
        )
    )
    base.add(
        ParagraphStyle(
            name="Footnote",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=TEXT_MUTED,
        )
    )
    _styles._cache = base  # type: ignore[attr-defined]
    return base


# --- Page chrome callbacks --------------------------------------------------


def _draw_watermark(canvas, watermark: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 64)
    canvas.setFillGray(0.85)
    try:
        canvas.setFillAlpha(0.35)
    except Exception:
        pass
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, watermark)
    canvas.restoreState()


def _draw_footer(canvas, doc, footer_text: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(2 * cm, 1.5 * cm, footer_text)
    canvas.drawRightString(A4[0] - 2 * cm, 1.5 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(GRAY_BORDER)
    canvas.setLineWidth(0.3)
    canvas.line(2 * cm, 2 * cm, A4[0] - 2 * cm, 2 * cm)
    canvas.restoreState()


# --- Flowable factories -----------------------------------------------------


def cover_section(title: str, subtitle: str = "") -> list:
    s = _styles()
    generated = datetime.now(timezone.utc).strftime("%B %d, %Y")
    return [
        Spacer(1, 4 * cm),
        Paragraph(title, s["CoverTitle"]),
        Paragraph(subtitle, s["CoverSubtitle"]) if subtitle else Spacer(1, 0),
        Spacer(1, 1 * cm),
        Paragraph(f"Generated {generated}", s["CoverMeta"]),
        PageBreak(),
    ]


def heading(text: str, level: int = 1) -> Paragraph:
    style = _styles()["SectionH1" if level == 1 else "SectionH2"]
    return Paragraph(text, style)


def body(text: str) -> Paragraph:
    return Paragraph(text, _styles()["Body"])


def metric_grid(metrics: dict[str, str], columns: int = 3) -> Table:
    """Card-grid of label/value pairs. Pass formatted strings (e.g. 'USD 1.2M')."""
    s = _styles()
    items = list(metrics.items())
    rows: list[list] = []
    for i in range(0, len(items), columns):
        chunk = items[i : i + columns]
        cells = []
        for label, value in chunk:
            html = (
                f'<para alignment="center">'
                f'<font size="8" color="#6b7280">{label}</font><br/>'
                f'<font size="14" color="#1f3a5f"><b>{value}</b></font>'
                f"</para>"
            )
            cells.append(Paragraph(html, s["Body"]))
        while len(cells) < columns:
            cells.append("")
        rows.append(cells)

    col_width = (A4[0] - 4 * cm) / columns
    t = Table(rows, colWidths=[col_width] * columns)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GRAY_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, GRAY_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, GRAY_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return t


def _format_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        if pd.isna(v):
            return ""
        if abs(v) >= 1_000_000:
            return f"{v:,.0f}"
        if abs(v) >= 1:
            return f"{v:,.2f}"
        return f"{v:.4f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def dataframe_table(
    df: pd.DataFrame,
    *,
    title: str | None = None,
    max_rows: int = 18,
    max_cols: int = 8,
) -> list:
    """Render a DataFrame as a styled table. Truncates with a note if needed."""
    flowables: list = []
    if title:
        flowables.append(heading(title, level=2))

    if df is None or df.empty:
        flowables.append(body("<i>No data available.</i>"))
        return flowables

    has_named_index = bool(df.index.name) or not isinstance(df.index, pd.RangeIndex)

    truncated = df.iloc[:max_rows, :max_cols].copy()

    header = [str(c) for c in truncated.columns]
    data: list[list[str]] = []
    if has_named_index:
        header = [str(truncated.index.name or "")] + header
    data.append(header)
    for idx, row in truncated.iterrows():
        cells = [_format_value(v) for v in row.values]
        if has_named_index:
            cells = [_format_value(idx)] + cells
        data.append(cells)

    n_cols = len(data[0])
    width = (A4[0] - 4 * cm) / n_cols
    t = Table(data, colWidths=[width] * n_cols, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRAY_LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.25, GRAY_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flowables.append(t)

    truncation: list[str] = []
    if len(df) > max_rows:
        truncation.append(f"{len(df) - max_rows} more row(s)")
    if len(df.columns) > max_cols:
        truncation.append(f"{len(df.columns) - max_cols} more column(s)")
    if truncation:
        flowables.append(Spacer(1, 4))
        flowables.append(
            Paragraph(
                f"<i>{' and '.join(truncation)} omitted for space.</i>",
                _styles()["Footnote"],
            )
        )
    flowables.append(Spacer(1, 12))
    return flowables


# --- Top-level builder ------------------------------------------------------


def build_pdf(
    *,
    title: str,
    sections: Iterable,
    subtitle: str = "",
    watermark: str | None = None,
    footer_text: str = "Zenkos Financial Models",
    author: str = "Zenkos",
) -> bytes:
    """Assemble a full PDF document. Returns the raw bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.5 * cm,
        title=title,
        author=author,
    )

    flowables = list(cover_section(title, subtitle)) + list(sections)

    def _on_page(canvas, doc_):
        if watermark:
            _draw_watermark(canvas, watermark)
        _draw_footer(canvas, doc_, footer_text)

    doc.build(flowables, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
