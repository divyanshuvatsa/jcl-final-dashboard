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
def render_covenant_headroom_chart(cov_df: pd.DataFrame):
    """All 24 covenants sorted by headroom — instantly shows the tightest."""
    df = cov_df.copy()
    df = df[df["Operator"] != "rating"].copy()
    df["headroom"] = pd.to_numeric(df.get("Headroom_Pct"), errors="coerce")
    df = df[df["headroom"].notna()].copy()
    
    if df.empty:
        st.info("No numeric covenants to plot.")
        return
    
    df["label"] = df["Lender"] + " — " + df["Covenant"]
    df = df.sort_values("headroom", ascending=False)  # tightest at bottom
    
    # Color by status
    color_map = {
        "Compliant": "#10B981",
        "Watch": "#3B82F6",
        "Near Breach": "#F59E0B",
        "Breach": "#EF4444",
    }
    colors = [color_map.get(s, "#64748B") for s in df["Status"]]
    
    fig = go.Figure(go.Bar(
        x=df["headroom"],
        y=df["label"],
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.0f}%" for v in df["headroom"]],
        textposition="outside",
        textfont=dict(size=10, color="#F1F5F9"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Actual: %{customdata[0]:.2f}x<br>"
            "Threshold: %{customdata[1]} %{customdata[2]:.2f}x<br>"
            "Headroom: %{x:+.1f}%<extra></extra>"
        ),
        customdata=df[["Actual", "Operator", "Threshold"]].values,
    ))
    
    fig.add_vline(x=0, line=dict(color="#EF4444", width=2, dash="dash"),
                   annotation=dict(text="Breach line", font=dict(color="#EF4444")))
    fig.add_vline(x=20, line=dict(color="#F59E0B", width=1, dash="dot"),
                   annotation=dict(text="Watch threshold (20% headroom)",
                                   font=dict(color="#F59E0B"),
                                   xanchor="left"))
    
    fig.update_layout(
        height=max(420, 22 * len(df)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Headroom % (positive = compliant, negative = breach)",
                   gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(color="#F1F5F9", autorange="reversed"),
        margin=dict(l=20, r=80, t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════
# FACILITY COST PREMIUM CHART
# ════════════════════════════════════════════════════════════════════
def render_facility_cost_chart(data: Dict[str, Any]):
    """Each facility's effective rate vs portfolio WAC."""
    fm = data["facility_master"].copy()
    fm = fm[(fm["Effective_OS"] > 0) & ~fm["Sub_Limit_Flag"]]
    fm = fm[fm["Effective_Rate"].notna() & (fm["Effective_Rate"] > 0)]
    
    if fm.empty:
        st.info("No interest-bearing facilities to plot.")
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
        height=max(380, 25 * len(fm)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Effective Rate (%)",
                   gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(color="#F1F5F9", autorange="reversed"),
        margin=dict(l=20, r=20, t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════
# LENDER × CATEGORY STACKED BAR
# ════════════════════════════════════════════════════════════════════
def render_lender_composition_stacked(data: Dict[str, Any]):
    """Each lender's exposure split by category — stacked bar."""
    from lender_heatmap import _build_pivot, CATEGORY_LABELS
    pivot = _build_pivot(data)
    
    if pivot.empty:
        return
    
    cat_colors = {
        "Term Loan": "#3B82F6",
        "WC Fund-Based": "#8B5CF6",
        "FX Buyer's Credit": "#06B6D4",
        "FD-Backed FB": "#10B981",
        "NFB (LC/SBLC)": "#F59E0B",
        "NFB FD-Backed": "#84CC16",
        "Hedge": "#EC4899",
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
            hovertemplate=f"<b>%{{y}}</b><br>{cat}: ₹%{{x:,.1f}} Cr<extra></extra>",
        ))
    
    fig.update_layout(
        barmode="stack",
        height=320,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Effective Outstanding (₹ Cr)",
                    gridcolor="#334155", color="#94A3B8"),
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
    """Term loan outstanding running down over time — area chart."""
    fm = data["facility_master"].copy()
    tl = fm[fm["Category"] == "FB-Term"].copy()
    
    rep = data["repayment_schedule"].copy()
    if rep.empty or tl.empty:
        st.info("No term loan schedule to plot.")
        return
    
    # Compute outstanding by lender at each period
    rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
    rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
    
    # Get current outstanding
    current_os = tl.set_index("Lender")["Outstanding"].to_dict()
    
    # Compute cumulative repayment per lender per FY
    by_lender_fy = rep.groupby(["Lender", "FY_Label"])["Total_Principal"].sum().unstack(fill_value=0)
    
    # Build outstanding timeline
    fy_labels = sorted(by_lender_fy.columns,
                        key=lambda x: int(x.replace("FY", "")))
    
    fig = go.Figure()
    
    for lender in by_lender_fy.index:
        outstanding = current_os.get(lender, 0)
        timeline = [outstanding]
        for fy in fy_labels:
            outstanding -= by_lender_fy.loc[lender, fy]
            outstanding = max(0, outstanding)
            timeline.append(outstanding)
        
        # X axis = current + each FY
        x = ["Current"] + fy_labels
        
        fig.add_trace(go.Scatter(
            x=x, y=timeline,
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
        xaxis=dict(title="", gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(title="Term Loan Outstanding (₹ Cr)",
                    gridcolor="#334155", color="#94A3B8"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.15,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
        margin=dict(l=20, r=20, t=20, b=60),
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
    
    fig = go.Figure(go.Bar(
        x=fm["days"],
        y=fm["label"],
        orientation="h",
        marker_color=fm["color"].tolist(),
        text=[f"{d}d ({date})" for d, date in zip(fm["days"], fm["expiry_str"])],
        textposition="outside",
        textfont=dict(size=10, color="#F1F5F9"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Expires: %{customdata[0]}<br>"
            "Days to expiry: %{x}<br>"
            "Sanction: ₹%{customdata[1]:.1f} Cr<extra></extra>"
        ),
        customdata=fm[["expiry_str", "Sanction_INR"]].values,
    ))
    
    # Reference lines
    for d, label, color in [
        (30, "30 days (urgent)", "#EF4444"),
        (60, "60 days", "#F59E0B"),
        (90, "90 days", "#3B82F6"),
        (180, "180 days", "#8B5CF6"),
    ]:
        fig.add_vline(x=d, line=dict(color=color, width=1, dash="dot"),
                       annotation=dict(text=label, font=dict(color=color, size=9),
                                       yref="paper", y=1, yanchor="top"))
    
    fig.update_layout(
        height=max(400, 25 * len(fm)),
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="Days to Expiry (from as-of date)",
                    gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(autorange="reversed", color="#F1F5F9"),
        margin=dict(l=20, r=120, t=40, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


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
