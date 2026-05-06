"""
JCL Debt Monitoring Dashboard — Main Entry Point
─────────────────────────────────────────────────────────────────────
Real-time, Excel-driven, fully-dynamic debt and covenant monitoring.

Excel = single source of truth. Edit Excel → click Reload → updates.
"""

import streamlit as st
import sys
import traceback


# ─── PAGE CONFIG (must be first Streamlit call) ──────────────────────────
st.set_page_config(
    page_title="JCL Debt Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "**JCL Debt Monitor** — Real-time, Excel-driven debt and covenant monitoring dashboard.",
    },
)


# ─── IMPORTS (after page config) ─────────────────────────────────────────
try:
    from data_loader import load_all_data
    from theme import CUSTOM_CSS
    from dashboard_ui import (
        render_sidebar, render_header,
        render_tab_overview, render_tab_repayment, render_tab_covenants,
        render_tab_scenarios, render_tab_renewals, render_tab_ai, render_tab_export,
        render_tab_snapshots,
    )
    from lender_heatmap import render_lender_heatmap
    from rate_path_simulator import render_rate_path_simulator
    from scenario_engine import recompute_covenants
    
    # Gemini AI (optional — fails gracefully if package missing)
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
    st.error(f"❌ Failed to load data from Excel:\n\n```\n{e}\n```")
    st.code(traceback.format_exc())
    st.stop()

if not data.get("excel_exists"):
    st.error(f"⚠️ JCL_Debt_Model_Final.xlsx not found at `{data.get('excel_path')}`.")
    st.markdown("""
**Fix this by one of:**
1. Place `JCL_Debt_Model_Final.xlsx` in the project root
2. Set environment variable `JCL_EXCEL_PATH` to the file path
3. Upload the file via the sidebar uploader (after first launch)
""")
    st.stop()


# ─── SIDEBAR + CONTROLS ──────────────────────────────────────────────────
controls = render_sidebar(data)


# ─── HEADER ──────────────────────────────────────────────────────────────
render_header(data)


# ─── COMPUTE COVENANTS (used by Gemini tab) ──────────────────────────────
fin = data["financials"][controls["basis"]]
cov_df = recompute_covenants(data["covenants"], fin,
                              controls["ebitda_change"], 0, controls["debt_change"])


# ─── TABS ────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "🏠 Overview",
    "📅 Repayment",
    "📋 Covenants",
    "🔬 Scenarios",
    "🌡️ Heatmap",
    "📈 Rate Path",
    "📆 Renewals",
    "🤖 Rule AI",
    "🧠 Gemini AI",
    "📸 Snapshots",
    "📤 Export",
])

with tabs[0]:
    render_tab_overview(data, controls)

with tabs[1]:
    render_tab_repayment(data, controls)

with tabs[2]:
    render_tab_covenants(data, controls)

with tabs[3]:
    render_tab_scenarios(data, controls)

with tabs[4]:
    st.markdown("### 🌡️ Lender × Category Exposure Heatmap")
    st.caption("Visualize where each lender's exposure is concentrated by facility type.")
    render_lender_heatmap(data)

with tabs[5]:
    st.markdown("### 📈 Multi-Quarter Rate Path Simulator")
    render_rate_path_simulator(data)

with tabs[6]:
    render_tab_renewals(data, controls)

with tabs[7]:
    render_tab_ai(data, controls)

with tabs[8]:
    if GEMINI_AVAILABLE:
        render_gemini_tab(data, cov_df)
    else:
        st.markdown("### 🧠 Gemini AI Analyst")
        st.warning("⚠️ google-generativeai package not installed.")
        st.markdown("Install with: `pip install google-generativeai`")
        st.markdown("Or wait for Streamlit Cloud deployment (auto-installs from requirements.txt).")

with tabs[9]:
    render_tab_snapshots(data, controls)

with tabs[10]:
    render_tab_export(data, controls)


# ─── FOOTER ──────────────────────────────────────────────────────────────
st.markdown("""<div style='margin-top:40px;padding:16px;text-align:center;
            border-top:1px solid #334155;color:#64748B;font-size:0.78rem;'>
    JCL Debt Monitor · Excel-driven · All numbers reconcile to JCL_Debt_Model_Final.xlsx
</div>""", unsafe_allow_html=True)
