"""Rate path simulator with base reference, savings/cost callouts, and richer viz."""

from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from typing import Dict, Any
from theme import CHART_LAYOUT
from scenario_engine import recompute_interest


PRESET_PATHS = {
    "Hold (no change for 24M)":         [0, 0, 0, 0, 0, 0, 0, 0],
    "Cuts (50bps over 12M)":            [0, -25, -25, 0, 0, 0, 0, 0],
    "Aggressive cuts (100bps over 12M)":[-25, -25, -25, -25, 0, 0, 0, 0],
    "Mild hike (50bps over 12M)":       [0, 25, 0, 25, 0, 0, 0, 0],
    "Stagflation (100bps hike)":        [25, 25, 25, 25, 0, 0, 0, 0],
    "Volatile (cut then hike)":         [-25, -25, 0, 0, 25, 25, 25, 25],
}


def render_rate_path_simulator(data: Dict[str, Any]):
    """8-quarter rate path with base reference and impact callouts."""
    
    st.markdown(
        "Model how RBI rate decisions over the next 8 quarters affect annual interest cost.\n\n"
        "Each quarter's change applies cumulatively to all floating-rate facilities."
    )
    
    # Base reference
    base = recompute_interest(data["facility_master"], data["benchmark_rates"], 0, 0)
    b1_base = base["Bucket1_Interest"]
    
    # ─── Inputs ──────────────────────────────────────────────────────
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.markdown("##### 🎛️ Pick a Scenario")
        path_name = st.selectbox(
            "Preset", list(PRESET_PATHS.keys()),
            key="rate_path_preset", label_visibility="collapsed",
        )
        path = PRESET_PATHS[path_name].copy()
        
        st.markdown("##### Custom Path (bps per quarter)")
        # Use 4-column grid for inputs
        custom_path = []
        cc = st.columns(4)
        for i in range(8):
            with cc[i % 4]:
                v = st.number_input(
                    f"Q{i+1}", min_value=-100, max_value=100,
                    value=path[i], step=25, key=f"rate_path_q{i}",
                )
                custom_path.append(v)
        path = custom_path
    
    with c2:
        # ─── Compute paths ───────────────────────────────────────────
        cumulative = []
        running = 0
        for v in path:
            running += v
            cumulative.append(running)
        
        annual_int_path = []
        for shock in cumulative:
            s = recompute_interest(data["facility_master"], data["benchmark_rates"], shock, 0)
            annual_int_path.append(s["Bucket1_Interest"])
        
        # Quarter labels
        as_of = pd.Timestamp(data["as_of_date"])
        labels = []
        for i in range(1, 9):
            month = as_of.month + 3 * i
            year = as_of.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            fy = year if month >= 4 else year - 1
            q_in_fy = ((month - 1 - 3) % 12) // 3 + 1
            labels.append(f"Q{q_in_fy} FY{str(fy + 1)[-2:]}")
        
        # KPIs
        end_state = cumulative[-1]
        end_int = annual_int_path[-1]
        delta_int = end_int - b1_base
        cum_savings_2y = sum((b1_base - x) for x in annual_int_path) / 4  # 4 quarters per year
        
        st.markdown("##### 📊 Impact")
        m1, m2 = st.columns(2)
        with m1:
            st.metric(
                "Cumulative Rate Move",
                f"{end_state:+d} bps",
                "after 8 quarters",
            )
        with m2:
            sign = "✅ Savings" if delta_int < 0 else "⚠️ Cost increase" if delta_int > 0 else "No change"
            st.metric(
                f"Annual Interest at end",
                f"₹{end_int:.2f} Cr",
                f"{delta_int:+.2f} Cr vs base",
                delta_color="inverse" if delta_int < 0 else "normal",
            )
        
        st.markdown(f"<div style='padding:12px;background:#1E293B;border-radius:8px;"
                    f"border-left:4px solid {'#10B981' if cum_savings_2y > 0 else '#EF4444' if cum_savings_2y < 0 else '#3B82F6'};"
                    f"margin-top:12px;'>"
                    f"<div style='color:#94A3B8;font-size:0.78rem;'>2-YEAR CUMULATIVE IMPACT</div>"
                    f"<div style='color:#F1F5F9;font-size:1.5rem;font-weight:700;'>"
                    f"{'₹' if cum_savings_2y < 0 else '₹'}"
                    f"{abs(cum_savings_2y):,.2f} Cr {'extra cost' if cum_savings_2y < 0 else 'saved' if cum_savings_2y > 0 else 'unchanged'}</div>"
                    f"<div style='color:#94A3B8;font-size:0.75rem;margin-top:4px;'>"
                    f"vs holding rates flat at base</div></div>",
                    unsafe_allow_html=True)
    
    # ─── Chart: Combined view ────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Visualization")
    
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.35, 0.65],
        vertical_spacing=0.08,
        subplot_titles=("Quarterly Rate Change (bps)", "Annual Interest Cost (₹ Cr)"),
    )
    
    # Top: Quarterly rate change bars
    fig.add_trace(go.Bar(
        x=labels, y=path,
        marker_color=["#10B981" if v < 0 else "#EF4444" if v > 0 else "#64748B" for v in path],
        text=[f"{v:+d}" if v != 0 else "—" for v in path],
        textposition="outside",
        textfont=dict(size=11, color="#94A3B8"),
        showlegend=False,
        hovertemplate="<b>%{x}</b><br>Δ %{y:+d} bps<extra></extra>",
    ), row=1, col=1)
    fig.add_hline(y=0, line=dict(color="#94A3B8", width=1, dash="solid"), row=1, col=1)
    
    # Bottom: Annual interest with base reference
    fig.add_trace(go.Scatter(
        x=labels, y=[b1_base]*len(labels),
        mode="lines",
        line=dict(color="#94A3B8", width=2, dash="dash"),
        name=f"Base (₹{b1_base:.2f} Cr)",
        hovertemplate="<b>Base</b><br>₹%{y:.2f} Cr<extra></extra>",
    ), row=2, col=1)
    
    # Color the line based on savings/cost
    line_color = "#10B981" if annual_int_path[-1] < b1_base else "#EF4444" if annual_int_path[-1] > b1_base else "#3B82F6"
    
    fig.add_trace(go.Scatter(
        x=labels, y=annual_int_path,
        mode="lines+markers",
        line=dict(color=line_color, width=3),
        marker=dict(size=10, color=line_color, line=dict(color="white", width=2)),
        name="Projected",
        fill="tonexty",
        fillcolor=f"rgba({16 if line_color == '#10B981' else 239},{185 if line_color == '#10B981' else 68},{129 if line_color == '#10B981' else 68},0.15)",
        text=[f"₹{v:.2f}" for v in annual_int_path],
        textposition="top center",
        textfont=dict(size=10, color="#F1F5F9"),
        hovertemplate="<b>%{x}</b><br>Annual Interest: ₹%{y:.2f} Cr<extra></extra>",
    ), row=2, col=1)
    
    fig.update_layout(
        height=520,
        plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
        font=dict(color="#F1F5F9", family="Inter, sans-serif"),
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.06,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#94A3B8")),
    )
    fig.update_xaxes(gridcolor="#334155", color="#94A3B8")
    fig.update_yaxes(gridcolor="#334155", color="#94A3B8")
    fig.update_yaxes(title="bps Δ", row=1, col=1)
    fig.update_yaxes(title="₹ Cr (annual)", row=2, col=1)
    
    st.plotly_chart(fig, use_container_width=True)
    
    # ─── Per-facility impact chart ───────────────────────────────────
    st.markdown("#### 🔎 Impact by Facility (at end of 24M)")
    
    fm = data["facility_master"].copy()
    fm = fm[(fm["Effective_OS"] > 0) & ~fm["Sub_Limit_Flag"]]
    fm = fm[fm["Spread_BPS"].notna()]  # only floating-rate
    
    if len(fm) > 0:
        # Compute new interest per facility at final shock
        end_shock = cumulative[-1]
        
        rows = []
        for _, r in fm.iterrows():
            old_int = r["Effective_OS"] * r["Effective_Rate"]
            new_rate = r["Effective_Rate"] + (end_shock / 10000)
            new_int = r["Effective_OS"] * new_rate
            delta = new_int - old_int
            rows.append({
                "Facility": f"{r['Lender']} - {r['Facility']}"[:40],
                "Outstanding": r["Effective_OS"],
                "Δ Interest (₹ Cr)": delta,
            })
        
        df = pd.DataFrame(rows).sort_values("Δ Interest (₹ Cr)",
                                             ascending=(end_shock > 0))
        
        fig3 = go.Figure(go.Bar(
            x=df["Δ Interest (₹ Cr)"],
            y=df["Facility"],
            orientation="h",
            marker_color=["#10B981" if v < 0 else "#EF4444" if v > 0 else "#64748B"
                          for v in df["Δ Interest (₹ Cr)"]],
            text=[f"{v:+.3f}" for v in df["Δ Interest (₹ Cr)"]],
            textposition="outside",
            textfont=dict(size=10, color="#F1F5F9"),
            hovertemplate="<b>%{y}</b><br>Δ %{x:+.3f} Cr/yr<extra></extra>",
        ))
        fig3.update_layout(
            height=max(280, 30 * len(df)),
            plot_bgcolor="#0F172A", paper_bgcolor="#0F172A",
            font=dict(color="#F1F5F9", family="Inter, sans-serif"),
            xaxis=dict(title=f"Δ Annual Interest at {end_shock:+d} bps shock (₹ Cr)",
                       gridcolor="#334155", color="#94A3B8",
                       zeroline=True, zerolinecolor="#94A3B8", zerolinewidth=2),
            yaxis=dict(color="#F1F5F9", autorange="reversed"),
            margin=dict(l=20, r=80, t=20, b=40),
        )
        st.plotly_chart(fig3, use_container_width=True)
