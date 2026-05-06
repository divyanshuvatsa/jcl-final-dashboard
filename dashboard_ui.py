"""Dashboard UI — sidebar + 7 tabs. Reads data dict, presents Excel-faithful views."""

from __future__ import annotations
from datetime import date
from typing import Dict, Any
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from theme import COLORS, LENDER_COLORS, CATEGORY_COLORS, STATUS_COLORS, CHART_LAYOUT
from scenario_engine import recompute_covenants, run_scenario, recompute_interest
import rule_based_ai as rba


# ─── Helper formatters ──────────────────────────────────────────────────
def inr(v, d=1):
    if v is None or pd.isna(v): return "—"
    return f"₹{v:,.{d}f} Cr"


def pct(v, d=2):
    if v is None or pd.isna(v): return "—"
    return f"{v*100:.{d}f}%" if abs(v) < 5 else f"{v:.{d}f}%"


def render_hero(verdict, color, narrative):
    st.markdown(f"""<div class='hero-section'>
        <div class='hero-verdict-badge' style='background:{color};color:white;'>● {verdict}</div>
        <p class='hero-narrative'>{narrative}</p></div>""", unsafe_allow_html=True)


def render_tab_header(label, title, subtitle=""):
    sub = f"<div class='tab-header-subtitle'>{subtitle}</div>" if subtitle else ""
    st.markdown(f"""<div class='tab-header'>
        <div class='tab-header-label'>{label}</div>
        <div class='tab-header-title'>{title}</div>{sub}</div>""", unsafe_allow_html=True)


def render_big_kpi(label, value, sub="", color="#F1F5F9"):
    st.markdown(f"""<div class='big-kpi'>
        <div class='big-kpi-label'>{label}</div>
        <div class='big-kpi-value' style='color:{color};'>{value}</div>
        <div class='big-kpi-sub'>{sub}</div></div>""", unsafe_allow_html=True)


def status_pill_class(s):
    return {"Compliant": "compliant", "Watch": "watch",
            "Near Breach": "near", "Breach": "breach"}.get(s, "watch")


# ─── Sidebar ─────────────────────────────────────────────────────────────
def render_sidebar(data: Dict[str, Any]) -> Dict[str, Any]:
    with st.sidebar:
        st.markdown("""<div style='padding:16px 0;border-bottom:1px solid #334155;'>
            <h1 style='font-size:1.4rem;margin:0;'>📊 JCL Debt Monitor</h1>
            <p style='color:#94A3B8;font-size:0.78rem;margin:4px 0 0 0;'>Jindal Coke Limited</p>
        </div>""", unsafe_allow_html=True)
        
        # Excel sync
        st.markdown("### 🔴 Live Excel Sync")
        if data.get("excel_exists"):
            st.caption(f"✅ Source: Excel ({data['excel_path'].split('/')[-1]})")
            st.caption(f"📅 Modified: {data['excel_mtime']}")
            st.caption(f"🔑 Hash: `{data['excel_signature'][:8]}...`")
        else:
            st.error("⚠️ Excel not found — fix path or upload below")
        
        # Excel uploader
        uploaded = st.file_uploader("📤 Upload Updated Excel", type=["xlsx"],
                                     help="Replaces the bundled Excel. Changes apply instantly.",
                                     key="excel_upload")
        if uploaded is not None:
            from data_loader import save_uploaded_excel, force_reload
            save_uploaded_excel(uploaded.getbuffer())
            force_reload()
            st.success(f"✅ Uploaded {uploaded.name}. Reloading...")
            st.rerun()
        
        if st.button("🔄 Reload from Excel", use_container_width=True):
            from data_loader import force_reload
            force_reload()
            st.rerun()
        
        with st.expander("📋 Data Provenance", expanded=False):
            st.markdown("""
**Live (from Excel each reload):**
- All 34 facility outstandings
- 9 benchmark rates
- All financial figures (FY24A & FY26E)
- Sanctioned amounts, spreads, dates
- Covenant thresholds & actuals
- Repayment & Interest schedules
- Three-bucket totals

**The Excel is the single source of truth.**
Edit the Excel → click Reload → everything updates.
""")
        
        st.markdown("---")
        st.markdown("### ⚙️ View Controls")
        
        # Display options
        basis = st.radio("Financial Basis",
                          options=["FY26E", "FY24A"],
                          index=0,
                          horizontal=True,
                          key="basis_input")
        
        # Scenario stress (live recompute)
        st.markdown("### 🔬 Scenario Stress")
        
        # Quick presets
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📈 Stress", use_container_width=True,
                         help="Excel preset: +100bps, +25bps spread, -15% EBITDA, +10% debt"):
                st.session_state.update(rate_shock=100, spread_shock=25,
                                        ebitda_change=-15, debt_change=10)
            if st.button("⛈ Severe", use_container_width=True,
                         help="Excel preset: +200bps, +50bps spread, -30% EBITDA, +25% debt"):
                st.session_state.update(rate_shock=200, spread_shock=50,
                                        ebitda_change=-30, debt_change=25)
        with c2:
            if st.button("📉 EBITDA -20%", use_container_width=True):
                st.session_state.update(rate_shock=0, spread_shock=0,
                                        ebitda_change=-20, debt_change=0)
            if st.button("🔄 Reset", use_container_width=True):
                st.session_state.update(rate_shock=0, spread_shock=0,
                                        ebitda_change=0, debt_change=0)
        
        for k, default in [("rate_shock", 0), ("spread_shock", 0),
                          ("ebitda_change", 0), ("debt_change", 0)]:
            if k not in st.session_state:
                st.session_state[k] = default
        
        rate_shock = st.slider("Rate Shock (bps)", -100, 300, step=25, key="rate_shock")
        spread_shock = st.slider("Spread Shock (bps)", 0, 200, step=25, key="spread_shock")
        ebitda_change = st.slider("EBITDA Change (%)", -40, 30, step=5, key="ebitda_change")
        debt_change = st.slider("Debt Change (%)", 0, 50, step=5, key="debt_change")
        
        is_stressed = any([rate_shock, spread_shock, ebitda_change, debt_change])
        if is_stressed:
            st.markdown(f"""<div class='callout-warn'>
                ⚠️ <b>Stress Active</b><br>
                Rate {rate_shock:+d}bps · Spread {spread_shock:+d}bps · 
                EBITDA {ebitda_change:+d}% · Debt {debt_change:+d}%
            </div>""", unsafe_allow_html=True)
        
        return {
            "basis": basis,
            "rate_shock": rate_shock,
            "spread_shock": spread_shock,
            "ebitda_change": ebitda_change,
            "debt_change": debt_change,
            "is_stressed": is_stressed,
        }


# ─── Header ──────────────────────────────────────────────────────────────
def render_header(data: Dict[str, Any]):
    c1, c2, c3 = st.columns([5, 2, 2])
    with c1:
        st.markdown(f"""<div style='background:linear-gradient(90deg, rgba(37,99,235,0.1) 0%, transparent 100%);
                                padding:16px 20px;border-radius:12px;border:1px solid #1E293B;'>
            <div style='font-size:1.7rem;font-weight:800;
                        background:linear-gradient(90deg,#60A5FA 0%,#C084FC 100%);
                        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>
                JCL Debt Monitoring Dashboard
            </div>
            <div style='color:#94A3B8;font-size:0.85rem;margin-top:4px;'>
                Real-time covenant tracking · Stress testing · Repayment timeline · 
                As-of {pd.Timestamp(data['as_of_date']).strftime('%d-%b-%Y')}
            </div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div style='background:#1E293B;border-radius:12px;padding:14px 18px;text-align:right;'>
            <div style='color:#94A3B8;font-size:0.7rem;text-transform:uppercase;'>FX Rate</div>
            <div style='color:#F1F5F9;font-size:1.3rem;font-weight:700;'>₹{data['fx_rate']:.2f}/USD</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div style='background:#1E293B;border-radius:12px;padding:14px 18px;text-align:right;'>
            <div style='color:#94A3B8;font-size:0.7rem;text-transform:uppercase;'>Basis</div>
            <div style='color:#F1F5F9;font-size:1.3rem;font-weight:700;'>{data['financial_basis']}</div>
        </div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════════════════
def render_tab_overview(data: Dict[str, Any], controls: Dict[str, Any]):
    fin = data["financials"][controls["basis"]]
    cov_df = recompute_covenants(data["covenants"], fin,
                                  controls["ebitda_change"],
                                  0, controls["debt_change"])
    int_calc = recompute_interest(data["facility_master"], data["benchmark_rates"],
                                   controls["rate_shock"], controls["spread_shock"])
    
    t = data["totals"]
    isum = data["interest_summary"]
    conc = data["lender_concentration"]
    compliant = (cov_df["Status"] == "Compliant").sum()
    near = (cov_df["Status"] == "Near Breach").sum()
    breach = (cov_df["Status"] == "Breach").sum()
    watch = (cov_df["Status"] == "Watch").sum()
    
    # Hero verdict
    if breach > 0:
        verdict, color = "ACTION REQUIRED", "#EF4444"
        narrative = f"<b>{breach} covenant(s) currently breached.</b> Lender dialogue required."
    elif near > 0:
        verdict, color = "MONITOR CLOSELY", "#F59E0B"
        narrative = (f"Banking exposure of <b>{inr(t['Total_Banking_Exposure'])}</b> healthy with "
                     f"<b>{near} covenant(s)</b> near threshold. Annual cost {inr(int_calc['Total'])}.")
    else:
        verdict, color = "HEALTHY", "#10B981"
        narrative = (f"Banking exposure of <b>{inr(t['Total_Banking_Exposure'])}</b> across 5 lenders. "
                     f"Sanctioned Debt {inr(t['Bucket1_Sanctioned_Debt'])}, NFB {inr(t['Bucket2_NFB_Contingent'])}, "
                     f"Separate {inr(t['Bucket3_Separate'])}. All <b>{len(cov_df)} covenants compliant</b>.")
    render_hero(verdict, color, narrative)
    
    # Three-bucket KPIs
    render_tab_header("AT A GLANCE", "Three-Bucket View",
                       "Sanctioned Debt is the primary debt total. Banking Exposure includes contingent NFB and FD-backed lines.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_big_kpi("Sanctioned Debt", inr(t["Bucket1_Sanctioned_Debt"]),
                        f"Bucket 1 · TL ₹670.7 + WC FB ₹647", color="#3B82F6")
    with c2:
        render_big_kpi("NFB Contingent", inr(t["Bucket2_NFB_Contingent"], 0),
                        "Bucket 2 · LCs, SBLCs (parent only)", color="#8B5CF6")
    with c3:
        render_big_kpi("Separate Lines", inr(t["Bucket3_Separate"], 0),
                        "Bucket 3 · FD-Backed + Hedge", color="#06B6D4")
    with c4:
        render_big_kpi("Banking Exposure", inr(t["Total_Banking_Exposure"]),
                        f"All buckets · 34 facilities", color="#F59E0B")
    
    # Health KPIs
    render_tab_header("HEALTH", "Cost & Compliance",
                       "Live values reflect current sliders." if controls["is_stressed"] else "Base case (no stress applied).")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        delta = int_calc["Total"] - isum["Total_Interest_Commission"]
        sub = f"Δ {delta:+.1f} vs base" if abs(delta) > 0.01 else f"WAC {pct(int_calc['Weighted_Avg_Cost'])}"
        render_big_kpi("Annual Cost", inr(int_calc["Total"]), sub,
                        color="#FBBF24" if int_calc["Weighted_Avg_Cost"] > 0.08 else "#F1F5F9")
    with c2:
        render_big_kpi("Weighted Avg Cost", pct(int_calc["Weighted_Avg_Cost"]),
                        "On Bucket 1 sanctioned debt",
                        color="#FBBF24" if int_calc["Weighted_Avg_Cost"] > 0.08 else "#10B981")
    with c3:
        status_color = "#10B981" if breach + near == 0 else "#F59E0B" if breach == 0 else "#EF4444"
        render_big_kpi("Covenants", f"{compliant}/{len(cov_df)}",
                        "All clear" if breach + near + watch == 0 else f"{breach} breach · {near} near · {watch} watch",
                        color=status_color)
    with c4:
        top = conc.loc[conc["Total_Banking_Exposure"].idxmax()]
        top_pct = top["Total_Banking_Exposure"] / t["Total_Banking_Exposure"] * 100
        render_big_kpi("Top Lender", f"{top_pct:.1f}%", top["Lender"],
                        color="#F59E0B" if top_pct > 40 else "#10B981")
    
    # Concentration donut + breakdown
    render_tab_header("STRUCTURE", "Lender Concentration",
                       "By Total Banking Exposure (₹ Cr). Hover for details.")
    c1, c2 = st.columns([2, 1])
    with c1:
        cs = conc.sort_values("Total_Banking_Exposure", ascending=False)
        fig = go.Figure(data=[go.Pie(
            labels=cs["Lender"], values=cs["Total_Banking_Exposure"], hole=0.6,
            marker=dict(colors=[LENDER_COLORS.get(l, "#3B82F6") for l in cs["Lender"]],
                        line=dict(color="#1E293B", width=3)),
            textinfo="label+percent", textposition="outside",
            hovertemplate="<b>%{label}</b><br>%{value:.1f} Cr<br>%{percent}<extra></extra>",
        )])
        fig.update_layout(**CHART_LAYOUT, height=420, showlegend=False,
                           annotations=[dict(text=f"<b>{t['Total_Banking_Exposure']:,.0f}</b>"
                                                  f"<br><span style='font-size:0.95rem;color:#94A3B8'>Cr Banking</span>",
                                              x=0.5, y=0.5, font=dict(size=24, color="#F1F5F9"),
                                              showarrow=False)])
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        top = cs.iloc[0]
        ts = top["Total_Banking_Exposure"] / t["Total_Banking_Exposure"] * 100
        st.markdown(f"""
        <div style='padding:16px 0;'>
            <div style='font-size:0.78rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;'>Largest Lender</div>
            <div style='font-size:1.5rem;font-weight:700;color:#F1F5F9;'>{top['Lender']}</div>
            <div style='color:#CBD5E1;'>{inr(top['Total_Banking_Exposure'])} <span class='mini-stat'>{ts:.1f}%</span></div>
        </div>
        <div style='padding:16px 0;border-top:1px solid #334155;'>
            <div style='font-size:0.78rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;'>Sanctioned Debt</div>
            <div style='font-size:1.5rem;font-weight:700;color:#F1F5F9;'>{inr(t['Bucket1_Sanctioned_Debt'])}</div>
            <div style='color:#CBD5E1;font-size:0.8rem;'>Primary debt total (Bucket 1)</div>
        </div>
        <div style='padding:16px 0;border-top:1px solid #334155;'>
            <div style='font-size:0.78rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;'>Diversification</div>
            <div style='font-size:1.5rem;font-weight:700;color:{"#F59E0B" if ts > 40 else "#10B981"};'>{"Concentrated" if ts > 40 else "Diversified"}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Three-bucket detailed table
    with st.expander("🔍 Detailed three-bucket breakdown", expanded=False):
        b1 = data["lender_bucket1"]
        b2 = data["lender_bucket2"]
        b3 = data["lender_bucket3"]
        merged = b1.merge(b2[["Lender", "Bucket2_Total_NFB"]], on="Lender", how="outer") \
                    .merge(b3[["Lender", "Bucket3_Total"]], on="Lender", how="outer") \
                    .merge(conc[["Lender", "Total_Banking_Exposure"]], on="Lender", how="outer") \
                    .fillna(0)
        merged = merged[merged["Lender"] != "Grand Total"]
        for col in ["TL_Sanctioned", "WC_FB_Cap", "Bucket1_Total_Debt", "Bucket2_Total_NFB",
                     "Bucket3_Total", "Total_Banking_Exposure"]:
            if col in merged.columns:
                merged[col] = merged[col].apply(lambda x: f"₹{x:,.1f}")
        merged.columns = [c.replace("_", " ") for c in merged.columns]
        st.dataframe(merged, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — REPAYMENT
# ═══════════════════════════════════════════════════════════════════════
def render_tab_repayment(data: Dict[str, Any], controls: Dict[str, Any]):
    rep = data["repayment_schedule"].copy()
    if len(rep) == 0:
        st.info("No repayment schedule available.")
        return
    
    fm = data["facility_master"]
    as_of = pd.Timestamp(data["as_of_date"])
    
    # Aggregate by FY
    rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
    rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
    fy_agg = rep.groupby("FY_Label").agg(
        RBL=("RBL_Principal", "sum"),
        YBL=("YBL_Principal", "sum"),
        Bajaj=("Bajaj_Principal", "sum"),
        Total_Prin=("Total_Principal", "sum"),
        Total_Int=("Total_Interest", "sum"),
        Total_DS=("Total_DS", "sum"),
    ).reset_index()
    
    # KPIs
    next_12m = rep[rep["Period_End"].between(as_of, as_of + pd.Timedelta(days=365))]
    next_12m_ds = next_12m["Total_DS"].sum()
    
    tl_total_outstanding = fm[fm["Category"] == "FB-Term"]["Effective_OS"].sum()
    fy_active = fy_agg[fy_agg["Total_Prin"] > 0]
    peak_year = fy_active.loc[fy_active["Total_Prin"].idxmax()] if len(fy_active) else None
    
    upcoming_renewals = fm[(fm["Validity_Date"] - as_of).dt.days.between(0, 60)]
    
    if len(upcoming_renewals) > 5:
        verdict, color = "RENEWALS DUE", "#F59E0B"
        narrative = (f"<b>{len(upcoming_renewals)} facilities</b> "
                     f"({inr(upcoming_renewals['Sanction_INR'].sum())}) need renewal in 60 days.")
    else:
        verdict, color = "ON TRACK", "#10B981"
        narrative = (f"Term loan portfolio on a structured path. Next 12 months: "
                     f"<b>{inr(next_12m_ds)}</b> debt service.")
    render_hero(verdict, color, narrative)
    
    render_tab_header("LIQUIDITY", "Cash Flow Obligations")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_big_kpi("TL Outstanding", inr(tl_total_outstanding, 1),
                        f"3 active term loans")
    with c2:
        prin_12m = next_12m["Total_Principal"].sum()
        int_12m = next_12m["Total_Interest"].sum()
        render_big_kpi("Next 12 Months", inr(next_12m_ds, 1),
                        f"P {inr(prin_12m, 0)} + I {inr(int_12m, 0)}")
    with c3:
        if peak_year is not None:
            render_big_kpi("Peak Year", peak_year["FY_Label"],
                            f"{inr(peak_year['Total_Prin'])} principal")
        else:
            render_big_kpi("Peak Year", "—", "")
    with c4:
        cov_df = recompute_covenants(data["covenants"], data["financials"][controls["basis"]],
                                       controls["ebitda_change"], 0, controls["debt_change"])
        dscr = cov_df[cov_df["Covenant"] == "DSCR"]["Actual"].iloc[0] if len(cov_df) else 0
        render_big_kpi("DSCR", f"{dscr:.2f}x" if isinstance(dscr, (int, float)) else "—",
                        "vs ≥1.50x threshold",
                        color="#10B981" if dscr > 2.0 else "#F59E0B")
    
    # Annual repayment chart by lender
    render_tab_header("TIMELINE", "Annual Principal Repayment by Lender")
    fy_chart = fy_agg[fy_agg["Total_Prin"] > 0].sort_values("FY_Label")
    fig = go.Figure()
    for lender, col, color in [("RBL Bank", "RBL", LENDER_COLORS["RBL Bank"]),
                                ("YES Bank", "YBL", LENDER_COLORS["YES Bank"]),
                                ("Bajaj Finance", "Bajaj", LENDER_COLORS["Bajaj Finance"])]:
        fig.add_trace(go.Bar(name=lender, x=fy_chart["FY_Label"], y=fy_chart[col],
                              marker_color=color,
                              hovertemplate=f"<b>{lender}</b><br>%{{x}}<br>₹%{{y:.2f}} Cr<extra></extra>"))
    fig.update_layout(**CHART_LAYOUT, height=420, barmode="stack",
                       xaxis=dict(title="Financial Year"),
                       yaxis=dict(title="Principal (₹ Cr)", gridcolor="#334155"),
                       legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.18))
    st.plotly_chart(fig, use_container_width=True)
    
    # Upcoming renewals
    render_tab_header("ATTENTION", "Upcoming Renewals (≤90 days)")
    upcoming_90 = fm.copy()
    upcoming_90["days_to_expiry"] = (upcoming_90["Validity_Date"] - as_of).dt.days
    upcoming_90 = upcoming_90[upcoming_90["days_to_expiry"].between(0, 90)].sort_values("days_to_expiry")
    
    if len(upcoming_90) == 0:
        st.markdown("<div class='callout-good'><b>✅ No renewals required in 90 days.</b></div>",
                     unsafe_allow_html=True)
    else:
        d = upcoming_90[["Lender", "Facility", "Validity_Date", "days_to_expiry", "Sanction_INR"]].copy()
        d["Validity_Date"] = d["Validity_Date"].dt.strftime("%d-%b-%Y")
        d["Sanction_INR"] = d["Sanction_INR"].apply(lambda x: f"₹{x:,.1f}")
        d.columns = ["Lender", "Facility", "Expires", "Days", "Sanctioned"]
        st.dataframe(d, use_container_width=True, hide_index=True)
    
    # Quarterly schedule
    with st.expander("📅 Full quarterly repayment schedule", expanded=False):
        rep_show = rep.copy()
        rep_show["Period"] = rep_show["Period_End"].dt.strftime("%d-%b-%Y") + " (" + rep_show["Period_Label"] + ")"
        rep_show = rep_show[(rep_show["Period_End"] >= as_of - pd.Timedelta(days=90))].head(40)
        for col in ["RBL_Principal", "RBL_Interest", "YBL_Principal", "YBL_Interest",
                    "Bajaj_Principal", "Bajaj_Interest", "Total_Principal", "Total_Interest", "Total_DS"]:
            rep_show[col] = rep_show[col].apply(lambda x: f"{x:.2f}" if x > 0 else "—")
        cols_show = ["Period", "RBL_Principal", "RBL_Interest",
                      "YBL_Principal", "YBL_Interest",
                      "Bajaj_Principal", "Bajaj_Interest",
                      "Total_Principal", "Total_Interest", "Total_DS"]
        rep_show.columns = [c.replace("_", " ") for c in rep_show.columns]
        cols_show = [c.replace("_", " ") for c in cols_show]
        st.dataframe(rep_show[cols_show], use_container_width=True, hide_index=True)
    
    # Facility browser
    with st.expander("🔍 Browse all 34 facilities", expanded=False):
        search = st.text_input("Search", "", key="fac_search_browser")
        df = fm.copy()
        if search:
            mask = (df["Facility"].str.contains(search, case=False, na=False) |
                    df["Lender"].str.contains(search, case=False, na=False))
            df = df[mask]
        disp = df[["S_No", "Lender", "Facility", "Category", "Bucket",
                    "Sanction_INR", "Effective_OS", "Effective_Rate",
                    "Validity_Date", "Maturity_Date"]].copy()
        disp["Sanction_INR"] = disp["Sanction_INR"].apply(lambda x: f"₹{x:,.1f}")
        disp["Effective_OS"] = disp["Effective_OS"].apply(lambda x: f"₹{x:,.2f}")
        disp["Effective_Rate"] = disp["Effective_Rate"].apply(lambda x: f"{x*100:.2f}%" if x > 0 else "TBD")
        disp["Validity_Date"] = pd.to_datetime(disp["Validity_Date"]).dt.strftime("%d-%b-%Y")
        disp["Maturity_Date"] = pd.to_datetime(disp["Maturity_Date"]).dt.strftime("%d-%b-%Y").fillna("Revolving")
        disp.columns = ["S.No", "Lender", "Facility", "Cat", "B",
                         "Sanc", "Eff O/S", "Rate", "Validity", "Maturity"]
        st.dataframe(disp, use_container_width=True, hide_index=True, height=400)


# ═══════════════════════════════════════════════════════════════════════
# TAB 3 — COVENANTS
# ═══════════════════════════════════════════════════════════════════════
def render_tab_covenants(data: Dict[str, Any], controls: Dict[str, Any]):
    fin = data["financials"][controls["basis"]]
    cov_df = recompute_covenants(data["covenants"], fin,
                                  controls["ebitda_change"],
                                  0, controls["debt_change"])
    
    compliant = (cov_df["Status"] == "Compliant").sum()
    watch = (cov_df["Status"] == "Watch").sum()
    near = (cov_df["Status"] == "Near Breach").sum()
    breach = (cov_df["Status"] == "Breach").sum()
    
    if breach > 0:
        verdict, color = "BREACH", "#EF4444"
        narrative = f"<b>{breach} covenant(s) breached.</b> Lender dialogue required immediately."
    elif near > 0:
        verdict, color = "MONITOR", "#F59E0B"
        t = cov_df[cov_df["Status"] == "Near Breach"].iloc[0]
        narrative = (f"<b>{compliant}/{len(cov_df)}</b> compliant. <b>{near}</b> near threshold — "
                     f"most notably <b>{t['Lender']} {t['Covenant']}</b> at "
                     f"{t['Headroom_Pct']:+.1f}% headroom.")
    else:
        verdict, color = "ALL CLEAR", "#10B981"
        ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
        ratio_cov["hr"] = pd.to_numeric(ratio_cov["Headroom_Pct"], errors="coerce")
        avg_hr = ratio_cov["hr"].mean()
        narrative = f"All <b>{len(cov_df)}</b> covenants compliant. Avg ratio headroom: <b>{avg_hr:.0f}%</b>."
    render_hero(verdict, color, narrative)
    
    render_tab_header("STATUS", "Compliance Dashboard")
    c1, c2, c3, c4 = st.columns(4)
    with c1: render_big_kpi("Compliant", str(compliant), f"{compliant/len(cov_df)*100:.0f}%", color="#10B981")
    with c2: render_big_kpi("Watch", str(watch), "5–10% buffer", color="#3B82F6")
    with c3: render_big_kpi("Near Breach", str(near), "<5% buffer", color="#F59E0B" if near else "#94A3B8")
    with c4: render_big_kpi("Breach", str(breach), "Action req'd", color="#EF4444" if breach else "#94A3B8")
    
    # Watch items
    attention = cov_df[cov_df["Status"].isin(["Breach", "Near Breach", "Watch"])]
    if len(attention) > 0:
        render_tab_header("ATTENTION", f"{len(attention)} Covenants Requiring Watch")
        for _, r in attention.iterrows():
            color = STATUS_COLORS.get(r["Status"], "#3B82F6")
            bg = {"Breach": "rgba(239,68,68,0.1)",
                   "Near Breach": "rgba(245,158,11,0.1)",
                   "Watch": "rgba(59,130,246,0.05)"}.get(r["Status"], "rgba(59,130,246,0.05)")
            actual = r["Actual"]
            actual_str = f"{actual:.2f}x" if isinstance(actual, (int, float)) else str(actual)[:30]
            thr_str = f"{r['Operator']}{r['Threshold']:.2f}x" if isinstance(r['Threshold'], (int, float)) else "≥A-"
            hr_str = f"{r['Headroom_Pct']:+.1f}%" if r["Headroom_Pct"] is not None else "—"
            st.markdown(f"""<div style='background:{bg};border-left:4px solid {color};
                                  border-radius:12px;padding:14px 18px;margin-bottom:8px;'>
                <div style='display:flex;justify-content:space-between;'>
                    <div style='flex:1;'>
                        <div style='font-size:0.7rem;color:{color};text-transform:uppercase;font-weight:700;'>
                            {r['Status']} · {r['Lender']}
                        </div>
                        <div style='font-size:1.05rem;font-weight:700;color:#F1F5F9;margin:4px 0;'>{r['Covenant']}</div>
                        <div style='color:#CBD5E1;font-size:0.88rem;'>
                            Actual: <b>{actual_str}</b> · Threshold: {thr_str}
                        </div>
                    </div>
                    <div style='text-align:right;'>
                        <div style='font-size:0.7rem;color:#94A3B8;text-transform:uppercase;'>Headroom</div>
                        <div style='font-size:1.5rem;font-weight:800;color:{color};'>{hr_str}</div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("<div class='callout-good'><b>✅ All 24 covenants well within thresholds.</b></div>",
                     unsafe_allow_html=True)
    
    # Full table by lender
    with st.expander("📋 View all 24 covenants by lender", expanded=True):
        for lender in cov_df["Lender"].unique():
            sub = cov_df[cov_df["Lender"] == lender]
            st.markdown(f"#### {lender} ({len(sub)} covenants)")
            d = sub.copy()
            d["Actual_S"] = d["Actual"].apply(
                lambda x: f"{x:.4f}x" if isinstance(x, (int, float)) else str(x)[:25])
            d["Headroom_S"] = d["Headroom_Pct"].apply(
                lambda x: f"{x:+.1f}%" if isinstance(x, (int, float)) and pd.notna(x) else "—")
            d["Threshold_S"] = d.apply(lambda r: f"{r['Operator']}{r['Threshold']:.2f}x"
                                         if isinstance(r['Threshold'], (int, float)) else f"≥{r['Threshold']}", axis=1)
            d_show = d[["Covenant", "Threshold_S", "Actual_S", "Headroom_S", "Status"]].copy()
            d_show.columns = ["Covenant", "Threshold", "Actual", "Headroom", "Status"]
            st.dataframe(d_show, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# TAB 4 — SCENARIOS
# ═══════════════════════════════════════════════════════════════════════
def render_tab_scenarios(data: Dict[str, Any], controls: Dict[str, Any]):
    sc = run_scenario(data, controls["rate_shock"], controls["spread_shock"],
                       controls["ebitda_change"], controls["debt_change"], controls["basis"])
    
    base_int = sc["base"]["interest"]
    stress_int = sc["stress"]["interest"]
    base_cov = sc["base"]["covenants"]
    stress_cov = sc["stress"]["covenants"]
    
    base_dscr = base_cov[base_cov["Covenant"] == "DSCR"]["Actual"].iloc[0]
    stress_dscr = stress_cov[stress_cov["Covenant"] == "DSCR"]["Actual"].iloc[0]
    
    # Severe preset analysis (from Excel)
    severe = run_scenario(data, 200, 50, -30, 25, controls["basis"])
    sev_breach = (severe["stress"]["covenants"]["Status"] == "Breach").sum()
    
    if sev_breach > 0:
        verdict, color = "RESILIENT TO MODERATE STRESS", "#3B82F6"
        narrative = f"Portfolio absorbs moderate stress. Severe stress (Excel preset) triggers {sev_breach} breach(es)."
    else:
        verdict, color = "HIGHLY RESILIENT", "#10B981"
        narrative = "Portfolio is <b>highly resilient</b>. Even severe combined stress causes no covenant breach."
    render_hero(verdict, color, narrative)
    
    if controls["is_stressed"]:
        st.markdown(f"""<div class='callout-info'>🔬 <b>Live Stress Active</b>:
            <span class='mini-stat'>Rate {controls['rate_shock']:+d}b</span>
            <span class='mini-stat'>Spread {controls['spread_shock']:+d}b</span>
            <span class='mini-stat'>EBITDA {controls['ebitda_change']:+d}%</span>
            <span class='mini-stat'>Debt {controls['debt_change']:+d}%</span>
        </div>""", unsafe_allow_html=True)
    
    # Current scenario impact
    render_tab_header("LIVE IMPACT", "Current Scenario vs Base")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        delta_int = stress_int["Total"] - base_int["Total"]
        pct_chg = (delta_int / base_int["Total"] * 100) if base_int["Total"] else 0
        render_big_kpi("Annual Interest", inr(stress_int["Total"]),
                        f"{delta_int:+.1f} ({pct_chg:+.1f}%)",
                        color="#EF4444" if delta_int > 5 else "#F1F5F9")
    with c2:
        wac_d = (stress_int["Weighted_Avg_Cost"] - base_int["Weighted_Avg_Cost"]) * 10000
        render_big_kpi("WAC", pct(stress_int["Weighted_Avg_Cost"]),
                        f"{wac_d:+.0f} bps", color="#EF4444" if wac_d > 100 else "#F1F5F9")
    with c3:
        d_dscr = stress_dscr - base_dscr
        render_big_kpi("DSCR", f"{stress_dscr:.2f}x",
                        f"{d_dscr:+.2f}x · floor 1.50x",
                        color="#10B981" if stress_dscr >= 1.5 else "#EF4444")
    with c4:
        base_icr = base_cov[base_cov["Covenant"] == "ICR"]["Actual"].iloc[0] if len(base_cov[base_cov["Covenant"] == "ICR"]) else 0
        stress_icr = stress_cov[stress_cov["Covenant"] == "ICR"]["Actual"].iloc[0] if len(stress_cov[stress_cov["Covenant"] == "ICR"]) else 0
        render_big_kpi("ICR", f"{stress_icr:.2f}x", f"{stress_icr - base_icr:+.2f}x",
                        color="#10B981" if stress_icr >= 3.0 else "#F59E0B")
    
    # Excel preset library
    render_tab_header("LIBRARY", "Pre-Defined Scenarios (Excel)")
    si = data["scenario_inputs"]
    so = data["scenario_outputs"]
    
    library_rows = []
    for i, name in enumerate(["Base", "Stress (Excel preset)", "Severe (Excel preset)"]):
        library_rows.append({
            "Scenario": name,
            "Rate Shock": f"{si['Rate_Shock_BPS'][i]:+.0f}bps",
            "Spread": f"{si['Spread_BPS'][i]:+.0f}bps",
            "EBITDA Δ": f"{si['EBITDA_Change_Pct'][i]:+.0f}%",
            "Debt Δ": f"{si['Debt_Change_Pct'][i]:+.0f}%",
            "B1 Interest": f"₹{so['Annual_B1_Interest'][i]:.2f}",
            "DSCR": f"{so['DSCR_Stressed'][i]:.4f}x",
            "Total Debt/EBITDA": f"{so['Total_Debt_EBITDA'][i]:.4f}x",
            "ICR": f"{so['ICR'][i]:.4f}x",
        })
    st.dataframe(pd.DataFrame(library_rows), use_container_width=True, hide_index=True)
    st.caption("These three scenarios are Excel-defined presets. Move sidebar sliders to test custom combinations.")
    
    # Sensitivity by benchmark
    render_tab_header("SENSITIVITY", "Rate Sensitivity by Benchmark")
    sens = data["rate_sensitivity"]
    if len(sens) > 0:
        fig = go.Figure(data=[go.Bar(
            x=sens["Benchmark"], y=sens["Delta_Interest_100bps"],
            marker_color="#3B82F6",
            text=sens["Delta_Interest_100bps"].apply(lambda x: f"₹{x:.2f}"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>+100 bps → +₹%{y:.3f} Cr<extra></extra>",
        )])
        fig.update_layout(**CHART_LAYOUT, height=400,
                           xaxis=dict(title="Benchmark", tickangle=-30),
                           yaxis=dict(title="Δ Annual Interest at +100 bps (₹ Cr)", gridcolor="#334155"))
        st.plotly_chart(fig, use_container_width=True)
        total_sens = sens["Delta_Interest_100bps"].sum()
        st.caption(f"**Combined sensitivity:** A parallel +100 bps shock to ALL floating benchmarks "
                    f"adds ≈ ₹{total_sens:.2f} Cr in annual interest expense.")


# ═══════════════════════════════════════════════════════════════════════
# TAB 5 — RENEWAL CALENDAR (NEW FEATURE)
# ═══════════════════════════════════════════════════════════════════════
def render_tab_renewals(data: Dict[str, Any], controls: Dict[str, Any]):
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days_to_expiry"] = (fm["Validity_Date"] - as_of).dt.days
    
    expired = fm[fm["days_to_expiry"] < 0]
    next_30 = fm[fm["days_to_expiry"].between(0, 30)]
    next_60 = fm[fm["days_to_expiry"].between(31, 60)]
    next_90 = fm[fm["days_to_expiry"].between(61, 90)]
    next_180 = fm[fm["days_to_expiry"].between(91, 180)]
    later = fm[fm["days_to_expiry"] > 180]
    
    total_urgent = len(next_30) + len(next_60)
    total_urgent_value = pd.concat([next_30, next_60])["Sanction_INR"].sum() if total_urgent > 0 else 0
    
    if total_urgent > 5:
        verdict, color = "ACTION REQUIRED", "#EF4444"
        narrative = f"<b>{total_urgent} facilities</b> ({inr(total_urgent_value)}) need renewal in 60 days."
    elif total_urgent > 0:
        verdict, color = "RENEWAL CYCLE", "#F59E0B"
        narrative = f"<b>{total_urgent} facilities</b> ({inr(total_urgent_value)}) due in 60 days. Initiate renewal."
    else:
        verdict, color = "NO IMMEDIATE ACTION", "#10B981"
        narrative = "No renewals required in next 60 days. Continue regular monitoring."
    render_hero(verdict, color, narrative)
    
    render_tab_header("CALENDAR", "Renewal Pipeline by Bucket")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: render_big_kpi("≤30 days", str(len(next_30)),
                              inr(next_30["Sanction_INR"].sum()) if len(next_30) else "—",
                              color="#EF4444")
    with c2: render_big_kpi("31-60 days", str(len(next_60)),
                              inr(next_60["Sanction_INR"].sum()) if len(next_60) else "—",
                              color="#F59E0B")
    with c3: render_big_kpi("61-90 days", str(len(next_90)),
                              inr(next_90["Sanction_INR"].sum()) if len(next_90) else "—",
                              color="#3B82F6")
    with c4: render_big_kpi("91-180 days", str(len(next_180)),
                              inr(next_180["Sanction_INR"].sum()) if len(next_180) else "—",
                              color="#94A3B8")
    with c5: render_big_kpi(">180 days", str(len(later)),
                              inr(later["Sanction_INR"].sum()) if len(later) else "—",
                              color="#10B981")
    
    # Detailed table per bucket
    render_tab_header("ACTIONS", "Priority-Ordered Renewal List")
    upcoming = fm[fm["days_to_expiry"].between(-30, 365)].sort_values("days_to_expiry")
    
    if len(upcoming) == 0:
        st.markdown("<div class='callout-good'><b>✅ No renewals in pipeline.</b></div>",
                     unsafe_allow_html=True)
    else:
        for _, r in upcoming.iterrows():
            days = int(r["days_to_expiry"])
            if days < 0:
                priority, color = "EXPIRED", "#EF4444"
                bg = "rgba(239,68,68,0.1)"
                action = "Renewal overdue. Contact lender immediately."
            elif days <= 30:
                priority, color = "URGENT", "#EF4444"
                bg = "rgba(239,68,68,0.1)"
                action = "Submit renewal request now."
            elif days <= 60:
                priority, color = "HIGH", "#F59E0B"
                bg = "rgba(245,158,11,0.1)"
                action = "Begin renewal preparation."
            elif days <= 90:
                priority, color = "MEDIUM", "#3B82F6"
                bg = "rgba(59,130,246,0.05)"
                action = "Schedule renewal discussions."
            else:
                priority, color = "LOW", "#94A3B8"
                bg = "rgba(148,163,184,0.05)"
                action = "Monitor."
            
            st.markdown(f"""<div style='background:{bg};border-left:4px solid {color};
                                  border-radius:12px;padding:14px 18px;margin-bottom:8px;'>
                <div style='display:flex;justify-content:space-between;'>
                    <div style='flex:2;'>
                        <span style='background:{color};color:white;padding:2px 8px;
                                      border-radius:4px;font-size:0.65rem;font-weight:800;
                                      letter-spacing:0.08em;'>{priority}</span>
                        <span style='color:#94A3B8;font-size:0.78rem;margin-left:8px;'>
                            {r['Lender']} · {r['Facility']}
                        </span>
                        <div style='color:#F1F5F9;font-size:0.95rem;margin-top:4px;'>{action}</div>
                    </div>
                    <div style='flex:1;text-align:right;'>
                        <div style='color:#94A3B8;font-size:0.7rem;'>EXPIRES</div>
                        <div style='color:#F1F5F9;font-size:1rem;font-weight:700;'>
                            {r['Validity_Date'].strftime('%d-%b-%Y')}
                        </div>
                        <div style='color:{color};font-size:0.85rem;'>{days:+d} days</div>
                        <div style='color:#94A3B8;font-size:0.78rem;'>{inr(r['Sanction_INR'])}</div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# TAB 6 — AI ANALYST
# ═══════════════════════════════════════════════════════════════════════
def render_tab_ai(data: Dict[str, Any], controls: Dict[str, Any]):
    fin = data["financials"][controls["basis"]]
    cov_df = recompute_covenants(data["covenants"], fin,
                                  controls["ebitda_change"],
                                  0, controls["debt_change"])
    
    render_tab_header("AI ANALYST", "Rule-Based Q&A",
                       "Always-on, deterministic answers powered by live Excel data.")
    
    # Proactive insights
    st.markdown("#### 💡 Proactive Insights")
    insights = rba.get_proactive_insights(data, cov_df)
    cols = st.columns(2)
    for i, ins in enumerate(insights):
        with cols[i % 2]:
            level = ins.get("level", "info")
            st.markdown(f"""<div class='insight-card {level}'>
                <div class='insight-title'>{ins['icon']} {ins['title']}</div>
                <div class='insight-body'>{ins['body']}</div></div>""", unsafe_allow_html=True)
    
    # Suggested questions
    st.markdown("#### 💬 Suggested Questions")
    cols = st.columns(2)
    for i, q in enumerate(rba.SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(q, key=f"rq_{i}", use_container_width=True):
                resp = rba.answer_question(q, data, cov_df)
                if "ai_history" not in st.session_state:
                    st.session_state.ai_history = []
                st.session_state.ai_history.append({"role": "user", "content": q})
                st.session_state.ai_history.append({"role": "assistant", "content": resp})
                st.rerun()
    
    # Free-form input
    user_input = st.chat_input("Ask anything about the portfolio...")
    if user_input:
        resp = rba.answer_question(user_input, data, cov_df)
        if "ai_history" not in st.session_state:
            st.session_state.ai_history = []
        st.session_state.ai_history.append({"role": "user", "content": user_input})
        st.session_state.ai_history.append({"role": "assistant", "content": resp})
        st.rerun()
    
    # Conversation history
    if st.session_state.get("ai_history"):
        st.markdown("#### 📝 Conversation")
        for m in st.session_state.ai_history:
            if m["role"] == "user":
                st.markdown(f"**You:** {m['content']}")
            else:
                st.markdown(m["content"])
            st.markdown("---")
        if st.button("🗑️ Clear conversation"):
            st.session_state.ai_history = []
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# TAB 7 — EXPORT & DOWNLOADS
# ═══════════════════════════════════════════════════════════════════════
def render_tab_export(data: Dict[str, Any], controls: Dict[str, Any]):
    render_tab_header("EXPORT", "Data & Reports",
                       "Download CSVs, PDF board memo, or snapshot the current state.")
    
    fin = data["financials"][controls["basis"]]
    cov_df = recompute_covenants(data["covenants"], fin,
                                  controls["ebitda_change"],
                                  0, controls["debt_change"])
    
    # ─── PDF Board Memo (top, prominent) ─────────────────────────────
    st.markdown("#### 📄 Board Memo (PDF)")
    st.caption("A polished 2-page PDF with verdict, KPIs, three-bucket table, "
                "lender concentration, all 24 covenants, and key observations. "
                "Suitable for sharing with senior management.")
    try:
        from pdf_export import generate_board_memo
        pdf_bytes = generate_board_memo(data, cov_df, controls)
        st.download_button(
            "📄 Download Board Memo PDF",
            data=pdf_bytes,
            file_name=f"JCL_Board_Memo_{data['as_of_date']}.pdf",
            mime="application/pdf",
            use_container_width=True, type="primary",
        )
    except Exception as e:
        st.error(f"PDF generation failed: {e}")
    
    st.markdown("---")
    st.markdown("#### 📊 Data Files (CSV)")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        csv = cov_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Covenants CSV", csv,
                            file_name=f"jcl_covenants_{data['as_of_date']}.csv",
                            mime="text/csv", use_container_width=True)
    with c2:
        csv = data["facility_master"].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Facility Master CSV", csv,
                            file_name=f"jcl_facilities_{data['as_of_date']}.csv",
                            mime="text/csv", use_container_width=True)
    with c3:
        csv = data["interest_schedule"].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Interest Schedule CSV", csv,
                            file_name=f"jcl_interest_{data['as_of_date']}.csv",
                            mime="text/csv", use_container_width=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        csv = data["repayment_schedule"].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Repayment Schedule CSV", csv,
                            file_name=f"jcl_repayment_{data['as_of_date']}.csv",
                            mime="text/csv", use_container_width=True)
    with c2:
        csv = data["lender_concentration"].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Lender Concentration CSV", csv,
                            file_name=f"jcl_lenders_{data['as_of_date']}.csv",
                            mime="text/csv", use_container_width=True)
    with c3:
        # Combined snapshot
        snapshot = {
            "as_of_date": str(data['as_of_date']),
            "fx_rate": data['fx_rate'],
            "totals": data['totals'],
            "interest_summary": data['interest_summary'],
            "stress_applied": controls,
        }
        import json
        snap_json = json.dumps(snapshot, indent=2, default=str).encode("utf-8")
        st.download_button("📥 State Snapshot JSON", snap_json,
                            file_name=f"jcl_snapshot_{data['as_of_date']}.json",
                            mime="application/json", use_container_width=True)
    
    # Headline summary
    render_tab_header("SUMMARY", "Headline Numbers")
    st.markdown(f"""
| Metric | Value |
|--------|-------|
| As-of date | {data['as_of_date']} |
| FX Rate | ₹{data['fx_rate']:.2f}/USD |
| Bucket 1 — Sanctioned Debt | {inr(data['totals']['Bucket1_Sanctioned_Debt'])} |
| Bucket 2 — NFB Contingent | {inr(data['totals']['Bucket2_NFB_Contingent'])} |
| Bucket 3 — Separate Lines | {inr(data['totals']['Bucket3_Separate'])} |
| **Total Banking Exposure** | **{inr(data['totals']['Total_Banking_Exposure'])}** |
| Annual Interest + Commission | {inr(data['interest_summary']['Total_Interest_Commission'])} |
| Weighted Avg Cost | {data['interest_summary']['Weighted_Avg_Cost']*100:.4f}% |
| Total Covenants | {len(cov_df)} |
| Compliant | {(cov_df['Status'] == 'Compliant').sum()} |
| Watch | {(cov_df['Status'] == 'Watch').sum()} |
| Near Breach | {(cov_df['Status'] == 'Near Breach').sum()} |
| Breach | {(cov_df['Status'] == 'Breach').sum()} |
""")


# ═══════════════════════════════════════════════════════════════════════
# TAB 8 — HISTORICAL SNAPSHOTS
# ═══════════════════════════════════════════════════════════════════════
def render_tab_snapshots(data: Dict[str, Any], controls: Dict[str, Any]):
    """Save and compare historical snapshots of the dashboard state."""
    from snapshots import (take_snapshot, list_snapshots, get_snapshot,
                            delete_snapshot, compare_snapshots, clear_snapshots,
                            export_snapshots_to_json, import_snapshots_from_json)
    
    fin = data["financials"][controls["basis"]]
    cov_df = recompute_covenants(data["covenants"], fin,
                                  controls["ebitda_change"], 0, controls["debt_change"])
    
    render_tab_header("SNAPSHOTS", "Historical State Tracking",
                       "Capture current state. Compare against past states to see what changed.")
    
    # ─── Take new snapshot ──────────────────────────────────────────
    st.markdown("#### 📸 Capture Current State")
    c1, c2 = st.columns([3, 1])
    with c1:
        snap_label = st.text_input("Label (optional)", "",
                                     placeholder="e.g., 'Pre-Q1 review' or 'Before refinancing'",
                                     key="snap_label_input")
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📸 Take Snapshot", use_container_width=True, type="primary"):
            snap = take_snapshot(data, cov_df, snap_label or "")
            st.success(f"✅ Captured: {snap['label']}")
            st.rerun()
    
    snaps = list_snapshots()
    
    if not snaps:
        st.markdown("<div class='callout-info'>No snapshots yet. Take one to start tracking changes.</div>",
                     unsafe_allow_html=True)
        return
    
    # ─── List existing snapshots ────────────────────────────────────
    st.markdown(f"#### 📚 Saved Snapshots ({len(snaps)})")
    
    for snap in reversed(snaps):
        with st.expander(f"📋 {snap['label']} — {snap['captured_at_pretty']}", expanded=False):
            state = snap["state"]
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Banking Exposure", f"₹{state['Total_Banking_Exposure']:,.1f} Cr")
            with c2:
                st.metric("Annual Cost", f"₹{state['Annual_Interest_Comm']:,.1f} Cr")
            with c3:
                st.metric("WAC", f"{state['Weighted_Avg_Cost']*100:.2f}%")
            with c4:
                st.metric("Compliant", f"{state['Compliant']}/{state['Total_Covenants']}")
            
            c1, c2, c3 = st.columns([1, 1, 4])
            with c1:
                if st.button("🗑️ Delete", key=f"del_{snap['id']}"):
                    delete_snapshot(snap["id"])
                    st.rerun()
    
    # ─── Compare snapshots ──────────────────────────────────────────
    if len(snaps) >= 2:
        st.markdown("---")
        st.markdown("#### 🔍 Compare Two Snapshots")
        snap_options = {s["id"]: f"{s['label']} ({s['captured_at_pretty']})" for s in snaps}
        c1, c2 = st.columns(2)
        with c1:
            sa = st.selectbox("Earlier snapshot", list(snap_options.keys()),
                              format_func=lambda x: snap_options[x],
                              index=0, key="snap_a")
        with c2:
            sb = st.selectbox("Later snapshot", list(snap_options.keys()),
                              format_func=lambda x: snap_options[x],
                              index=len(snaps)-1, key="snap_b")
        
        if sa != sb:
            snap_a = get_snapshot(sa)
            snap_b = get_snapshot(sb)
            delta = compare_snapshots(snap_a, snap_b)
            
            # Headline changes
            if delta["changed"]:
                st.markdown("##### 📈 Metric Changes")
                rows = []
                for c in sorted(delta["changed"], key=lambda x: -abs(x.get("pct_change", 0))):
                    arrow = "⬆️" if c["abs_change"] > 0 else "⬇️"
                    rows.append({
                        "Metric": c["metric"].replace("_", " "),
                        "Before": f"{c['before']:,.4f}" if c['before'] < 100 else f"{c['before']:,.2f}",
                        "After": f"{c['after']:,.4f}" if c['after'] < 100 else f"{c['after']:,.2f}",
                        "Change": f"{arrow} {c['abs_change']:+,.4f}" if abs(c['abs_change']) < 100 else f"{arrow} {c['abs_change']:+,.2f}",
                        "%": f"{c['pct_change']:+.2f}%",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.markdown("<div class='callout-good'>✅ No metric changes between these snapshots.</div>",
                             unsafe_allow_html=True)
            
            # Covenant changes
            if delta["covenant_changes"]:
                st.markdown("##### 📋 Covenant Actual Changes")
                rows = []
                for c in sorted(delta["covenant_changes"], key=lambda x: -abs(x["abs_change"])):
                    arrow = "⬆️" if c["abs_change"] > 0 else "⬇️"
                    rows.append({
                        "Lender": c["lender"],
                        "Covenant": c["covenant"],
                        "Before": f"{c['before']:.4f}",
                        "After": f"{c['after']:.4f}",
                        "Change": f"{arrow} {c['abs_change']:+.4f}",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            
            # Lender exposure changes
            if delta["exposure_changes"]:
                st.markdown("##### 🏦 Lender Exposure Changes")
                rows = []
                for c in delta["exposure_changes"]:
                    arrow = "⬆️" if c["abs_change"] > 0 else "⬇️"
                    rows.append({
                        "Lender": c["lender"],
                        "Before (₹ Cr)": f"{c['before']:,.1f}",
                        "After (₹ Cr)": f"{c['after']:,.1f}",
                        "Change": f"{arrow} ₹{c['abs_change']:+,.1f}",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Pick two different snapshots to compare.")
    
    # ─── Export / Import ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 💾 Backup Snapshots")
    st.caption("Download snapshots as JSON to keep across sessions. Re-upload to restore.")
    c1, c2, c3 = st.columns(3)
    with c1:
        js = export_snapshots_to_json()
        st.download_button(
            "📥 Download Snapshots JSON", js,
            file_name=f"jcl_snapshots_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json", use_container_width=True,
        )
    with c2:
        uploaded = st.file_uploader("📤 Restore from JSON", type=["json"],
                                     key="snap_restore", label_visibility="collapsed")
        if uploaded is not None:
            try:
                n = import_snapshots_from_json(uploaded.getvalue())
                st.success(f"✅ Restored {n} new snapshots")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")
    with c3:
        if st.button("🗑️ Clear All Snapshots", use_container_width=True):
            clear_snapshots()
            st.rerun()
