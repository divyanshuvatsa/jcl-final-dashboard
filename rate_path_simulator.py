"""Rate path simulator — model RBI rate decisions over next 4-8 quarters."""

from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from typing import Dict, Any, List
from theme import CHART_LAYOUT
from scenario_engine import recompute_interest


PRESET_PATHS = {
    "Hold (no change for 24M)":    [0, 0, 0, 0, 0, 0, 0, 0],
    "Cuts (50bps over 12M)":       [0, -25, -25, 0, 0, 0, 0, 0],
    "Aggressive cuts (100bps)":    [-25, -25, -25, -25, 0, 0, 0, 0],
    "Mild hike (50bps over 12M)":  [0, 25, 0, 25, 0, 0, 0, 0],
    "Stagflation (100bps hike)":   [25, 25, 25, 25, 0, 0, 0, 0],
    "Volatile (cut then hike)":    [-25, -25, 0, 0, 25, 25, 25, 25],
}


def render_rate_path_simulator(data: Dict[str, Any]):
    """8-quarter rate path simulator with cumulative interest impact."""
    st.markdown(
        "Model how RBI rate decisions over the next 8 quarters affect annual interest cost. "
        "Each quarter's change applies to all floating-rate facilities cumulatively.")
    
    c1, c2 = st.columns([2, 3])
    
    with c1:
        st.markdown("##### Pick a Path")
        path_name = st.selectbox("Preset", list(PRESET_PATHS.keys()), key="rate_path_preset")
        path = PRESET_PATHS[path_name].copy()
        
        st.markdown("##### Customize (bps per quarter)")
        custom_path = []
        for i in range(8):
            q = st.number_input(f"Q{i+1}", min_value=-100, max_value=100,
                                  value=path[i], step=25, key=f"rate_path_q{i}")
            custom_path.append(q)
        path = custom_path
    
    with c2:
        # Compute cumulative path
        cumulative = []
        running = 0
        for v in path:
            running += v
            cumulative.append(running)
        
        # Compute annual interest at each cumulative shock
        base = recompute_interest(data["facility_master"], data["benchmark_rates"], 0, 0)
        b1_base = base["Bucket1_Interest"]
        
        annual_interest_path = []
        for shock_bps in cumulative:
            stress = recompute_interest(data["facility_master"], data["benchmark_rates"],
                                          shock_bps, 0)
            annual_interest_path.append(stress["Bucket1_Interest"])
        
        # Quarter labels (next 8 from as-of date)
        as_of = pd.Timestamp(data["as_of_date"])
        labels = []
        for i in range(1, 9):
            month = as_of.month + 3 * i
            year = as_of.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            fy = year if month >= 4 else year - 1
            q_in_fy = ((month - 1 - 3) % 12) // 3 + 1
            labels.append(f"Q{q_in_fy} FY{str(fy + 1)[-2:]}")
        
        # Build dual-axis chart
        fig = go.Figure()
        # Bars = quarterly rate change
        fig.add_trace(go.Bar(
            x=labels, y=path, name="Quarterly Δ (bps)",
            marker_color=["#10B981" if v <= 0 else "#EF4444" for v in path],
            text=[f"{v:+d}" for v in path], textposition="outside",
            yaxis="y", hovertemplate="<b>%{x}</b><br>%{y:+d} bps<extra></extra>",
        ))
        # Line = annual interest
        fig.add_trace(go.Scatter(
            x=labels, y=annual_interest_path, name="Annual B1 Interest (₹ Cr)",
            line=dict(color="#F59E0B", width=3), mode="lines+markers",
            marker=dict(size=10, color="#F59E0B", line=dict(color="white", width=2)),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Annual Interest: ₹%{y:.2f} Cr<extra></extra>",
        ))
        fig.update_layout(
            **CHART_LAYOUT, height=420,
            xaxis=dict(title="Quarter"),
            yaxis=dict(title="Quarterly Rate Change (bps)",
                       gridcolor="#334155", side="left"),
            yaxis2=dict(title="Annual Interest (₹ Cr)", overlaying="y",
                        side="right", showgrid=False),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.18),
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Summary
    end_state = cumulative[-1]
    delta_int = annual_interest_path[-1] - b1_base
    st.markdown(f"""
**Summary:** Starting rate environment moves {end_state:+d} bps over 24 months.  
Annual interest cost moves from **₹{b1_base:.2f} Cr → ₹{annual_interest_path[-1]:.2f} Cr** — 
a **{delta_int:+.2f} Cr** annual change ({delta_int/b1_base*100:+.1f}%).
""")
