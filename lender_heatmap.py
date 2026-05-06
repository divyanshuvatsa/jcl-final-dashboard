"""Lender heatmap with totals, percentages, and complete data display."""

from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from typing import Dict, Any
from theme import CHART_LAYOUT, LENDER_COLORS


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


def _build_pivot(data: Dict[str, Any]) -> pd.DataFrame:
    fm = data["facility_master"].copy()
    fm_active = fm[~fm["Sub_Limit_Flag"]].copy()
    fm_active["Cat_Label"] = fm_active["Category"].map(CATEGORY_LABELS).fillna(fm_active["Category"])
    
    pivot = fm_active.pivot_table(
        index="Lender", columns="Cat_Label",
        values="Effective_OS", aggfunc="sum", fill_value=0,
    )
    
    # Order columns logically
    cols_present = [c for c in CATEGORY_ORDER if c in pivot.columns]
    cols_extra = [c for c in pivot.columns if c not in cols_present]
    pivot = pivot[cols_present + cols_extra]
    
    # Order lenders by total
    pivot["__total__"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("__total__", ascending=False)
    pivot = pivot.drop(columns="__total__")
    
    return pivot


def render_lender_heatmap(data: Dict[str, Any]):
    """Render heatmap + supporting visualizations."""
    pivot = _build_pivot(data)
    
    if pivot.empty:
        st.warning("No data available for heatmap.")
        return
    
    # ─── Compute totals ─────────────────────────────────────────────
    row_totals = pivot.sum(axis=1)
    col_totals = pivot.sum(axis=0)
    grand_total = pivot.values.sum()
    
    # Top KPIs
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total Effective Outstanding", f"₹{grand_total:,.0f} Cr")
    with c2:
        biggest_lender = row_totals.idxmax()
        st.metric("Largest Lender", f"{biggest_lender}",
                  f"₹{row_totals.max():,.0f} Cr ({row_totals.max()/grand_total*100:.0f}%)")
    with c3:
        biggest_cat = col_totals.idxmax()
        st.metric("Largest Category", f"{biggest_cat}",
                  f"₹{col_totals.max():,.0f} Cr ({col_totals.max()/grand_total*100:.0f}%)")
    
    st.markdown("---")
    
    # ─── Toggle: ₹ Cr vs % ──────────────────────────────────────────
    view_mode = st.radio(
        "View as:", ["₹ Crores", "% of Total"],
        horizontal=True, key="heatmap_view_mode",
        label_visibility="collapsed",
    )
    
    if view_mode == "% of Total":
        z = (pivot.values / grand_total * 100)
        text = [[f"{v:.1f}%" if v >= 0.1 else "" for v in row] for row in z]
        hover_suffix = "%"
        cb_title = "% of Total"
    else:
        z = pivot.values
        text = [[f"₹{v:.0f}" if v >= 1 else "" for v in row] for row in z]
        hover_suffix = " Cr"
        cb_title = "₹ Cr"
    
    # ─── Build heatmap with marginal totals ─────────────────────────
    # We use subplots: heatmap (main) + bar charts (marginals)
    from plotly.subplots import make_subplots
    
    fig = make_subplots(
        rows=2, cols=2,
        column_widths=[0.85, 0.15],
        row_heights=[0.18, 0.82],
        horizontal_spacing=0.02,
        vertical_spacing=0.02,
        shared_xaxes=True,
        shared_yaxes=True,
    )
    
    # Top: column totals bar
    fig.add_trace(go.Bar(
        x=list(pivot.columns),
        y=col_totals.values,
        marker_color="#3B82F6",
        text=[f"₹{v:.0f}" for v in col_totals.values],
        textposition="outside",
        textfont=dict(size=10, color="#94A3B8"),
        showlegend=False,
        hovertemplate="<b>%{x}</b><br>₹%{y:,.0f} Cr total<extra></extra>",
    ), row=1, col=1)
    
    # Right: row totals bar
    fig.add_trace(go.Bar(
        x=row_totals.values,
        y=list(pivot.index),
        orientation="h",
        marker_color=[LENDER_COLORS.get(l, "#3B82F6") for l in pivot.index],
        text=[f"₹{v:.0f}" for v in row_totals.values],
        textposition="outside",
        textfont=dict(size=10, color="#F1F5F9"),
        showlegend=False,
        hovertemplate="<b>%{y}</b><br>₹%{x:,.0f} Cr total<extra></extra>",
    ), row=2, col=2)
    
    # Main heatmap
    fig.add_trace(go.Heatmap(
        z=z, x=list(pivot.columns), y=list(pivot.index),
        text=text, texttemplate="%{text}",
        textfont=dict(size=11, color="white"),
        colorscale=[
            [0, "#0F172A"],
            [0.001, "#1E3A8A"],
            [0.3, "#3B82F6"],
            [0.6, "#8B5CF6"],
            [1, "#EC4899"],
        ],
        showscale=True,
        colorbar=dict(
            title=dict(text=cb_title, font={"color": "#94A3B8"}),
            tickfont={"color": "#94A3B8"},
            x=1.12, len=0.78, y=0.41,
        ),
        hovertemplate=f"<b>%{{y}}</b><br>%{{x}}<br>%{{z:.1f}}{hover_suffix}<extra></extra>",
    ), row=2, col=1)
    
    fig.update_layout(
        height=560,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        margin=dict(l=20, r=20, t=20, b=80),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, row=1, col=1,
                     showticklabels=False)
    fig.update_yaxes(showgrid=False, zeroline=False, row=1, col=1,
                     showticklabels=False)
    fig.update_xaxes(showgrid=False, zeroline=False, row=2, col=2,
                     showticklabels=False)
    fig.update_yaxes(showgrid=False, zeroline=False, row=2, col=2,
                     showticklabels=False)
    fig.update_xaxes(tickangle=-30, tickfont=dict(size=10, color="#94A3B8"),
                     row=2, col=1)
    fig.update_yaxes(tickfont=dict(size=11, color="#F1F5F9"),
                     autorange="reversed", row=2, col=1)
    
    st.plotly_chart(fig, use_container_width=True)
    
    st.caption(
        "Top bars = total per category. Right bars = total per lender. "
        "Sub-limits excluded to avoid double-counting. "
        "Empty cells mean no exposure of that type with that lender."
    )
    
    # ─── Lender composition stacked bar ─────────────────────────────
    st.markdown("---")
    st.markdown("#### 📊 Lender Composition (% of each lender)")
    
    pct_pivot = pivot.div(row_totals, axis=0) * 100
    
    fig2 = go.Figure()
    cat_colors = {
        "Term Loan": "#3B82F6",
        "WC Fund-Based": "#8B5CF6",
        "FX Buyer's Credit": "#06B6D4",
        "FD-Backed FB": "#10B981",
        "NFB (LC/SBLC)": "#F59E0B",
        "NFB FD-Backed": "#84CC16",
        "Hedge": "#EC4899",
    }
    
    for cat in pct_pivot.columns:
        fig2.add_trace(go.Bar(
            name=cat,
            y=list(pct_pivot.index),
            x=pct_pivot[cat].values,
            orientation="h",
            marker_color=cat_colors.get(cat, "#94A3B8"),
            text=[f"{v:.0f}%" if v > 5 else "" for v in pct_pivot[cat].values],
            textposition="inside",
            textfont=dict(color="white", size=11),
            hovertemplate=f"<b>%{{y}}</b><br>{cat}: %{{x:.1f}}%<extra></extra>",
        ))
    
    fig2.update_layout(
        barmode="stack",
        height=320,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        xaxis=dict(title="% of Lender's Total", range=[0, 100],
                    gridcolor="#334155", color="#94A3B8"),
        yaxis=dict(autorange="reversed", color="#F1F5F9"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.15,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
        margin=dict(l=20, r=20, t=20, b=80),
    )
    st.plotly_chart(fig2, use_container_width=True)
