"""
Scenario engine — applies user shocks (rate, spread, EBITDA) on top of the
Excel base values to recompute covenants and interest dynamically.

Excel ground-truth scenario outputs (from Scenario Analysis tab):
  Stress (+100bps, +25bps spread, +10% util, -15% EBITDA, +10% debt):
    Annual B1 Interest: ₹50.89 Cr
    DSCR: 2.79x
  Severe (+200bps, +50bps spread, +20% util, -30% EBITDA, +25% debt):
    Annual B1 Interest: ₹62.96 Cr
    DSCR: 1.92x

This module replicates those outputs exactly for slider-driven what-if analysis.
"""

from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Optional


# Rating ordinal map (higher = better)
RATING_ORDINALS = {
    "AAA": 21, "AA+": 20, "AA": 19, "AA-": 18,
    "A+": 17, "A": 16, "A-": 15,
    "BBB+": 14, "BBB": 13, "BBB-": 12,
    "BB+": 11, "BB": 10, "BB-": 9,
    "B+": 8, "B": 7, "B-": 6,
    "CCC+": 5, "CCC": 4, "CCC-": 3, "CC": 2, "C": 1, "D": 0,
}


def rating_to_ordinal(rating_str: Any) -> int:
    """Parse rating string → ordinal. Higher = better."""
    if rating_str is None:
        return 0
    s = str(rating_str).upper()
    # Try longest match first
    for tier in sorted(RATING_ORDINALS.keys(), key=lambda x: -len(x)):
        if tier in s:
            return RATING_ORDINALS[tier]
    return 0


def calculate_dscr(financials: Dict[str, float], ebitda_change_pct: float = 0,
                   interest_change_pct: float = 0, debt_repay_change_pct: float = 0) -> float:
    """DSCR = (EBITDA - Tax) / (Sched_Repay + Interest). Excel formula."""
    ebitda = financials["EBITDA"] * (1 + ebitda_change_pct / 100)
    tax = financials.get("Tax Paid", 0)
    sched = financials.get("Sched TL Repay", 0) * (1 + debt_repay_change_pct / 100)
    interest = financials.get("Interest Expense", 0) * (1 + interest_change_pct / 100)
    denom = sched + interest
    if denom <= 0: return 999.0
    return (ebitda - tax) / denom


def calculate_all_ratios(financials: Dict[str, float],
                         ebitda_change_pct: float = 0,
                         interest_change_pct: float = 0,
                         debt_change_pct: float = 0) -> Dict[str, float]:
    """Return all 9 ratios used across covenants. Apply shocks if requested."""
    ebitda = financials["EBITDA"] * (1 + ebitda_change_pct / 100)
    interest = financials["Interest Expense"] * (1 + interest_change_pct / 100)
    total_debt = financials["Total Debt"] * (1 + debt_change_pct / 100)
    term_debt = financials["Term Debt"] * (1 + debt_change_pct / 100)
    tnw = financials["TNW"]
    atnw = financials.get("ATNW", tnw)
    ca = financials["Current Assets"]
    cl = financials["Current Liabilities"]
    tol = financials["TOL"]
    fa = financials["Fixed Assets"]
    tax = financials.get("Tax Paid", 0)
    sched = financials.get("Sched TL Repay", 0)
    
    return {
        "DSCR": (ebitda - tax) / (sched + interest) if (sched + interest) > 0 else 999.0,
        "Total Debt / EBITDA": total_debt / ebitda if ebitda > 0 else 999.0,
        "Term Debt / EBITDA": term_debt / ebitda if ebitda > 0 else 999.0,
        "TOL / TNW": tol / tnw if tnw > 0 else 999.0,
        "TOL / ATNW": tol / atnw if atnw > 0 else 999.0,
        "Total Debt / ATNW": total_debt / atnw if atnw > 0 else 999.0,
        "ICR": ebitda / interest if interest > 0 else 999.0,
        "Current Ratio": ca / cl if cl > 0 else 999.0,
        "FACR": fa / term_debt if term_debt > 0 else 999.0,
        "FACR (MSC 1.25x)": fa / term_debt if term_debt > 0 else 999.0,
        "Debt / Equity": total_debt / tnw if tnw > 0 else 999.0,
        "Promoter Shareholding": financials.get("Promoter Shareholding", 1.0),
    }


def evaluate_status(actual: float, operator: str, threshold: float) -> str:
    """Apply Excel covenant status logic."""
    if pd.isna(actual) or actual is None:
        return "Pending"
    op = operator.strip()
    try:
        a = float(actual); t = float(threshold)
    except (TypeError, ValueError):
        return "Pending"

    if op in (">", ">="):
        if (op == ">" and a <= t) or (op == ">=" and a < t):
            return "Breach"
        # headroom: how far above threshold
        hr_pct = ((a - t) / t * 100) if t > 0 else 100
        if hr_pct < 5: return "Near Breach"
        if hr_pct < 10: return "Watch"
        return "Compliant"
    elif op in ("<", "<="):
        if (op == "<" and a >= t) or (op == "<=" and a > t):
            return "Breach"
        hr_pct = ((t - a) / t * 100) if t > 0 else 100
        if hr_pct < 5: return "Near Breach"
        if hr_pct < 10: return "Watch"
        return "Compliant"
    return "Pending"


def recompute_covenants(base_covenants: pd.DataFrame, financials: Dict[str, float],
                        ebitda_change_pct: float = 0,
                        interest_change_pct: float = 0,
                        debt_change_pct: float = 0) -> pd.DataFrame:
    """Apply shocks to financials and recompute every covenant's actual + status.
    
    base_covenants: from data['covenants'] — provides lender, name, operator, threshold.
    Returns: a new DataFrame with recomputed Actual, Headroom, Headroom_Pct, Status.
    """
    ratios = calculate_all_ratios(financials, ebitda_change_pct, interest_change_pct, debt_change_pct)
    rating_str = financials.get("External Rating", "")
    rating_ord = rating_to_ordinal(rating_str)
    
    rows = []
    for _, c in base_covenants.iterrows():
        name = c["Covenant"]
        op = c["Operator"]
        thr = c["Threshold"]
        
        # Map covenant name to ratio
        if op == "rating":
            actual = rating_str
            try:
                thr_ord = rating_to_ordinal(thr)
                ok = rating_ord >= thr_ord
                status = "Compliant" if ok else "Breach"
                headroom = rating_ord - thr_ord
                hr_pct = None
            except Exception:
                status = "Pending"; headroom = None; hr_pct = None
        else:
            actual = ratios.get(name)
            if actual is None:
                # Try fuzzy match for variant names
                for k, v in ratios.items():
                    if name.split("(")[0].strip() == k.split("(")[0].strip():
                        actual = v
                        break
            if actual is None:
                status = "Pending"; headroom = None; hr_pct = None
            else:
                status = evaluate_status(actual, op, thr)
                if op in (">", ">="):
                    headroom = actual - thr
                    hr_pct = (headroom / thr * 100) if thr > 0 else 0
                elif op in ("<", "<="):
                    headroom = thr - actual
                    hr_pct = (headroom / thr * 100) if thr > 0 else 0
                else:
                    headroom = None; hr_pct = None
        
        rows.append({
            "Lender": c["Lender"], "Covenant": name, "Operator": op,
            "Threshold": thr, "Actual": actual, "Headroom": headroom,
            "Headroom_Pct": hr_pct, "Status": status,
        })
    return pd.DataFrame(rows)


def recompute_interest(facility_master: pd.DataFrame, benchmark_rates: Dict[str, float],
                       rate_shock_bps: float = 0, spread_shock_bps: float = 0,
                       util_change_pct: float = 0) -> Dict[str, Any]:
    """
    Apply rate/spread/utilisation shocks and recompute annual cost per facility.
    Returns same structure as Excel Interest Schedule.

    Excel parity: matches Scenario Analysis E12 formula
        SUMPRODUCT((Bucket=1) * EffOS * (1 + UtilChange) * (Rate + RateShock + SpreadShock))
    Utilisation factor is applied ONLY to Bucket 1 (drawable FB economic debt). It does not
    apply to Bucket 2 NFB commitments (priced on sanctioned face, not on drawn balance) nor
    to Bucket 3 FDOD (already at 100% utilisation by structure).
    """
    rate_shock = rate_shock_bps / 10000
    spread_shock = spread_shock_bps / 10000
    util_factor = 1.0 + (util_change_pct / 100.0)
    rows = []
    bucket1_int = 0.0; bucket2_comm = 0.0; bucket3_int = 0.0
    
    for _, r in facility_master.iterrows():
        eff_os = r.get("Effective_OS", 0)
        base_rate = r.get("Effective_Rate", 0)
        category = r.get("Category", "")
        bucket = int(r.get("Bucket", 0))
        rate_type = str(r.get("Rate_Type", ""))
        
        # Apply shock only to floating-rate facilities
        if "Floating" in rate_type:
            shocked_rate = base_rate + rate_shock + spread_shock
        else:
            shocked_rate = base_rate
        
        # Bucket aggregation (matches Excel Interest Summary / Scenario Analysis logic)
        # Bucket 1 = FB Sanctioned Debt: TL + WC FB. Utilisation factor applies here.
        if bucket == 1 and category in ("FB", "FB-Term", "FB-FCY"):
            stressed_os = eff_os * util_factor
            annual_cost = stressed_os * shocked_rate
            bucket1_int += annual_cost
        # Bucket 2 = NFB Contingent (parent only). Commission on sanctioned face — no util.
        elif bucket == 2 and category == "NFB":
            stressed_os = eff_os
            annual_cost = stressed_os * shocked_rate
            bucket2_comm += annual_cost
        # Bucket 3 = FD-backed FB. Already at 100% utilisation by structure — no util factor.
        elif bucket == 3 and category in ("FB-FDbacked",):
            stressed_os = eff_os
            annual_cost = stressed_os * shocked_rate
            bucket3_int += annual_cost
        else:
            stressed_os = eff_os
            annual_cost = stressed_os * shocked_rate
        # Sub-limits in bucket 0 — count their commission but tag separately

        rows.append({
            "S_No": r["S_No"], "Lender": r["Lender"], "Facility": r["Facility"],
            "Category": category, "Bucket": bucket,
            "Effective_OS": eff_os, "Stressed_OS": stressed_os,
            "Base_Rate": base_rate,
            "Shocked_Rate": shocked_rate, "Annual_Cost": annual_cost,
        })
    
    total = bucket1_int + bucket2_comm + bucket3_int
    
    # WAC of FB Economic Debt: blended rate = stressed B1 interest / stressed B1 outstanding.
    # Both numerator and denominator carry the same util factor, so WAC isolates the rate
    # impact (rate shock × spread shock) and is independent of utilisation by construction.
    b1_os_base = facility_master[
        (facility_master["Bucket"] == 1) &
        (facility_master["Category"].isin(["FB", "FB-Term", "FB-FCY"]))
    ]["Effective_OS"].sum()
    b1_os_stressed = b1_os_base * util_factor
    wac = (bucket1_int / b1_os_stressed) if b1_os_stressed > 0 else 0

    return {
        "facility_breakdown": pd.DataFrame(rows),
        "Bucket1_Interest": bucket1_int,
        "Bucket2_Commission": bucket2_comm,
        "Bucket3_Interest": bucket3_int,
        "Total": total,
        "Weighted_Avg_Cost": wac,
        "Bucket1_OS_Base": b1_os_base,
        "Bucket1_OS_Stressed": b1_os_stressed,
    }


def run_scenario(data: Dict[str, Any], rate_shock_bps: float, spread_shock_bps: float,
                 ebitda_change_pct: float, debt_change_pct: float = 0,
                 basis: str = "FY26E", util_change_pct: float = 0) -> Dict[str, Any]:
    """Full scenario run — returns base + stressed metrics.

    Mirrors Excel Scenario Analysis tab: rate_shock + spread_shock + util_change drive
    the Bucket-1 interest line; ebitda_change and debt_change drive the covenant ratios.
    """
    fin = data["financials"][basis]
    base_int = recompute_interest(data["facility_master"], data["benchmark_rates"], 0, 0, 0)
    base_cov = recompute_covenants(data["covenants"], fin, 0, 0, 0)

    # Compute interest change pct from rate + spread + util shocks combined
    if base_int["Bucket1_Interest"] > 0:
        stress_int = recompute_interest(data["facility_master"], data["benchmark_rates"],
                                        rate_shock_bps, spread_shock_bps, util_change_pct)
        int_change_pct = (stress_int["Bucket1_Interest"] / base_int["Bucket1_Interest"] - 1) * 100
    else:
        stress_int = base_int; int_change_pct = 0
    
    stress_cov = recompute_covenants(data["covenants"], fin, ebitda_change_pct, int_change_pct, debt_change_pct)
    
    return {
        "base": {
            "interest": base_int,
            "covenants": base_cov,
        },
        "stress": {
            "interest": stress_int,
            "covenants": stress_cov,
        },
        "delta": {
            "annual_interest": stress_int["Total"] - base_int["Total"],
            "wac_bps": (stress_int["Weighted_Avg_Cost"] - base_int["Weighted_Avg_Cost"]) * 10000,
        },
    }
