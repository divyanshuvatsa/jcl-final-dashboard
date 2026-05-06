"""Lender heatmap — exposure by lender × facility category."""

from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from typing import Dict, Any
from theme import CHART_LAYOUT


def render_lender_heatmap(data: Dict[str, Any]):
    """Heatmap: rows = lenders, cols = facility categories, values = ₹ Cr exposure."""
    fm = data["facility_master"].copy()
    
    # Pivot: lender × category, sum of effective outstanding (with sub-limits zeroed)
    fm_active = fm[~fm["Sub_Limit_Flag"]].copy()
    
    # Simplify category labels
    cat_map = {
        "FB": "WC Fund-Based",
        "FB-Term": "Term Loan",
        "FB-FCY": "FX Buyer's Credit",
        "FB-FDbacked": "FD-Backed FB",
        "NFB": "NFB (LC/SBLC)",
        "NFB-FDbacked": "NFB FD-Backed",
        "Hedge": "Hedge",
    }
    fm_active["Cat_Label"] = fm_active["Category"].map(cat_map).fillna(fm_active["Category"])
    
    pivot = fm_active.pivot_table(
        index="Lender", columns="Cat_Label",
        values="Effective_OS", aggfunc="sum", fill_value=0,
    )
    
    # Order lenders by total exposure
    pivot["_total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("_total", ascending=True).drop(columns="_total")
    
    # Order columns logically
    desired = ["Term Loan", "WC Fund-Based", "FX Buyer's Credit", "FD-Backed FB",
                "NFB (LC/SBLC)", "NFB FD-Backed", "Hedge"]
    cols_present = [c for c in desired if c in pivot.columns]
    cols_extra = [c for c in pivot.columns if c not in cols_present]
    pivot = pivot[cols_present + cols_extra]
    
    # Annotated heatmap
    z = pivot.values
    text = [[f"₹{v:.0f}" if v > 0 else "—" for v in row] for row in z]
    
    fig = go.Figure(data=go.Heatmap(
        z=z, x=list(pivot.columns), y=list(pivot.index),
        text=text, texttemplate="%{text}",
        textfont={"size": 12, "color": "white"},
        colorscale=[[0, "#1E293B"], [0.3, "#3B82F6"], [0.7, "#8B5CF6"], [1, "#EC4899"]],
        showscale=True,
        colorbar=dict(title=dict(text="₹ Cr", font={"color": "#94A3B8"}),
                      tickfont={"color": "#94A3B8"}),
        hovertemplate="<b>%{y}</b><br>%{x}<br>₹%{z:,.1f} Cr<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT, height=380,
        xaxis=dict(title="", side="top", tickangle=-30,
                    tickfont=dict(size=11)),
        yaxis=dict(title="", autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.caption("Rows = lenders, columns = facility categories. Values are effective outstanding (₹ Cr). "
                "Sub-limits excluded to avoid double-counting.")
