"""
Gemini AI Analyst — uses Google Gemini API for flexible Q&A on the dashboard data.

The model receives a structured context with all key facts from the Excel,
and answers user questions in natural language with citations to the data.

Setup:
- Add GEMINI_API_KEY to Streamlit secrets (.streamlit/secrets.toml)
  OR set env variable GEMINI_API_KEY
  OR enter API key in dashboard sidebar
- Free tier: 60 requests/min, sufficient for board reviews

Cost: Free tier covers normal use. Paid tier ~$0.075 per 1M tokens.
"""

from __future__ import annotations
import os
import streamlit as st
from typing import Dict, Any, List
import pandas as pd


def _build_data_context(data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    """Build a comprehensive context string with all key portfolio facts."""
    t = data["totals"]
    isum = data["interest_summary"]
    fy = data["financials"]["FY26E"]
    
    ctx = f"""You are a senior credit analyst providing analysis on Jindal Coke Limited's (JCL) debt portfolio.
You MUST answer ONLY using the data provided below. Do not make up numbers. If a question cannot be answered from this data, say so.

═══ PORTFOLIO SNAPSHOT (As of {data['as_of_date']}) ═══

THREE-BUCKET STRUCTURE (the correct way to add up exposure):
- Bucket 1 (Sanctioned Debt — TL + WC FB cap basis): Rs.{t['Bucket1_Sanctioned_Debt']:,.1f} Cr
- Bucket 2 (NFB Contingent — LCs/SBLCs, parent only): Rs.{t['Bucket2_NFB_Contingent']:,.1f} Cr
- Bucket 3 (Separate Lines — FD-backed + hedge): Rs.{t['Bucket3_Separate']:,.1f} Cr
- TOTAL BANKING EXPOSURE: Rs.{t['Total_Banking_Exposure']:,.1f} Cr
(NOT Rs.3,411 Cr - that incorrect figure double-counts WC sub-limits)

ANNUAL COST:
- Bucket 1 Interest: Rs.{isum['Bucket1_Interest']:,.4f} Cr
- Bucket 2 Commission: Rs.{isum['Bucket2_Commission']:,.4f} Cr
- Bucket 3 Interest: Rs.{isum['Bucket3_Interest']:,.4f} Cr
- TOTAL ANNUAL INTEREST + COMMISSION: Rs.{isum['Total_Interest_Commission']:,.2f} Cr
- Weighted Average Cost: {isum['Weighted_Avg_Cost']*100:.4f}%

FY26E PROJECTED FINANCIALS (Rs. Cr):
- EBITDA: {fy['EBITDA']:,.2f}
- Total Debt: {fy['Total Debt']:,.2f}
- Term Debt: {fy['Term Debt']:,.2f}
- Tangible Net Worth (TNW): {fy['TNW']:,.2f}
- Total Outside Liabilities (TOL): {fy['TOL']:,.2f}
- Interest Expense: {fy['Interest Expense']:,.2f}
- Scheduled TL Repayment: {fy['Sched TL Repay']:,.2f}
- Tax: {fy['Tax']:,.2f}
- Fixed Assets: {fy['Fixed Assets']:,.2f}

LENDER CONCENTRATION:
"""
    for _, r in data["lender_concentration"].iterrows():
        ctx += f"- {r['Lender']}: Rs.{r['Total_Banking_Exposure']:,.1f} Cr ({r['Pct_Banking_Exposure']*100:.1f}% of banking)\n"
    
    # Term loan outstandings
    fm = data["facility_master"]
    tl = fm[fm["Category"] == "FB-Term"]
    ctx += "\nTERM LOAN OUTSTANDINGS (Rs. Cr):\n"
    for _, r in tl.iterrows():
        ctx += f"- {r['Facility']} ({r['Lender']}): Outstanding Rs.{r['Outstanding']:,.2f}, Rate {r['Rate_Display']}\n"
    
    # Covenant summary
    ctx += f"\nCOVENANT COMPLIANCE ({len(cov_df)} total):\n"
    ctx += f"- Compliant: {(cov_df['Status']=='Compliant').sum()}\n"
    ctx += f"- Watch: {(cov_df['Status']=='Watch').sum()}\n"
    ctx += f"- Near Breach: {(cov_df['Status']=='Near Breach').sum()}\n"
    ctx += f"- Breach: {(cov_df['Status']=='Breach').sum()}\n"
    
    # Key ratios (from RBL — most stringent)
    rbl_cov = cov_df[cov_df["Lender"] == "RBL Bank"]
    ctx += "\nKEY FINANCIAL RATIOS (FY26E basis, RBL covenants):\n"
    for _, r in rbl_cov.iterrows():
        if isinstance(r["Actual"], (int, float)):
            ctx += f"- {r['Covenant']}: {r['Actual']:.4f}x (threshold {r['Operator']} {r['Threshold']:.2f}x) — {r['Status']}\n"
    
    # Top covenant by tightness
    ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
    ratio_cov["hr_num"] = pd.to_numeric(ratio_cov.get("Headroom_Pct"), errors="coerce")
    if ratio_cov["hr_num"].notna().any():
        tight = ratio_cov.loc[ratio_cov["hr_num"].idxmin()]
        ctx += f"\nTIGHTEST COVENANT: {tight['Lender']} {tight['Covenant']} = "
        ctx += f"{tight['Actual']:.2f}x vs threshold {tight['Operator']} {tight['Threshold']:.2f}x "
        ctx += f"(headroom {tight['hr_num']:+.1f}%)\n"
    
    # Renewals
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days"] = (fm["Validity_Date"] - as_of).dt.days
    soon = fm[fm["days"].notna() & fm["days"].between(0, 90)]
    ctx += f"\nFACILITIES EXPIRING IN NEXT 90 DAYS ({len(soon)}):\n"
    for _, r in soon.head(10).iterrows():
        ctx += f"- {r['Facility']} ({r['Lender']}): expires in {int(r['days'])} days, sanction Rs.{r['Sanction_INR']:,.1f} Cr\n"
    
    # Repayment schedule
    rep = data["repayment_schedule"].copy()
    if len(rep) > 0:
        rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
        rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
        agg = rep.groupby("FY_Label")["Total_Principal"].sum()
        ctx += f"\nTERM LOAN REPAYMENT SCHEDULE (Rs. Cr by FY):\n"
        for fy_label, amt in agg.items():
            if amt > 0:
                ctx += f"- {fy_label}: {amt:.2f}\n"
    
    ctx += """

INSTRUCTIONS:
1. Answer the user's question using ONLY the data above. Cite specific numbers.
2. Use Indian Rupee Crore (Rs. X Cr) format for amounts.
3. Use 2-4 decimal places for ratios and percentages.
4. If a question requires data not provided, say "I don't have that data — please check the Excel directly."
5. Be concise and use markdown formatting (headers, bullets, bold) for clarity.
6. For risk questions, lead with the main risk and quantify it.
7. NEVER invent numbers. If unsure, omit the figure.
"""
    return ctx


def get_api_key() -> str:
    """Try multiple sources for the Gemini API key."""
    # 1. Streamlit secrets (preferred for cloud)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    
    # 2. Environment variable
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    
    # 3. Session state (user entered in UI)
    return st.session_state.get("gemini_api_key", "")


def ask_gemini(question: str, data: Dict[str, Any], cov_df: pd.DataFrame,
               api_key: str = None, model_name: str = "gemini-2.0-flash") -> str:
    """Send question to Gemini with full data context. Returns markdown answer."""
    if api_key is None:
        api_key = get_api_key()
    
    if not api_key:
        return ("⚠️ **No Gemini API key configured.**\n\n"
                "Get a free key from [Google AI Studio](https://aistudio.google.com/apikey)\n\n"
                "Then either:\n"
                "1. Enter it in the sidebar **AI Settings** section, OR\n"
                "2. Add to `.streamlit/secrets.toml`: `GEMINI_API_KEY = \"your_key\"`")
    
    try:
        import google.generativeai as genai
    except ImportError:
        return ("⚠️ **Gemini library not installed.**\n\n"
                "Run: `pip install google-generativeai`\n\n"
                "Or wait for Streamlit Cloud deployment (auto-installs from requirements.txt).")
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        context = _build_data_context(data, cov_df)
        prompt = f"{context}\n\n═══ USER QUESTION ═══\n{question}\n\n═══ ANSWER ═══\n"
        
        response = model.generate_content(prompt)
        return response.text
    
    except Exception as e:
        return f"⚠️ **Gemini API error:** {str(e)}\n\nFalling back to rule-based AI may help. Or check your API key."


def render_gemini_settings_sidebar():
    """Sidebar section for Gemini API key configuration."""
    with st.sidebar:
        with st.expander("🤖 AI Settings", expanded=False):
            current = get_api_key()
            
            if current:
                masked = current[:6] + "..." + current[-4:] if len(current) > 12 else "****"
                st.markdown(f"<div style='font-size:0.85rem;color:#10B981;'>"
                            f"✓ Gemini API connected ({masked})</div>",
                            unsafe_allow_html=True)
                if st.button("🔄 Change API Key", key="reset_gemini_key", use_container_width=True):
                    st.session_state.pop("gemini_api_key", None)
                    st.rerun()
            else:
                st.markdown(
                    "Add a free Gemini API key for AI-powered Q&A.\n\n"
                    "Get one at [aistudio.google.com](https://aistudio.google.com/apikey)"
                )
                key_input = st.text_input(
                    "Gemini API Key", type="password",
                    placeholder="AIza...", key="gemini_key_input",
                    label_visibility="collapsed",
                )
                if key_input and st.button("💾 Save Key", use_container_width=True, key="save_gemini"):
                    st.session_state["gemini_api_key"] = key_input
                    st.success("Saved! Now use the Gemini Analyst tab.")
                    st.rerun()


# ─── Main render function for Gemini AI tab ──────────────────────────

def render_gemini_tab(data: Dict[str, Any], cov_df: pd.DataFrame):
    """Render the Gemini AI analyst tab."""
    st.markdown("### 🧠 Gemini AI Analyst")
    st.caption("Ask any question about the portfolio in natural language. "
                "Powered by Google Gemini, grounded in your Excel data.")
    
    api_key = get_api_key()
    if not api_key:
        st.warning("⚠️ **Gemini API key required.** Add one in the sidebar (🤖 AI Settings).")
        st.markdown("""
**Why Gemini?**
- Asks any question — no fixed templates
- Free tier covers normal use (60 requests/min)
- Grounds answers in your Excel data
- Cites specific numbers

**How to get a free API key:**
1. Visit [Google AI Studio](https://aistudio.google.com/apikey)
2. Click "Create API Key"
3. Copy the key (starts with `AIza...`)
4. Paste in the sidebar **🤖 AI Settings**
""")
        return
    
    # Suggested questions
    st.markdown("##### 💡 Try asking:")
    suggestions = [
        "What's the most concerning risk in this portfolio and why?",
        "Compare our cost of debt to typical mid-cap manufacturers in India",
        "If RBI cuts rates by 50 bps, what's our annual savings?",
        "Should we refinance any specific facility? Which one and why?",
        "What's our refinancing risk over the next 12 months?",
    ]
    cols = st.columns(2)
    for i, q in enumerate(suggestions):
        with cols[i % 2]:
            if st.button(q, key=f"gem_sug_{i}", use_container_width=True):
                st.session_state["pending_gemini_q"] = q
                st.rerun()
    
    # Free-form input
    pending = st.session_state.pop("pending_gemini_q", "")
    user_q = st.chat_input("Ask anything about the portfolio...")
    
    q_to_process = pending or user_q
    
    if q_to_process:
        if "gemini_history" not in st.session_state:
            st.session_state.gemini_history = []
        
        with st.spinner("🧠 Gemini is analyzing..."):
            answer = ask_gemini(q_to_process, data, cov_df, api_key)
        
        st.session_state.gemini_history.append({"role": "user", "content": q_to_process})
        st.session_state.gemini_history.append({"role": "assistant", "content": answer})
        st.rerun()
    
    # History
    if st.session_state.get("gemini_history"):
        st.markdown("---")
        st.markdown("##### 📝 Conversation")
        for m in st.session_state.gemini_history:
            if m["role"] == "user":
                st.markdown(f"**You:** {m['content']}")
            else:
                st.markdown(m["content"])
            st.markdown("---")
        if st.button("🗑️ Clear conversation", key="clear_gemini_hist"):
            st.session_state.gemini_history = []
            st.rerun()
