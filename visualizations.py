"""
Visual modules — replace text-heavy sections with insightful charts.

Provides:
- Covenant headroom bar chart (sorted from tightest to most slack)
- Facility cost premium chart (each facility's cost vs WAC)
- Lender × bucket stacked bars
- Repayment cumulative timeline
- Renewal Gantt-style timeline
"""

from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from typing import Dict, Any
from theme import LENDER_COLORS, STATUS_COLORS


# ════════════════════════════════════════════════════════════════════
# COVENANT HEADROOM BAR CHART
# ════════════════════════════════════════════════════════════════════
def render_covenant_headroom_chart(cov_df: pd.DataFrame, *, mode: str = "tightest"):
    """Covenant compliance buffer chart.

    mode = "tightest"  →  Show ONE bar per unique covenant TYPE, using the tightest
                          (smallest headroom %) instance across lenders. This eliminates
                          structural duplication (e.g. TOL/TNW appearing 5× across lenders).
    mode = "all"       →  Show all bars (original behavior). Useful for full audit detail.
    """
    df = cov_df.copy()
    df = df[df["Operator"] != "rating"].copy()
    df["headroom"] = pd.to_numeric(df.get("Headroom_Pct"), errors="coerce")
    df = df[df["headroom"].notna()].copy()

    if df.empty:
        st.info("No numeric covenants to plot.")
        return

    if mode == "tightest":
        # For each unique covenant type, keep the row with the tightest (smallest) headroom.
        df = df.sort_values("headroom").groupby("Covenant", sort=False).head(1)
        df["label"] = df["Covenant"] + "  ·  " + df["Lender"]
        n_total = (cov_df["Operator"] != "rating").sum()
        subtitle = (f"<i>Showing tightest of each ratio type "
                    f"({len(df)} unique types from {n_total} covenants).</i>")
    else:
        df["label"] = df["Lender"] + " — " + df["Covenant"]
        subtitle = "<i>All covenants — duplicate ratios shown per lender.</i>"

    df = df.sort_values("headroom", ascending=True)  # tightest at TOP

    CAP = 150
    df["display_value"] = df["headroom"].clip(upper=CAP)
    df["actual_text"] = df["headroom"].apply(
        lambda v: f">{CAP}% (actual {v:.0f}%)" if v > CAP else f"{v:+.0f}%"
    )

    color_map = {
        "Compliant": "#10B981", "Watch": "#3B82F6",
        "Near Breach": "#F59E0B", "Breach": "#EF4444",
    }
    colors = [color_map.get(s, "#64748B") for s in df["Status"]]

    fig = go.Figure()
    # Background zones
    fig.add_vrect(x0=-100, x1=0,    fillcolor="rgba(239,68,68,0.08)",  line_width=0, layer="below")
    fig.add_vrect(x0=0,    x1=20,   fillcolor="rgba(245,158,11,0.06)", line_width=0, layer="below")
    fig.add_vrect(x0=20,   x1=CAP+10, fillcolor="rgba(16,185,129,0.04)", line_width=0, layer="below")

    fig.add_trace(go.Bar(
        x=df["display_value"], y=df["label"], orientation="h",
        marker=dict(color=colors, line=dict(color="#0F172A", width=0.5)),
        text=df["actual_text"], textposition="outside",
        textfont=dict(size=11, color="#F1F5F9"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Actual: %{customdata[0]:.2f}x<br>"
            "Threshold: %{customdata[1]} %{customdata[2]:.2f}x<br>"
            "Headroom: %{customdata[3]:+.1f}%<br>"
            "Status: %{customdata[4]}<extra></extra>"
        ),
        customdata=df[["Actual", "Operator", "Threshold", "headroom", "Status"]].values,
    ))
    fig.add_vline(x=0,  line=dict(color="#EF4444", width=2))
    fig.add_vline(x=20, line=dict(color="#F59E0B", width=1, dash="dot"))

    fig.update_layout(
        height=max(400, 38 * len(df)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(
            title="Headroom % (positive = compliant, negative = breach)",
            gridcolor="#334155", color="#94A3B8",
            range=[-10, CAP + 25],
        ),
        yaxis=dict(color="#F1F5F9"),
        margin=dict(l=20, r=120, t=50, b=40),
        showlegend=False,
        annotations=[
            dict(x=-5, y=1.04, xref="x", yref="paper",
                 text="<span style='color:#EF4444'>◀ Breach</span>",
                 showarrow=False, font=dict(size=11)),
            dict(x=10, y=1.04, xref="x", yref="paper",
                 text="<span style='color:#F59E0B'>Watch</span>",
                 showarrow=False, font=dict(size=11)),
            dict(x=80, y=1.04, xref="x", yref="paper",
                 text="<span style='color:#10B981'>Compliant ▶</span>",
                 showarrow=False, font=dict(size=11)),
        ],
    )
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        f"<div style='font-size:0.82rem;color:#94A3B8;margin-top:4px;text-align:center;'>{subtitle}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='display:flex;gap:20px;justify-content:center;font-size:0.82rem;"
        "color:#94A3B8;margin-top:6px;'>"
        "<span>🟢 Compliant (>20% buffer)</span>"
        "<span>🔵 Watch (10-20%)</span>"
        "<span>🟡 Near Breach (<10%)</span>"
        "<span>🔴 Breach</span>"
        "</div>",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════
# FACILITY COST PREMIUM CHART — split into ₹ contribution + FB rate
# ════════════════════════════════════════════════════════════════════
def render_facility_cost_chart(data: Dict[str, Any]):
    """Annual ₹ COST CONTRIBUTION by facility — answers 'where does the ₹49 Cr come from?'.

    Replaces the previous 'rate vs WAC' chart which mixed NFB commission rates
    (0.50%) with FB interest rates (8.75%) — visually misleading because
    commission and interest are two different cost mechanics.
    """
    fm = data["facility_master"].copy()
    isum = data["interest_summary"]

    # Use Effective_OS for FB facilities (interest on drawn) and Sanction_INR for NFB (commission on face)
    # Mark each facility with its "annual cost" and "cost type" for clarity.
    rows = []
    for _, r in fm[~fm["Sub_Limit_Flag"]].iterrows():
        rate = r.get("Effective_Rate") or 0
        if not isinstance(rate, (int, float)) or rate <= 0:
            continue
        cat = r.get("Category", "")
        if cat == "NFB":
            # Commission on sanctioned face
            base = r.get("Sanction_INR", 0)
            cost_type = "Commission (NFB)"
        elif cat == "Hedge":
            continue  # exclude hedge memo items
        else:
            # Interest on drawn outstanding
            base = r.get("Effective_OS", 0)
            cost_type = "Interest (FB)"
        if base <= 0:
            continue
        cost = base * rate
        rows.append({
            "Lender": r["Lender"],
            "Facility": r["Facility"],
            "Label": f"{r['Lender']} — {r['Facility']}",
            "Rate_Pct": rate * 100,
            "Base": base,
            "Annual_Cost": cost,
            "Cost_Type": cost_type,
        })
    if not rows:
        st.info("No interest- or commission-bearing facilities to plot.")
        return

    df = pd.DataFrame(rows).sort_values("Annual_Cost", ascending=True)
    df["color"] = df["Cost_Type"].map({
        "Interest (FB)": "#3B82F6",
        "Commission (NFB)": "#F59E0B",
    })

    total_cost = df["Annual_Cost"].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Annual_Cost"],
        y=df["Label"],
        orientation="h",
        marker_color=df["color"].tolist(),
        text=[f"₹{c:.2f} Cr" for c in df["Annual_Cost"]],
        textposition="outside",
        textfont=dict(size=11, color="#F1F5F9"),
        customdata=df[["Rate_Pct", "Base", "Cost_Type"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Annual Cost: ₹%{x:.2f} Cr<br>"
            "Type: %{customdata[2]}<br>"
            "Rate: %{customdata[0]:.2f}%<br>"
            "Base: ₹%{customdata[1]:.1f} Cr<extra></extra>"
        ),
    ))

    fig.update_layout(
        height=max(380, 40 * len(df)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title=f"Annual Cost Contribution (₹ Cr)  ·  total ties to ₹{total_cost:.2f} Cr",
                   gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(color="#F1F5F9", autorange="reversed"),
        margin=dict(l=20, r=80, t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Legend / caption
    st.markdown(
        "<div style='display:flex;gap:24px;justify-content:center;font-size:0.85rem;"
        "color:#94A3B8;margin-top:6px;'>"
        "<span><span style='color:#3B82F6'>■</span> Interest on drawn FB principal</span>"
        "<span><span style='color:#F59E0B'>■</span> Commission on NFB sanctioned face</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_fb_rate_vs_wac_chart(data: Dict[str, Any]):
    """FB-only Effective Rate vs WAC — apples-to-apples interest-rate comparison.

    Excludes NFB commission rates (which are a fundamentally different cost mechanic).
    Bars further right cost more per rupee of borrowed principal.
    """
    fm = data["facility_master"].copy()
    fm = fm[(fm["Effective_OS"] > 0) & ~fm["Sub_Limit_Flag"]]
    fm = fm[fm["Effective_Rate"].notna() & (fm["Effective_Rate"] > 0)]
    # FB only — drop NFB commission lines and hedge
    fm = fm[~fm["Category"].isin(["NFB", "NFB-FDbacked", "Hedge"])]

    if fm.empty:
        st.info("No FB interest-bearing facilities to plot.")
        return

    wac = data["interest_summary"]["Weighted_Avg_Cost"]
    fm = fm.sort_values("Effective_Rate", ascending=True)

    fm["label"] = fm["Lender"] + " — " + fm["Facility"]
    fm["rate_pct"] = fm["Effective_Rate"] * 100
    fm["color"] = [LENDER_COLORS.get(l, "#3B82F6") for l in fm["Lender"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=fm["rate_pct"],
        y=fm["label"],
        orientation="h",
        marker_color=fm["color"].tolist(),
        text=[f"{r:.2f}%" for r in fm["rate_pct"]],
        textposition="outside",
        textfont=dict(size=10, color="#F1F5F9"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Rate: %{x:.2f}%<br>"
            "Outstanding: ₹%{customdata[0]:.1f} Cr<br>"
            "Annual Interest: ₹%{customdata[1]:.2f} Cr<extra></extra>"
        ),
        customdata=fm[["Effective_OS"]].assign(
            interest=fm["Effective_OS"] * fm["Effective_Rate"]
        ).values,
    ))

    fig.add_vline(
        x=wac * 100,
        line=dict(color="#F59E0B", width=2, dash="dash"),
        annotation=dict(text=f"Portfolio WAC: {wac*100:.2f}%",
                        font=dict(color="#F59E0B")),
    )

    fig.update_layout(
        height=max(280, 40 * len(fm)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Effective Interest Rate (%)  ·  fund-based facilities only",
                   gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(color="#F1F5F9", autorange="reversed"),
        margin=dict(l=20, r=20, t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


CATEGORY_LABELS = {
    "FB": "WC Fund-Based",
    "FB-Term": "Term Loan",
    "FB-FCY": "FX Buyer's Credit",
    "FB-FDbacked": "FD-Backed FB",
    "NFB": "NFB (LC/SBLC)",
    "NFB-FDbacked": "NFB FD-Backed",
    "Hedge": "Hedge",
}
CATEGORY_ORDER = ["Term Loan", "WC Fund-Based", "FX Buyer's Credit",
                   "FD-Backed FB", "NFB (LC/SBLC)", "NFB FD-Backed", "Hedge"]


def _build_lender_category_pivot(data: Dict[str, Any]) -> pd.DataFrame:
    """Build pivot of SANCTIONED amounts by lender × category.

    Uses Sanction_INR (stable, auditable) instead of Effective_OS (drawn, fluctuates).
    Filtered to Bucket 1 + Bucket 2 only — so the chart sums exactly to ₹1,320.7 Cr
    (matches the headline Sanctioned Debt KPI).  Bucket 0 sub-limits and Bucket 3
    FD-backed lines are excluded by design.
    """
    fm = data["facility_master"].copy()
    # Bucket 1 + Bucket 2 only — these are what comprise Sanctioned Debt
    fm_main = fm[fm["Bucket"].isin([1, 2])].copy()
    fm_main["Cat_Label"] = fm_main["Category"].map(CATEGORY_LABELS).fillna(fm_main["Category"])

    pivot = fm_main.pivot_table(
        index="Lender", columns="Cat_Label",
        values="Sanction_INR", aggfunc="sum", fill_value=0,
    )

    cols_present = [c for c in CATEGORY_ORDER if c in pivot.columns]
    cols_extra = [c for c in pivot.columns if c not in cols_present]
    pivot = pivot[cols_present + cols_extra]

    pivot["__total__"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("__total__", ascending=False)
    pivot = pivot.drop(columns="__total__")

    return pivot


# ════════════════════════════════════════════════════════════════════
# LENDER × CATEGORY STACKED BAR
# ════════════════════════════════════════════════════════════════════
def render_lender_composition_stacked(data: Dict[str, Any]):
    """Each lender's SANCTIONED capacity split by facility category."""
    pivot = _build_lender_category_pivot(data)

    if pivot.empty:
        return

    cat_colors = {
        "Term Loan": "#3B82F6",
        "WC Fund-Based": "#8B5CF6",
        "FX Buyer's Credit": "#06B6D4",
        "NFB (LC/SBLC)": "#F59E0B",
    }

    fig = go.Figure()
    for cat in pivot.columns:
        fig.add_trace(go.Bar(
            name=cat,
            y=list(pivot.index),
            x=pivot[cat].values,
            orientation="h",
            marker_color=cat_colors.get(cat, "#94A3B8"),
            text=[f"₹{v:.0f}" if v >= 5 else "" for v in pivot[cat].values],
            textposition="inside",
            textfont=dict(color="white", size=10),
            hovertemplate=f"<b>%{{y}}</b><br>{cat}: ₹%{{x:,.1f}} Cr (sanctioned)<extra></extra>",
        ))

    # Add total annotation per row
    totals = pivot.sum(axis=1)
    for lender, total in totals.items():
        fig.add_annotation(
            x=total + 8, y=lender, text=f"<b>₹{total:.1f}</b>",
            showarrow=False, font=dict(color="#F1F5F9", size=11),
            xanchor="left",
        )

    fig.update_layout(
        barmode="stack",
        height=320,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Sanctioned Capacity (₹ Cr)  ·  total ties to ₹1,320.7 Cr",
                    gridcolor="#334155", color="#94A3B8",
                    range=[0, totals.max() * 1.18]),
        yaxis=dict(autorange="reversed", color="#F1F5F9"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.18,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
        margin=dict(l=20, r=20, t=20, b=80),
    )
    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════
# REPAYMENT CUMULATIVE TIMELINE
# ════════════════════════════════════════════════════════════════════
def render_repayment_timeline(data: Dict[str, Any]):
    """Term loan outstanding running down over time — area chart.

    BUG FIX: previously double-subtracted past-FY repayments because the chart
    used current Effective_OS (which is already net of FY-to-date payments) but
    then subtracted ALL FY repayments starting from FY24. Now correctly skips
    past FYs and projects forward only from the as-of date.
    """
    fm = data["facility_master"].copy()
    tl = fm[fm["Category"] == "FB-Term"].copy()
    rep = data["repayment_schedule"].copy()
    if rep.empty or tl.empty:
        st.info("No term loan schedule to plot.")
        return

    as_of = pd.Timestamp(data["as_of_date"])
    # Determine the as-of fiscal year (Indian: Apr-Mar)
    as_of_fy = as_of.year + (1 if as_of.month >= 4 else 0)

    rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
    rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]

    lender_cols = {
        "RBL Bank": "RBL_Principal",
        "YES Bank": "YBL_Principal",
        "Bajaj Finance": "Bajaj_Principal",
    }

    # Aggregate current outstanding per lender (sum across rows; ignore lenders with 0)
    current_os = tl.groupby("Lender")["Effective_OS"].sum().to_dict()
    current_os = {l: v for l, v in current_os.items() if v > 0}

    # Future FYs only — payments in FYs ≤ as_of_fy are already reflected in Effective_OS
    future_fy_labels = [f"FY{str(fy)[-2:]}"
                        for fy in range(as_of_fy + 1, rep["FY"].max() + 1)]

    fig = go.Figure()

    for lender, col in lender_cols.items():
        if col not in rep.columns:
            continue
        outstanding = current_os.get(lender, 0)
        if outstanding <= 0:
            continue

        # Build trajectory: start at current, then subtract each future FY's payments
        timeline = [outstanding]
        for fy in future_fy_labels:
            fy_payment = rep[rep["FY_Label"] == fy][col].sum()
            outstanding = max(0, outstanding - fy_payment)
            timeline.append(outstanding)

        x_axis = ["As-of"] + [f"End of {fy}" for fy in future_fy_labels]

        fig.add_trace(go.Scatter(
            x=x_axis, y=timeline,
            mode="lines+markers",
            name=lender,
            line=dict(color=LENDER_COLORS.get(lender, "#3B82F6"), width=3),
            marker=dict(size=8),
            stackgroup="one",
            hovertemplate=f"<b>{lender}</b><br>%{{x}}: ₹%{{y:.1f}} Cr<extra></extra>",
        ))

    fig.update_layout(
        height=380,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="", gridcolor="#334155", color="#94A3B8",
                   tickangle=-30),
        yaxis=dict(title="Term Loan Outstanding (₹ Cr)",
                    gridcolor="#334155", color="#94A3B8"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
        margin=dict(l=20, r=20, t=20, b=80),
    )
    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════
# RENEWAL TIMELINE GANTT
# ════════════════════════════════════════════════════════════════════
def render_renewal_timeline(data: Dict[str, Any]):
    """Each facility's expiration on a timeline."""
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days"] = (fm["Validity_Date"] - as_of).dt.days
    fm = fm[fm["days"].notna() & (fm["days"] >= 0) & (fm["days"] <= 365)].copy()
    
    if fm.empty:
        st.info("No facilities expiring in the next 12 months.")
        return
    
    fm["label"] = fm["Lender"] + " — " + fm["Facility"]
    fm = fm.sort_values("days")
    
    # Color by urgency
    def _color(d):
        if d <= 30: return "#EF4444"
        if d <= 60: return "#F59E0B"
        if d <= 90: return "#3B82F6"
        if d <= 180: return "#8B5CF6"
        return "#64748B"
    
    fm["color"] = fm["days"].apply(_color)
    fm["expiry_str"] = fm["Validity_Date"].dt.strftime("%d-%b-%Y")
    
    fig = go.Figure()
    
    # Background shaded zones for urgency bands (subtle, behind bars)
    fig.add_vrect(x0=0, x1=30, fillcolor="rgba(239,68,68,0.10)", line_width=0, layer="below")
    fig.add_vrect(x0=30, x1=60, fillcolor="rgba(245,158,11,0.08)", line_width=0, layer="below")
    fig.add_vrect(x0=60, x1=90, fillcolor="rgba(59,130,246,0.06)", line_width=0, layer="below")
    fig.add_vrect(x0=90, x1=180, fillcolor="rgba(139,92,246,0.05)", line_width=0, layer="below")
    fig.add_vrect(x0=180, x1=400, fillcolor="rgba(100,116,139,0.04)", line_width=0, layer="below")
    
    fig.add_trace(go.Bar(
        x=fm["days"],
        y=fm["label"],
        orientation="h",
        marker=dict(color=fm["color"].tolist(), line=dict(color="#0F172A", width=0.5)),
        text=[f"{d}d · {date}" for d, date in zip(fm["days"], fm["expiry_str"])],
        textposition="outside",
        textfont=dict(size=10, color="#F1F5F9"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Expires: %{customdata[0]}<br>"
            "Days to expiry: %{x}<br>"
            "Sanction: ₹%{customdata[1]:.1f} Cr<extra></extra>"
        ),
        customdata=fm[["expiry_str", "Sanction_INR"]].values,
        showlegend=False,
    ))
    
    # Reference lines (no inline text — use external legend below)
    for d, color in [(30, "#EF4444"), (60, "#F59E0B"),
                      (90, "#3B82F6"), (180, "#8B5CF6")]:
        fig.add_vline(x=d, line=dict(color=color, width=1, dash="dot"))
    
    # Annotation labels positioned BELOW the chart (no overlap)
    fig.update_layout(
        height=max(450, 26 * len(fm)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(
            title="Days to Expiry (from as-of date)",
            gridcolor="#334155", color="#94A3B8",
            range=[0, max(200, fm["days"].max() + 60)],
        ),
        yaxis=dict(autorange="reversed", color="#F1F5F9"),
        margin=dict(l=20, r=180, t=20, b=60),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Color legend below chart (no overlap with bars)
    st.markdown(
        "<div style='display:flex;gap:18px;justify-content:center;font-size:0.82rem;"
        "color:#94A3B8;margin-top:4px;flex-wrap:wrap;'>"
        "<span>🔴 ≤30 days (urgent)</span>"
        "<span>🟠 31-60 days (high)</span>"
        "<span>🔵 61-90 days (medium)</span>"
        "<span>🟣 91-180 days (low)</span>"
        "<span>⚫ >180 days (monitor)</span>"
        "</div>",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════
# SCENARIO IMPACT COMPARISON
# ════════════════════════════════════════════════════════════════════
def render_scenario_comparison_chart(base_metrics: Dict, stress_metrics: Dict):
    """Side-by-side base vs stress comparison for key metrics."""
    metrics = []
    
    if "DSCR" in base_metrics and "DSCR" in stress_metrics:
        metrics.append(("DSCR", base_metrics["DSCR"], stress_metrics["DSCR"], 1.5, ">="))
    if "Total_Debt_EBITDA" in base_metrics:
        metrics.append(("Total Debt/EBITDA", base_metrics["Total_Debt_EBITDA"],
                        stress_metrics.get("Total_Debt_EBITDA", 0), 4.0, "<="))
    if "ICR" in base_metrics:
        metrics.append(("ICR", base_metrics["ICR"], stress_metrics.get("ICR", 0), 3.0, ">="))
    if "TOL_TNW" in base_metrics:
        metrics.append(("TOL/TNW", base_metrics["TOL_TNW"],
                        stress_metrics.get("TOL_TNW", 0), 2.5, "<="))
    
    if not metrics:
        return
    
    labels = [m[0] for m in metrics]
    base_vals = [m[1] for m in metrics]
    stress_vals = [m[2] for m in metrics]
    thresholds = [m[3] for m in metrics]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Base (FY26E)", x=labels, y=base_vals,
        marker_color="#3B82F6",
        text=[f"{v:.2f}" for v in base_vals],
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name="Stress", x=labels, y=stress_vals,
        marker_color="#F59E0B",
        text=[f"{v:.2f}" for v in stress_vals],
        textposition="outside",
    ))
    fig.add_trace(go.Scatter(
        name="Threshold", x=labels, y=thresholds,
        mode="markers", marker=dict(symbol="line-ew", size=20, color="#EF4444",
                                     line=dict(width=3)),
    ))
    
    fig.update_layout(
        barmode="group",
        height=400,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(gridcolor="#334155", color="#94A3B8"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.15,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
        margin=dict(l=20, r=20, t=20, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)
