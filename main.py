"""
JCL Debt Monitoring Dashboard — Main Entry Point
─────────────────────────────────────────────────────────────────────
A real-time, Excel-driven debt monitoring dashboard for Jindal Coke Limited.

Architecture:
  • Excel (JCL_Debt_Model_Final.xlsx) is the SINGLE SOURCE OF TRUTH
  • Every number, rate, threshold, schedule is read from the Excel
  • Edit the Excel → click 'Reload from Excel' → dashboard updates
  • Upload a new Excel via sidebar → dashboard rebuilds

Data flow:
  Excel → data_loader.load_all_data() → {dict of all data}
       → scenario_engine (applies user shocks)
       → dashboard_ui (renders 7 tabs)

Run: streamlit run main.py
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
        "Get Help": "https://github.com/divyanshuvatsa/jcl-final-dashboard",
        "Report a bug": "https://github.com/divyanshuvatsa/jcl-final-dashboard/issues",
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


# ─── TABS ────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "🏠 Overview",
    "📅 Repayment",
    "📋 Covenants",
    "🔬 Scenarios",
    "🌡️ Heatmap",
    "📈 Rate Path",
    "📆 Renewals",
    "🤖 AI Analyst",
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
    render_tab_snapshots(data, controls)

with tabs[9]:
    render_tab_export(data, controls)


# ─── FOOTER ──────────────────────────────────────────────────────────────
st.markdown("""<div style='margin-top:40px;padding:16px;text-align:center;
            border-top:1px solid #334155;color:#64748B;font-size:0.78rem;'>
    JCL Debt Monitor · Excel-driven · Updated from JCL_Debt_Model_Final.xlsx · 
    All numbers reconcile to the source workbook
</div>""", unsafe_allow_html=True)
