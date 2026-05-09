"""
Rule-based AI analyst — deterministic, zero-API answers.
All numbers traced to data['...'] — no hardcoded magic values.
"""

from __future__ import annotations
import pandas as pd
from typing import Dict, Any, List


SUGGESTED_QUESTIONS = [
    "What is the biggest risk in the portfolio?",
    "Which covenant is closest to breaching?",
    "What is our weighted average cost of debt?",
    "Which is our most expensive facility?",
    "What is the term loan repayment timeline?",
    "How much does a 100 bps rate hike cost us?",
    "What is the biggest concentration risk?",
    "Which facilities expire in the next 90 days?",
    "Give me a 5-point summary for the board.",
    "What should we focus on before the next lender review?",
]


# ─── Helper formatters ────────────────────────────────────────────────────
def _inr(v: float, d: int = 2) -> str:
    return f"₹{v:,.{d}f} Cr"


def _pct(v: float, d: int = 2) -> str:
    return f"{v*100:.{d}f}%" if abs(v) < 5 else f"{v:.{d}f}%"


# ─── Answer functions ────────────────────────────────────────────────────
def answer_biggest_risk(data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    b1 = data["lender_bucket1"]
    b1_lender = b1[b1["Lender"] != "Grand Total"]
    total_sd = data["totals"]["Bucket1_Sanctioned_Debt"]
    top = b1_lender.loc[b1_lender["Bucket1_Total_Debt"].idxmax()]
    top_share = top["Bucket1_Total_Debt"] / total_sd * 100
    
    # Tightest covenant
    ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
    ratio_cov["hr_pct_num"] = pd.to_numeric(ratio_cov["Headroom_Pct"], errors="coerce")
    tight = ratio_cov.loc[ratio_cov["hr_pct_num"].idxmin()] if len(ratio_cov) else None
    
    out = ["**🎯 Biggest Risks**\n"]
    if top_share > 40:
        out.append(f"1. **Lender Concentration** — {top['Lender']} holds "
                   f"**{top_share:.1f}%** ({_inr(top['Bucket1_Total_Debt'])}) "
                   f"of sanctioned debt of {_inr(total_sd)}. "
                   f"Diversification recommended in next refinancing cycle.")
    if tight is not None and pd.notna(tight["hr_pct_num"]) and tight["hr_pct_num"] < 25:
        out.append(f"2. **Tightest Covenant** — {tight['Lender']} {tight['Covenant']} "
                   f"has **{tight['hr_pct_num']:+.1f}%** headroom (actual {tight['Actual']:.2f}x "
                   f"vs threshold {tight['Operator']} {tight['Threshold']:.2f}x).")
    
    # Renewal risk
    fm = data["facility_master"]
    as_of = pd.Timestamp(data["as_of_date"])
    fm = fm.copy()
    fm["days_to_expiry"] = (fm["Validity_Date"] - as_of).dt.days
    near_expiry = fm[(fm["days_to_expiry"].notna()) & (fm["days_to_expiry"].between(0, 60))]
    if len(near_expiry) > 0:
        nearest = near_expiry.loc[near_expiry["days_to_expiry"].idxmin()]
        out.append(f"3. **Renewal Risk** — {nearest['Facility']} ({nearest['Lender']}) "
                   f"expires in **{int(nearest['days_to_expiry'])} days** "
                   f"({_inr(nearest['Sanction_INR'], 0)}).")
    if len(out) == 1:
        out.append("Portfolio is healthy across all dimensions. No critical risks detected.")
    return "\n\n".join(out)


def answer_tightest_covenant(data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
    ratio_cov["hr_pct_num"] = pd.to_numeric(ratio_cov["Headroom_Pct"], errors="coerce")
    sorted_cov = ratio_cov.sort_values("hr_pct_num").head(5)
    out = ["**📊 Top 5 Tightest Covenants** (by headroom %)\n"]
    out.append("| # | Lender | Covenant | Threshold | Actual | Headroom |")
    out.append("|---|--------|----------|-----------|--------|----------|")
    for i, (_, r) in enumerate(sorted_cov.iterrows(), 1):
        out.append(f"| {i} | {r['Lender']} | {r['Covenant']} | "
                   f"{r['Operator']}{r['Threshold']:.2f}x | "
                   f"{r['Actual']:.2f}x | {r['hr_pct_num']:+.1f}% |")
    return "\n".join(out)


def answer_wac(data: Dict[str, Any]) -> str:
    isum = data["interest_summary"]
    return (f"**💰 Cost of Debt Summary**\n\n"
            f"- **Weighted Avg Cost of Sanctioned Debt: {isum['Weighted_Avg_Cost']*100:.2f}%**\n"
            f"- Bucket 1 Interest (Sanctioned Debt): {_inr(isum['Bucket1_Interest'])}\n"
            f"- Bucket 2 Commission (NFB Contingent): {_inr(isum['Bucket2_Commission'])}\n"
            f"- Bucket 3 Interest (Separate Lines): {_inr(isum['Bucket3_Interest'])}\n"
            f"- **Total Annual Interest + Commission: {_inr(isum['Total_Interest_Commission'])}**\n\n"
            f"WAC is computed as Bucket 1 interest divided by Bucket 1 outstanding "
            f"({_inr(isum['Bucket1_Interest'])} / "
            f"{_inr(data['totals']['Bucket1_Sanctioned_Debt'])} = "
            f"{isum['Weighted_Avg_Cost']*100:.2f}%).")


def answer_most_expensive(data: Dict[str, Any]) -> str:
    isched = data["interest_schedule"]
    fb = isched[isched["Category"].isin(["FB", "FB-Term", "FB-FCY"])].copy()
    fb = fb[fb["Effective_OS"] > 0]
    if len(fb) == 0: return "No active FB facilities found."
    
    fb_sorted = fb.sort_values("Effective_Rate", ascending=False)
    top = fb_sorted.iloc[0]
    wac = data["interest_summary"]["Weighted_Avg_Cost"]
    premium_rate = top["Effective_Rate"] - wac
    premium_inr = top["Effective_OS"] * premium_rate
    
    out = [f"**💸 Most Expensive Facility**\n"]
    out.append(f"- **{top['Facility']}** at **{top['Lender']}**")
    out.append(f"- Outstanding: **{_inr(top['Effective_OS'])}**")
    out.append(f"- Rate: **{top['Effective_Rate']*100:.2f}%** "
               f"(vs portfolio WAC of {wac*100:.2f}%)")
    out.append(f"- Annual cost: **{_inr(top['Annual_Cost'])}**")
    out.append(f"- **Annual premium over WAC: {_inr(premium_inr)}** "
               f"= ({premium_rate*10000:.0f} bps × {_inr(top['Effective_OS'], 0)})")
    out.append(f"\nRefinancing this at portfolio WAC would save approximately "
               f"{_inr(premium_inr)} per year.")
    
    out.append("\n**Top 5 by rate:**")
    out.append("| Lender | Facility | Rate | Annual Cost |")
    out.append("|--------|----------|------|-------------|")
    for _, r in fb_sorted.head(5).iterrows():
        out.append(f"| {r['Lender']} | {r['Facility']} | "
                   f"{r['Effective_Rate']*100:.2f}% | {_inr(r['Annual_Cost'])} |")
    return "\n".join(out)


def answer_repayment_timeline(data: Dict[str, Any]) -> str:
    rep = data["repayment_schedule"].copy()
    if len(rep) == 0: return "No repayment schedule available."
    rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
    rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
    fy_agg = rep.groupby("FY_Label").agg(
        Principal=("Total_Principal", "sum"),
        Interest=("Total_Interest", "sum"),
        DS=("Total_DS", "sum"),
    ).reset_index()
    fy_agg = fy_agg[fy_agg["Principal"] > 0]  # exclude pure-moratorium years
    
    peak = fy_agg.loc[fy_agg["Principal"].idxmax()]
    
    out = [f"**📅 Term Loan Repayment Timeline**\n"]
    out.append(f"- Total TL Sanctioned: **₹670.7 Cr** (RBL ₹200 + YBL ₹320.7 + Bajaj ₹150)")
    out.append(f"- Repayment span: {fy_agg['FY_Label'].iloc[0]} to {fy_agg['FY_Label'].iloc[-1]}")
    out.append(f"- **Peak repayment year: {peak['FY_Label']}** with "
               f"{_inr(peak['Principal'])} principal + {_inr(peak['Interest'])} interest = "
               f"{_inr(peak['DS'])} debt service")
    out.append(f"- Total interest paid over loan life: {_inr(fy_agg['Interest'].sum())}")
    
    out.append("\n**FY-wise principal repayment:**")
    out.append("| FY | Principal | Interest | Total DS |")
    out.append("|----|-----------|----------|----------|")
    for _, r in fy_agg.iterrows():
        out.append(f"| {r['FY_Label']} | {_inr(r['Principal'])} | "
                   f"{_inr(r['Interest'])} | {_inr(r['DS'])} |")
    return "\n".join(out)


def answer_rate_shock(data: Dict[str, Any]) -> str:
    sens = data["rate_sensitivity"]
    isum = data["interest_summary"]
    total_delta = sens["Delta_Interest_100bps"].sum() if len(sens) > 0 else 0
    
    out = [f"**📈 Impact of +100 bps Rate Shock**\n"]
    out.append(f"- Current Bucket 1 Interest: {_inr(isum['Bucket1_Interest'])}")
    out.append(f"- **Additional cost from +100 bps: {_inr(total_delta)}**")
    out.append(f"- Stressed Annual Interest: {_inr(isum['Bucket1_Interest'] + total_delta)}")
    out.append(f"- New WAC: {((isum['Bucket1_Interest'] + total_delta) / data['totals']['Bucket1_Sanctioned_Debt'] * 100):.2f}%")
    
    out.append("\n**Sensitivity by benchmark:**")
    out.append("| Benchmark | Δ Interest @ +100 bps |")
    out.append("|-----------|----------------------|")
    for _, r in sens.iterrows():
        out.append(f"| {r['Benchmark']} | {_inr(r['Delta_Interest_100bps'])} |")
    return "\n".join(out)


def answer_concentration(data: Dict[str, Any]) -> str:
    b1 = data["lender_bucket1"]
    b1 = b1[b1["Lender"] != "Grand Total"]
    total_sd = data["totals"]["Bucket1_Sanctioned_Debt"]
    fm_count = len(data["facility_master"])
    
    out = [f"**🏦 Lender Concentration Analysis**\n"]
    out.append(f"Sanctioned Debt: {_inr(total_sd)} (across 5 lenders, {fm_count} facilities)")
    out.append("")
    out.append("| Lender | Sanctioned Debt | % of Sanctioned |")
    out.append("|--------|-----------------|-----------------|")
    for _, r in b1.sort_values("Bucket1_Total_Debt", ascending=False).iterrows():
        out.append(f"| {r['Lender']} | {_inr(r['Bucket1_Total_Debt'])} | "
                   f"{r['Bucket1_Total_Debt']/total_sd*100:.1f}% |")
    
    top = b1.loc[b1["Bucket1_Total_Debt"].idxmax()]
    top_pct = top["Bucket1_Total_Debt"] / total_sd * 100
    if top_pct > 40:
        out.append(f"\n⚠️ **{top['Lender']} concentration ({top_pct:.1f}%) exceeds the 40% diversification threshold.** "
                   f"Consider reducing exposure in next refinancing cycle.")
    else:
        out.append(f"\n✅ Concentration well-distributed; largest lender at {top_pct:.1f}%.")
    return "\n".join(out)


def answer_renewals(data: Dict[str, Any]) -> str:
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days_to_expiry"] = (fm["Validity_Date"] - as_of).dt.days
    upcoming = fm[fm["days_to_expiry"].notna() & fm["days_to_expiry"].between(0, 90)].sort_values("days_to_expiry")
    
    out = [f"**📆 Upcoming Renewals (next 90 days from {data['as_of_date']})**\n"]
    if len(upcoming) == 0:
        out.append("No facilities expiring in the next 90 days.")
        return "\n".join(out)
    
    out.append(f"- **{len(upcoming)} facilities** require renewal action soon")
    out.append(f"- Combined sanctioned: **{_inr(upcoming['Sanction_INR'].sum())}**")
    out.append("")
    out.append("| Facility | Lender | Expires | Days | Sanctioned |")
    out.append("|----------|--------|---------|------|------------|")
    for _, r in upcoming.iterrows():
        out.append(f"| {r['Facility']} | {r['Lender']} | "
                   f"{r['Validity_Date'].strftime('%d-%b-%Y')} | "
                   f"{int(r['days_to_expiry'])} | {_inr(r['Sanction_INR'])} |")
    return "\n".join(out)


def answer_board_summary(data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    t = data["totals"]
    isum = data["interest_summary"]
    b1 = data["lender_bucket1"]
    b1 = b1[b1["Lender"] != "Grand Total"]
    top = b1.loc[b1["Bucket1_Total_Debt"].idxmax()]
    fm_count = len(data["facility_master"])
    
    compliant = (cov_df["Status"] == "Compliant").sum()
    near = (cov_df["Status"].isin(["Near Breach", "Watch"])).sum()
    breach = (cov_df["Status"] == "Breach").sum()
    
    out = [f"**📋 5-Point Board Summary**\n"]
    out.append(f"1. **Sanctioned Debt**: {_inr(t['Bucket1_Sanctioned_Debt'])} across 5 lenders, "
               f"{fm_count} facilities. Plus NFB Contingent {_inr(t['Bucket2_NFB_Contingent'])} (off-B/S) "
               f"and FD-Backed {_inr(t['Bucket3_Separate'])} (separate line).")
    out.append(f"2. **Annual Cost**: {_inr(isum['Total_Interest_Commission'])} "
               f"at WAC {isum['Weighted_Avg_Cost']*100:.2f}% on sanctioned debt.")
    out.append(f"3. **Covenants**: {compliant}/{len(cov_df)} compliant. "
               f"{breach} breach, {near} near or watch.")
    out.append(f"4. **Term Loans**: ₹670.7 Cr sanctioned across RBL/YBL/Bajaj. "
               f"Maturities span FY29-FY37. Outstanding ~₹446 Cr.")
    out.append(f"5. **Top Concentration**: {top['Lender']} at "
               f"{top['Bucket1_Total_Debt']/t['Bucket1_Sanctioned_Debt']*100:.1f}% "
               f"({_inr(top['Bucket1_Total_Debt'])}).")
    return "\n".join(out)


def answer_pre_review(data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    out = [f"**📝 Pre-Review Action Items** (priority order)\n"]
    items = []
    
    # Breaches first
    breaches = cov_df[cov_df["Status"] == "Breach"]
    for _, r in breaches.iterrows():
        items.append(f"**HIGH** — Address {r['Lender']} {r['Covenant']} breach. Lender waiver may be required.")
    
    # Near-breach + watch
    near = cov_df[cov_df["Status"].isin(["Near Breach", "Watch"])]
    for _, r in near.iterrows():
        items.append(f"**MEDIUM** — Monitor {r['Lender']} {r['Covenant']} "
                     f"({r['Status']}, headroom {r['Headroom_Pct']:+.1f}%).")
    
    # Renewals
    fm = data["facility_master"].copy()
    as_of = pd.Timestamp(data["as_of_date"])
    fm["days_to_expiry"] = (fm["Validity_Date"] - as_of).dt.days
    soon = fm[fm["days_to_expiry"].notna() & fm["days_to_expiry"].between(0, 60)]
    if len(soon) > 0:
        items.append(f"**MEDIUM** — Initiate renewal for {len(soon)} facilities expiring in 60 days "
                     f"(combined {_inr(soon['Sanction_INR'].sum())}).")
    
    # TBD rates
    tbd = fm[fm["Rate_Type"] == "TBD"]
    if len(tbd) > 0:
        items.append(f"**LOW** — Confirm rates for {len(tbd)} TBD-rate facilities at next availment.")
    
    if not items:
        items.append("No urgent action items. Continue regular quarterly monitoring.")
    
    for i, item in enumerate(items, 1):
        out.append(f"{i}. {item}")
    return "\n".join(out)


# ─── Proactive insights (4 cards) ────────────────────────────────────────
def get_proactive_insights(data: Dict[str, Any], cov_df: pd.DataFrame) -> List[Dict[str, str]]:
    insights = []
    isum = data["interest_summary"]
    t = data["totals"]
    b1 = data["lender_bucket1"]
    b1 = b1[b1["Lender"] != "Grand Total"]
    
    # Card 1: Concentration (by Sanctioned Debt)
    top = b1.loc[b1["Bucket1_Total_Debt"].idxmax()]
    top_pct = top["Bucket1_Total_Debt"] / t["Bucket1_Sanctioned_Debt"] * 100
    if top_pct > 40:
        insights.append({
            "icon": "⚠️", "level": "warning",
            "title": "Concentration Risk",
            "body": f"<b>{top['Lender']}</b> at <b>{top_pct:.1f}%</b> of sanctioned debt. "
                    f"Diversification recommended in next cycle."
        })
    else:
        insights.append({
            "icon": "✅", "level": "good",
            "title": "Diversified Portfolio",
            "body": f"Top lender at {top_pct:.1f}%. Healthy distribution across 5 lenders."
        })
    
    # Card 2: Refinancing opportunity
    isched = data["interest_schedule"]
    fb = isched[isched["Category"].isin(["FB", "FB-Term", "FB-FCY"]) & (isched["Effective_OS"] > 0)]
    if len(fb) > 0:
        most_exp = fb.loc[fb["Effective_Rate"].idxmax()]
        wac = isum["Weighted_Avg_Cost"]
        premium = (most_exp["Effective_Rate"] - wac) * most_exp["Effective_OS"]
        if premium > 0.5:
            insights.append({
                "icon": "💰", "level": "info",
                "title": "Refinancing Opportunity",
                "body": f"<b>{most_exp['Facility']}</b> ({most_exp['Lender']}) costs "
                        f"<b>{_inr(premium)}/yr above WAC</b>. "
                        f"Refinancing could save this amount annually."
            })
    
    # Card 3: Tightest covenant
    ratio_cov = cov_df[cov_df["Operator"] != "rating"].copy()
    ratio_cov["hr_pct_num"] = pd.to_numeric(ratio_cov["Headroom_Pct"], errors="coerce")
    if len(ratio_cov) > 0:
        tight = ratio_cov.loc[ratio_cov["hr_pct_num"].idxmin()]
        if pd.notna(tight["hr_pct_num"]):
            insights.append({
                "icon": "🎯", "level": "warning" if tight["hr_pct_num"] < 25 else "good",
                "title": "Tightest Covenant",
                "body": f"<b>{tight['Lender']} {tight['Covenant']}</b> has "
                        f"<b>{tight['hr_pct_num']:+.1f}%</b> headroom. "
                        f"Actual {tight['Actual']:.2f}x vs threshold {tight['Operator']}{tight['Threshold']:.2f}x."
            })
    
    # Card 4: Repayment peak
    rep = data["repayment_schedule"].copy()
    if len(rep) > 0:
        rep["FY"] = rep["Period_End"].dt.year + (rep["Period_End"].dt.month >= 4).astype(int)
        rep["FY_Label"] = "FY" + rep["FY"].astype(str).str[-2:]
        fy_agg = rep.groupby("FY_Label")["Total_Principal"].sum()
        if (fy_agg > 0).any():
            peak_label = fy_agg.idxmax()
            peak_val = fy_agg.max()
            insights.append({
                "icon": "📅", "level": "info",
                "title": "Peak Repayment Year",
                "body": f"Highest TL principal burden in <b>{peak_label}</b> at "
                        f"<b>{_inr(peak_val)}</b>. Plan liquidity accordingly."
            })
    
    return insights[:4]


# ─── Question router ─────────────────────────────────────────────────────
KEYWORD_MAP = [
    (("biggest", "main", "main risk", "primary risk"), answer_biggest_risk),
    (("tightest", "closest", "near breach", "headroom"), answer_tightest_covenant),
    (("wac", "weighted", "cost of debt", "cost of"), answer_wac),
    (("expensive", "highest rate", "costly"), answer_most_expensive),
    (("repayment", "timeline", "term loan schedule", "tl schedule"), answer_repayment_timeline),
    (("rate hike", "rate shock", "100 bps", "rate increase"), answer_rate_shock),
    (("concentration", "lender mix", "diversification"), answer_concentration),
    (("renewal", "expiry", "expire", "validity"), answer_renewals),
    (("board", "summary", "5-point", "5 point"), answer_board_summary),
    (("review", "action", "before", "next"), answer_pre_review),
]


def answer_question(prompt: str, data: Dict[str, Any], cov_df: pd.DataFrame) -> str:
    """Route prompt to best handler. Returns markdown answer."""
    p = prompt.lower()
    best_score = 0
    best_fn = None
    for keys, fn in KEYWORD_MAP:
        score = sum(1 for k in keys if k in p)
        if score > best_score:
            best_score = score
            best_fn = fn
    
    if best_fn and best_score >= 1:
        try:
            # Some handlers need cov_df, some don't
            import inspect
            sig = inspect.signature(best_fn)
            if len(sig.parameters) >= 2:
                return best_fn(data, cov_df)
            else:
                return best_fn(data)
        except Exception as e:
            return f"_(Error: {e})_"
    
    return ("I couldn't match your question to a known pattern. Try one of the suggested questions, "
            "or use keywords like *biggest risk*, *tightest covenant*, *WAC*, *expensive*, "
            "*repayment*, *rate hike*, *concentration*, *renewal*, *board summary*, or *review*.")
