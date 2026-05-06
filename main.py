"""
JCL Debt Monitoring Dashboard — 5-Tab Concentrated View
─────────────────────────────────────────────────────────────────────
Real-time, Excel-driven, fully-dynamic debt and covenant monitoring.

5 TABS — each with a distinct, focused purpose:
  1. Overview        — KPIs, concentration, composition, facility costs
  2. Covenants       — All 24 covenants + headroom + watch items
  3. Schedule        — Repayment + renewals (everything time-based)
  4. AI Analyst      — Rule-based + Gemini Q&A
  5. Tools           — Snapshots + downloads + PDF export

Stress sliders (sidebar) update everything live. No separate Scenarios tab.
"""

import streamlit as st
import sys
import traceback


# ─── PAGE CONFIG ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="JCL Debt Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "**JCL Debt Monitor** — Real-time, Excel-driven debt monitoring.",
    },
)


# ─── IMPORTS ─────────────────────────────────────────────────────────────
try:
    from data_loader import load_all_data
    from theme import CUSTOM_CSS
    from dashboard_ui import (
        render_sidebar, render_header,
        render_tab_overview, render_tab_repayment, render_tab_covenants,
        render_tab_renewals, render_tab_ai, render_tab_export,
        render_tab_snapshots, render_tab_header,
    )
    from scenario_engine import recompute_covenants
    
    try:
        from gemini_ai import render_gemini_tab
        GEMINI_AVAILABLE = True
    except ImportError:
        GEMINI_AVAILABLE = False
        
except ImportError as e:
    st.error(f"❌ Import error: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ─── APPLY CUSTOM CSS ────────────────────────────────────────────────────
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ─── LOAD DATA ───────────────────────────────────────────────────────────
try:
    data = load_all_data()
except Exception as e:
    st.error(f"❌ Failed to load data:\n\n```\n{e}\n```")
    st.code(traceback.format_exc())
    st.stop()

if not data.get("excel_exists"):
    st.error(f"⚠️ JCL_Debt_Model_Final.xlsx not found.")
    st.stop()


# ─── SIDEBAR ─────────────────────────────────────────────────────────────
controls = render_sidebar(data)


# ─── HEADER ──────────────────────────────────────────────────────────────
render_header(data)


# ─── COMPUTE COVENANTS ───────────────────────────────────────────────────
fin = data["financials"][controls["basis"]]
cov_df = recompute_covenants(data["covenants"], fin,
                              controls["ebitda_change"], 0, controls["debt_change"])


# ─── 5 FOCUSED TABS ──────────────────────────────────────────────────────
tabs = st.tabs([
    "🏠  Overview",
    "📋  Covenants",
    "📅  Schedule",
    "🤖  AI Analyst",
    "💾  Tools",
])

# ═════ TAB 1: OVERVIEW ═════
with tabs[0]:
    render_tab_overview(data, controls)


# ═════ TAB 2: COVENANTS ═════
with tabs[1]:
    render_tab_covenants(data, controls)
    
    if controls["is_stressed"]:
        st.info(f"💡 Stress active: Rate {controls['rate_shock']:+d}bps · "
                f"EBITDA {controls['ebitda_change']:+d}% · "
                f"Debt {controls['debt_change']:+d}%. Adjust sidebar sliders to test scenarios.")
    else:
        st.info("💡 Use sidebar sliders to stress-test covenants. "
                "Click **🌪 Stress** or **⛈ Severe** for Excel preset scenarios.")


# ═════ TAB 3: SCHEDULE (Repayment + Renewals) ═════
with tabs[2]:
    render_tab_repayment(data, controls)
    
    st.markdown("---")
    render_tab_renewals(data, controls)


# ═════ TAB 4: AI ANALYST (Unified) ═════
with tabs[3]:
    if GEMINI_AVAILABLE:
        ai_mode = st.radio(
            "AI Mode:",
            ["⚡ Rule-Based (offline, instant)",
             "🧠 Gemini (online, smart)"],
            horizontal=True, key="ai_mode_toggle",
            label_visibility="collapsed",
        )
        
        if "Gemini" in ai_mode:
            render_gemini_tab(data, cov_df)
        else:
            render_tab_ai(data, controls)
    else:
        render_tab_ai(data, controls)


# ═════ TAB 5: TOOLS (Snapshots + Export) ═════
with tabs[4]:
    sub = st.radio(
        "Tool:",
        ["📤 Downloads & PDF", "📸 Historical Snapshots"],
        horizontal=True, key="tools_tab_radio",
        label_visibility="collapsed",
    )
    
    if "Snapshots" in sub:
        render_tab_snapshots(data, controls)
    else:
        render_tab_export(data, controls)


# ─── FOOTER ──────────────────────────────────────────────────────────────
st.markdown("""<div style='margin-top:40px;padding:16px;text-align:center;
            border-top:1px solid #334155;color:#64748B;font-size:0.78rem;'>
    JCL Debt Monitor · 5-tab concentrated view · Excel-driven
</div>""", unsafe_allow_html=True)
