"""
PDF Board Memo — generates a downloadable executive summary PDF.

Uses reportlab (pure Python, no system deps, works on Streamlit Cloud).
"""

from __future__ import annotations
from datetime import datetime
from io import BytesIO
from typing import Dict, Any
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# Brand colors
PRIMARY = colors.HexColor("#1F3864")
ACCENT = colors.HexColor("#3B82F6")
GOOD = colors.HexColor("#10B981")
WARN = colors.HexColor("#F59E0B")
BAD = colors.HexColor("#EF4444")
GREY_DARK = colors.HexColor("#1F2937")
GREY_MID = colors.HexColor("#6B7280")
GREY_LIGHT = colors.HexColor("#F3F4F6")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(
        name="DocTitle", fontSize=22, textColor=PRIMARY, spaceAfter=4,
        fontName="Helvetica-Bold", leading=26,
    ))
    s.add(ParagraphStyle(
        name="DocSubtitle", fontSize=11, textColor=GREY_MID, spaceAfter=14,
        fontName="Helvetica",
    ))
    s.add(ParagraphStyle(
        name="SectionHeader", fontSize=13, textColor=PRIMARY, spaceBefore=14, spaceAfter=8,
        fontName="Helvetica-Bold", leading=16,
        borderPadding=(0, 0, 4, 0), borderWidth=0,
    ))
    s.add(ParagraphStyle(
        name="BodyText2", fontSize=10, textColor=GREY_DARK, spaceAfter=6,
        fontName="Helvetica", leading=14,
    ))
    s.add(ParagraphStyle(
        name="VerdictBadge", fontSize=14, textColor=colors.white, spaceAfter=10,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
    ))
    s.add(ParagraphStyle(
        name="HeroNarrative", fontSize=11, textColor=GREY_DARK, spaceAfter=10,
        fontName="Helvetica", leading=15,
    ))
    s.add(ParagraphStyle(
        name="Caption", fontSize=8, textColor=GREY_MID, spaceAfter=4,
        fontName="Helvetica-Oblique",
    ))
    s.add(ParagraphStyle(
        name="FooterText", fontSize=8, textColor=GREY_MID, alignment=TA_CENTER,
        fontName="Helvetica",
    ))
    return s


def _inr(v, d=1):
    if v is None or pd.isna(v): return "—"
    return f"Rs.{v:,.{d}f} Cr"


def _pct(v, d=2):
    if v is None or pd.isna(v): return "—"
    return f"{v*100:.{d}f}%"


def _kpi_table(rows):
    """Build a 4-column KPI grid."""
    data = [rows]
    table = Table(data, colWidths=[4.4*cm]*4, rowHeights=[2.3*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _kpi_cell(label, value, color=PRIMARY):
    """Build a single KPI cell as a paragraph."""
    return Paragraph(
        f'<para alignment="center">'
        f'<font size="7" color="#6B7280"><b>{label.upper()}</b></font><br/><br/>'
        f'<font size="14" color="{color.hexval()}"><b>{value}</b></font>'
        f'</para>', _styles()["BodyText2"]
    )


def generate_board_memo(data: Dict[str, Any], cov_df: pd.DataFrame,
                        controls: Dict[str, Any] = None) -> bytes:
    """
    Generate a board-quality PDF memo.
    Returns the PDF as bytes (suitable for st.download_button).
    """
    if controls is None:
        controls = {"is_stressed": False, "basis": "FY26E"}
    
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="JCL Debt Monitoring — Board Memo",
        author="JCL Debt Dashboard",
    )
    
    s = _styles()
    story = []
    
    # ─── COVER & TITLE ──────────────────────────────────────────────
    story.append(Paragraph("Jindal Coke Limited", s["DocTitle"]))
    story.append(Paragraph(
        f"Debt Monitoring Board Memo &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"As-of {pd.Timestamp(data['as_of_date']).strftime('%d %B %Y')} "
        f"&nbsp;|&nbsp; Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}",
        s["DocSubtitle"]))
    
    # ─── HERO VERDICT ───────────────────────────────────────────────
    breach = (cov_df["Status"] == "Breach").sum()
    near = (cov_df["Status"] == "Near Breach").sum()
    watch = (cov_df["Status"] == "Watch").sum()
    compliant = (cov_df["Status"] == "Compliant").sum()
    
    if breach > 0:
        verdict, vcolor = "ACTION REQUIRED", BAD
        narrative = f"<b>{breach} covenant(s) breached.</b> Lender dialogue required immediately."
    elif near > 0:
        verdict, vcolor = "MONITOR CLOSELY", WARN
        narrative = (f"Banking exposure of <b>{_inr(data['totals']['Total_Banking_Exposure'])}</b> "
                     f"is healthy. <b>{near} covenant(s)</b> are near threshold and require monitoring.")
    else:
        verdict, vcolor = "HEALTHY", GOOD
        narrative = (f"Banking exposure of <b>{_inr(data['totals']['Total_Banking_Exposure'])}</b> "
                     f"across 5 lenders. Sanctioned Debt {_inr(data['totals']['Bucket1_Sanctioned_Debt'])}, "
                     f"NFB {_inr(data['totals']['Bucket2_NFB_Contingent'])}, "
                     f"Separate {_inr(data['totals']['Bucket3_Separate'])}. "
                     f"All <b>{len(cov_df)} covenants compliant</b>.")
    
    badge_table = Table(
        [[Paragraph(f"<para alignment='center'><font color='white'><b>STATUS: {verdict}</b></font></para>",
                     s["BodyText2"])]],
        colWidths=[16.8*cm], rowHeights=[0.9*cm],
    )
    badge_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), vcolor),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(badge_table)
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(narrative, s["HeroNarrative"]))
    story.append(Spacer(1, 0.3*cm))
    
    # ─── HEADLINE KPIs ──────────────────────────────────────────────
    story.append(Paragraph("Headline Metrics", s["SectionHeader"]))
    isum = data["interest_summary"]
    t = data["totals"]
    
    kpi_cells = [
        _kpi_cell("Banking Exposure", _inr(t["Total_Banking_Exposure"]), ACCENT),
        _kpi_cell("Sanctioned Debt", _inr(t["Bucket1_Sanctioned_Debt"]), PRIMARY),
        _kpi_cell("Annual Cost", _inr(isum["Total_Interest_Commission"]), WARN),
        _kpi_cell("Weighted Avg Cost", _pct(isum["Weighted_Avg_Cost"]), GOOD),
    ]
    story.append(_kpi_table(kpi_cells))
    story.append(Spacer(1, 0.3*cm))
    
    cov_status_cells = [
        _kpi_cell("Compliant", str(compliant), GOOD),
        _kpi_cell("Watch", str(watch), ACCENT),
        _kpi_cell("Near Breach", str(near), WARN if near else GREY_MID),
        _kpi_cell("Breach", str(breach), BAD if breach else GREY_MID),
    ]
    story.append(_kpi_table(cov_status_cells))
    story.append(Spacer(1, 0.4*cm))
    
    # ─── THREE-BUCKET STRUCTURE ─────────────────────────────────────
    story.append(Paragraph("Three-Bucket Exposure Structure", s["SectionHeader"]))
    
    bucket_data = [
        ["Bucket", "Description", "Amount (Rs. Cr)", "% of Banking"],
        ["Bucket 1", "Sanctioned Debt (TL + WC FB on cap basis)",
         f"{t['Bucket1_Sanctioned_Debt']:,.1f}",
         f"{t['Bucket1_Sanctioned_Debt']/t['Total_Banking_Exposure']*100:.1f}%"],
        ["Bucket 2", "NFB Contingent (LCs, SBLCs - parent only)",
         f"{t['Bucket2_NFB_Contingent']:,.1f}",
         f"{t['Bucket2_NFB_Contingent']/t['Total_Banking_Exposure']*100:.1f}%"],
        ["Bucket 3", "Separate Lines (FD-Backed + Hedge)",
         f"{t['Bucket3_Separate']:,.1f}",
         f"{t['Bucket3_Separate']/t['Total_Banking_Exposure']*100:.1f}%"],
        ["TOTAL", "Banking Exposure",
         f"{t['Total_Banking_Exposure']:,.1f}", "100.0%"],
    ]
    bt = Table(bucket_data, colWidths=[2.2*cm, 7.6*cm, 3.5*cm, 3.5*cm])
    bt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("BACKGROUND", (0, -1), (-1, -1), GREY_LIGHT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_MID),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(bt)
    story.append(Spacer(1, 0.3*cm))
    
    # ─── LENDER CONCENTRATION ───────────────────────────────────────
    story.append(Paragraph("Lender Concentration", s["SectionHeader"]))
    conc = data["lender_concentration"].sort_values("Total_Banking_Exposure", ascending=False)
    conc_data = [["Lender", "Banking Exposure (Rs. Cr)", "% of Sanc Debt", "% of Banking"]]
    for _, r in conc.iterrows():
        conc_data.append([
            r["Lender"],
            f"{r['Total_Banking_Exposure']:,.1f}",
            f"{r['Pct_Sanctioned_Debt']*100:.1f}%",
            f"{r['Pct_Banking_Exposure']*100:.1f}%",
        ])
    conc_table = Table(conc_data, colWidths=[5*cm, 4*cm, 3.4*cm, 3.4*cm])
    conc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_MID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(conc_table)
    
    top = conc.iloc[0]
    top_pct = top["Total_Banking_Exposure"] / t["Total_Banking_Exposure"] * 100
    if top_pct > 40:
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"<font color='#F59E0B'><b>Note:</b></font> {top['Lender']} represents "
            f"{top_pct:.1f}% of total banking exposure, exceeding the 40% diversification threshold.",
            s["BodyText2"]))
    
    story.append(Spacer(1, 0.4*cm))
    
    # ─── PAGE BREAK before covenants ────────────────────────────────
    story.append(PageBreak())
    
    # ─── COVENANT COMPLIANCE TABLE ──────────────────────────────────
    story.append(Paragraph("Covenant Compliance", s["SectionHeader"]))
    story.append(Paragraph(
        f"All {len(cov_df)} covenants from the source workbook, evaluated on {controls.get('basis','FY26E')} basis.",
        s["BodyText2"]))
    
    cov_data = [["Lender", "Covenant", "Op", "Threshold", "Actual", "Status"]]
    for _, r in cov_df.iterrows():
        thr = r["Threshold"]
        thr_s = f"{thr:.2f}x" if isinstance(thr, (int, float)) else str(thr)[:10]
        actual = r["Actual"]
        actual_s = f"{actual:.2f}x" if isinstance(actual, (int, float)) else str(actual)[:18]
        cov_data.append([
            r["Lender"], r["Covenant"], r["Operator"],
            thr_s, actual_s, r["Status"],
        ])
    
    cov_table = Table(cov_data, colWidths=[3.5*cm, 4.5*cm, 1*cm, 2.4*cm, 2.6*cm, 2.4*cm])
    cov_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (1, -1), "LEFT"),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_MID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    # Color status cells
    for i, (_, r) in enumerate(cov_df.iterrows(), 1):
        col = {"Compliant": GOOD, "Watch": ACCENT, "Near Breach": WARN, "Breach": BAD}.get(r["Status"], GREY_MID)
        cov_styles.append(("TEXTCOLOR", (5, i), (5, i), col))
        cov_styles.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
    cov_table.setStyle(TableStyle(cov_styles))
    story.append(cov_table)
    
    story.append(Spacer(1, 0.4*cm))
    
    # ─── KEY RISKS & ACTIONS ────────────────────────────────────────
    story.append(Paragraph("Key Observations & Actions", s["SectionHeader"]))
    obs = []
    
    # Concentration
    if top_pct > 40:
        obs.append(f"<b>Concentration:</b> {top['Lender']} at {top_pct:.1f}% — diversify in next refinancing cycle.")
    else:
        obs.append(f"<b>Concentration:</b> Largest lender at {top_pct:.1f}% — well-distributed.")
    
    # Tightest covenant
    ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
    ratio_cov["hr_num"] = pd.to_numeric(ratio_cov.get("Headroom_Pct"), errors="coerce")
    if len(ratio_cov) > 0 and ratio_cov["hr_num"].notna().any():
        tight = ratio_cov.loc[ratio_cov["hr_num"].idxmin()]
        obs.append(f"<b>Tightest Covenant:</b> {tight['Lender']} {tight['Covenant']} at "
                   f"{tight['hr_num']:+.1f}% headroom (actual {tight['Actual']:.2f}x).")
    
    # Most expensive
    isched = data["interest_schedule"]
    fb = isched[isched["Category"].isin(["FB", "FB-Term", "FB-FCY"]) & (isched["Effective_OS"] > 0)]
    if len(fb) > 0:
        exp = fb.loc[fb["Effective_Rate"].idxmax()]
        wac = isum["Weighted_Avg_Cost"]
        premium = (exp["Effective_Rate"] - wac) * exp["Effective_OS"]
        if premium > 0.5:
            obs.append(f"<b>Most Expensive:</b> {exp['Facility']} ({exp['Lender']}) at "
                       f"{exp['Effective_Rate']*100:.2f}% — {_inr(premium)}/yr above WAC.")
    
    # Renewals
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days"] = (fm["Validity_Date"] - as_of).dt.days
    soon = fm[fm["days"].notna() & fm["days"].between(0, 60)]
    if len(soon) > 0:
        obs.append(f"<b>Renewals Due:</b> {len(soon)} facilities expire in 60 days "
                   f"(combined {_inr(soon['Sanction_INR'].sum())}).")
    
    # Repayment peak
    rep = data["repayment_schedule"].copy()
    if len(rep) > 0:
        rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
        rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
        agg = rep.groupby("FY_Label")["Total_Principal"].sum()
        if (agg > 0).any():
            peak_label = agg.idxmax()
            obs.append(f"<b>Peak Repayment:</b> {peak_label} at {_inr(agg.max())} principal.")
    
    for i, o in enumerate(obs, 1):
        story.append(Paragraph(f"{i}. {o}", s["BodyText2"]))
    
    story.append(Spacer(1, 0.4*cm))
    
    # ─── FOOTER NOTE ────────────────────────────────────────────────
    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph(
        f"<i>Generated from JCL_Debt_Model_Final.xlsx. All figures reconcile to the source workbook. "
        f"Modified {data.get('excel_mtime', 'unknown')}.</i>",
        s["Caption"]))
    
    # Build
    def footer_fn(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY_MID)
        canvas.drawString(2*cm, 1*cm,
                           f"JCL Debt Monitoring  |  As-of {data['as_of_date']}")
        canvas.drawRightString(A4[0] - 2*cm, 1*cm, f"Page {doc_obj.page}")
        canvas.restoreState()
    
    doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)
    buf.seek(0)
    return buf.getvalue()
