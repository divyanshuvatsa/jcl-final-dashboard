"""
Excel reader — JCL_Debt_Model_Final.xlsx is the single source of truth.

Reads pre-computed values from the Excel:
  - Effective Outstanding (col "Eff Current O/S") — Excel handles cap allocation, sub-limits, USD INR caps
  - Effective Rate p.a. (col "Eff Rate p.a.") — Excel handles benchmark + spread
  - Covenant actuals & status — read directly from Covenant Tracker
  - Lender Summary three-bucket totals — read from Lender Summary tab
  - Repayment Schedule — read quarterly schedule
  - Interest Schedule — read per-facility annual cost

This loader is structured to be backward-compatible with the rest of the
dashboard codebase: it preserves all the output dict keys and DataFrame
column names that downstream modules (dashboard_ui, visualizations, gemini_ai,
rule_based_ai, pdf_export, scenario_engine) consume — even when the underlying
Excel layout has been restructured.

Falls back to recomputation only if Excel cells are blank.
"""

from __future__ import annotations
import hashlib  # kept for future use
import os
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import warnings

import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


# ─── PATH RESOLUTION ───────────────────────────────────────────────────────
def get_excel_path() -> Path:
    """Find the JCL Excel file. Checks env var, project root, and common locations."""
    candidates = []
    env_path = os.environ.get("JCL_EXCEL_PATH")
    if env_path:
        candidates.append(Path(env_path))
    here = Path(__file__).parent
    candidates.extend([
        here / "JCL_Debt_Model_Final.xlsx",
        Path.cwd() / "JCL_Debt_Model_Final.xlsx",
        Path("/mnt/user-data/uploads/JCL_Debt_Model_Final.xlsx"),
    ])
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # for error reporting


def _excel_engine() -> str:
    """Pick the fastest available Excel engine. Calamine is ~8x faster than openpyxl."""
    try:
        import python_calamine  # noqa: F401
        return "calamine"
    except ImportError:
        return "openpyxl"


_EXCEL_ENGINE = _excel_engine()


def file_signature(path: Path) -> str:
    """Cheap composite signature: mtime + size. No MD5 cost."""
    if not path.exists():
        return "missing"
    stat = path.stat()
    return f"{int(stat.st_mtime)}_{stat.st_size}"


def file_mtime_pretty(path: Path) -> str:
    if not path.exists():
        return "FILE NOT FOUND"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d-%b-%Y %H:%M:%S")


def _safe_float(v, default=0.0) -> float:
    """Coerce to float; handle bool/string edge cases (e.g. row 35 'Promoter %' = 'True')."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes"):
            return 1.0
        if s in ("false", "no"):
            return 0.0
        try:
            return float(s)
        except (ValueError, TypeError):
            return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ─── EXCEL PARSING ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading JCL Excel...")
def load_excel(signature: str, path_str: str) -> Dict[str, Any]:
    """
    Read every relevant section of the Excel.
    The signature parameter is the cache key — changes when file changes.
    """
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Excel not found at {path}. Place "
                                f"JCL_Debt_Model_Final.xlsx in the project root.")

    out: Dict[str, Any] = {}

    # ─── Instructions tab — parameters, benchmarks, financials, caps ───
    ins = pd.read_excel(path, sheet_name="Instructions & Assumptions",
                        header=None, engine=_EXCEL_ENGINE)

    # Section A: parameters (rows 3-7 in 0-index)
    out["as_of_date"] = pd.Timestamp(ins.iloc[3, 1]).date()
    out["fx_rate"] = _safe_float(ins.iloc[4, 1], 92.98)
    out["use_full_util"] = bool(ins.iloc[5, 1]) if pd.notna(ins.iloc[5, 1]) else True
    out["days_in_year"] = int(_safe_float(ins.iloc[6, 1], 365))
    out["financial_basis"] = str(ins.iloc[7, 1]) if pd.notna(ins.iloc[7, 1]) else "Projected"

    # Section B: benchmark rates (rows 11-19)
    benchmark_label_to_key = {
        "1Y MCLR (RBL Bank)": "RBL 1Y MCLR",
        "3M MCLR (YBL)": "YBL 3M MCLR",
        "6M I-MCLR (ICICI)": "ICICI 6M I-MCLR",
        "12M MCLR (SIB)": "SIB 12M MCLR",
        "Bajaj Floating Reference Rate (BFRR)": "Bajaj BFRR",
        "Term SOFR (USD) 3M": "Term SOFR (USD)",
        "3M T-Bill": "3M T-Bill",
        "Repo Rate": "Repo Rate",
        "FD rate (RBL FDOD)": "FD Rate (RBL FDOD)",
    }
    out["benchmark_rates"] = {}
    for i in range(10, 25):
        try:
            label = ins.iloc[i, 0]
            val = ins.iloc[i, 1]
            if pd.notna(label) and pd.notna(val) and isinstance(val, (int, float)):
                key = benchmark_label_to_key.get(str(label).strip())
                if key:
                    out["benchmark_rates"][key] = float(val)
        except Exception:
            continue

    # Section C: financials (rows 23-38)
    fin_label_map = {
        "EBITDA": "EBITDA",
        "Total Debt (Gross)": "Total Debt",
        "Term Debt": "Term Debt",
        "Tangible Net Worth (TNW)": "TNW",
        "Adjusted TNW (ATNW)": "ATNW",
        "Current Assets": "Current Assets",
        "Current Liabilities": "Current Liabilities",
        "Total Outside Liabilities (TOL)": "TOL",
        "Interest Expense (TTM)": "Interest Expense",
        "Fixed Assets (net block)": "Fixed Assets",
        "Secured Debt (outstanding)": "Secured Debt",
        "External Rating": "External Rating",
        "Promoter Shareholding %": "Promoter Shareholding",
        "Principal Repayment (TTM)": "Principal Repayment TTM",
        "Tax Paid (TTM)": "Tax Paid",
        "Scheduled TL Repayment (next 12M)": "Sched TL Repay",
    }
    out["financials"] = {"FY24A": {}, "FY26E": {}, "Active": {}}
    for i in range(22, 42):
        try:
            label = ins.iloc[i, 0]
            if pd.isna(label):
                continue
            key = fin_label_map.get(str(label).strip())
            if not key:
                continue
            active_v = ins.iloc[i, 1]
            fy24_v = ins.iloc[i, 2]
            fy26_v = ins.iloc[i, 3]
            for tag, val in [("Active", active_v), ("FY24A", fy24_v), ("FY26E", fy26_v)]:
                if pd.notna(val):
                    if key == "External Rating":
                        out["financials"][tag][key] = str(val)
                    else:
                        # Promoter Shareholding "Active" col may show "True"; coerce safely
                        out["financials"][tag][key] = _safe_float(val)
        except Exception:
            continue

    # Section D: sanction-letter caps (rows 41-49)
    out["caps"] = {}
    for i in range(40, 50):
        try:
            label = ins.iloc[i, 0]
            val = ins.iloc[i, 1]
            if pd.notna(label) and pd.notna(val) and isinstance(val, (int, float)):
                out["caps"][str(label).strip()] = float(val)
        except Exception:
            continue

    # ─── Facility Master ─────────────────────────────────────
    fm_raw = pd.read_excel(path, sheet_name="Facility Master", header=3, engine=_EXCEL_ENGINE)
    # Filter rows where S.No is numeric
    fm_raw = fm_raw[pd.to_numeric(fm_raw["S.No"], errors="coerce").notna()].copy()
    fm_raw["S.No"] = fm_raw["S.No"].astype(int)

    # Helper: support both old ("Effective O/S") and new ("Eff Current O/S") column names
    def _fm_get(r, *candidates, default=None):
        for c in candidates:
            if c in r.index and pd.notna(r[c]):
                return r[c]
        return default

    fm_records = []
    for _, r in fm_raw.iterrows():
        eff_os_val = _fm_get(r, "Eff Current O/S", "Effective O/S", default=0.0)
        rec = {
            "S_No": int(r["S.No"]),
            "Lender": str(r["Lender"]),
            "Facility": str(r["Facility"]),
            "Category": str(r["Category"]),
            "Nature": str(r["Nature"]),
            "Sub_Limit_Flag": bool(r["Sub-Limit Flag"]) if pd.notna(r["Sub-Limit Flag"]) else False,
            # WC Cap Group / Amount removed in V19 model — always None
            "WC_Cap_Group": None,
            "WC_Cap_Amount": None,
            "FD_Backed": bool(r["FD-Backed"]) if pd.notna(r["FD-Backed"]) else False,
            # New flag for NFB Contingent classification (RBL SBLC for BC, RBL Capex LC)
            "NFB_Contingent_Flag": bool(_fm_get(r, "NFB Contingent Flag", default=False)),
            "Bucket": int(r["Bucket"]) if pd.notna(r["Bucket"]) else 0,
            "Currency": str(r["Currency"]),
            "Sanc_Orig_Ccy": _safe_float(r["Sanc Orig Ccy"]),
            "Sanction_INR": _safe_float(r["Sanc INR Cr"]),
            "Current_OS": _safe_float(r["Current O/S"]),
            "Effective_OS": _safe_float(eff_os_val),
            "Util_Pct": _safe_float(r["Util %"]),
            "Headroom": _safe_float(r["Headroom"]),
            "Benchmark": str(r["Benchmark"]) if pd.notna(r["Benchmark"]) else "",
            "Spread_BPS": _safe_float(r["Spread"]) * 10000,
            "Effective_Rate": _safe_float(r["Eff Rate p.a."]),
            "Rate_Type": str(r["Rate Type"]) if pd.notna(r["Rate Type"]) else "",
            "Moratorium_Months": int(_safe_float(r["Moratorium Mths"])),
            "Repayment_Frequency": str(r["Rep Frequency"]) if pd.notna(r["Rep Frequency"]) else "",
            "Tenor_Months": int(_safe_float(r["Tenor Mths"])),
            "Num_Instalments": int(_safe_float(r["No of Instalments"])),
            "Drawdown_Date": pd.Timestamp(r["Drawdown Date"]) if pd.notna(r["Drawdown Date"]) else pd.NaT,
            "Rep_Start_Date": pd.Timestamp(r["Rep Start Date"]) if pd.notna(r["Rep Start Date"]) else pd.NaT,
            "Maturity_Date": pd.Timestamp(r["Maturity Date"]) if pd.notna(r["Maturity Date"]) else pd.NaT,
            "Sanction_Date": pd.Timestamp(r["Sanction Date"]) if pd.notna(r["Sanction Date"]) else pd.NaT,
            "Validity_Date": pd.Timestamp(r["Validity Date"]) if pd.notna(r["Validity Date"]) else pd.NaT,
            "Purpose": str(r["Purpose"]) if pd.notna(r["Purpose"]) else "",
            "Security_Summary": str(r["Security Summary"]) if pd.notna(r["Security Summary"]) else "",
            "Sanction_Reference": str(r["Sanction Reference"]) if pd.notna(r["Sanction Reference"]) else "",
            "Remarks": str(r["Remarks"]) if pd.notna(r["Remarks"]) else "",
        }
        fm_records.append(rec)
    out["facility_master"] = pd.DataFrame(fm_records)

    # ─── Covenant Tracker ──────────────────────────────────
    cov_raw = pd.read_excel(path, sheet_name="Covenant Tracker", header=2, engine=_EXCEL_ENGINE)
    cov_records = []
    for _, r in cov_raw.iterrows():
        if pd.isna(r.get("Lender")) or pd.isna(r.get("Covenant")):
            continue
        if str(r["Lender"]).startswith(("Covenant", "Total", "Compliant", "Near", "Breached", "Pending", "Portfolio")):
            continue
        cov_records.append({
            "Lender": str(r["Lender"]),
            "Covenant": str(r["Covenant"]),
            "Operator": str(r["Operator"]),
            "Threshold": r["Threshold"] if pd.notna(r["Threshold"]) else None,
            "Actual": r["Actual"] if pd.notna(r["Actual"]) else None,
            "Headroom": r["Headroom"] if pd.notna(r["Headroom"]) else None,
            "Status": str(r["Status"]) if pd.notna(r["Status"]) else "Pending",
        })
    out["covenants"] = pd.DataFrame(cov_records)

    # ─── Lender Summary (three-bucket) ─────────────────────
    # NEW LAYOUT (validated Excel V19):
    #   Row 3 header:  Lender | Bucket 1: FB Mains | Bucket 2: NFB Mains | Sanctioned Debt | %
    #   Rows 4-8:      per-lender rows
    #   Row 9:         Grand Total | 720.7 | 600 | 1320.7 | 100%
    #   Row 13 header: Lender | NFB Mains (B2) | NFB sub of FB-Main | Total NFB Contingent | %
    #   Rows 14-18:    per-lender NFB Contingent rows
    #   Row 19:        Grand Total | 600 | 215 | 815 | 100%
    #   Row 23 header: Lender | FD-Backed | % Share
    #   Rows 24-28:    per-lender FD rows
    #   Row 29:        Grand Total | 100 | 100%
    #   Rows 33-36:    Memo Hedge Notional table (RBL LER 20, SIB Forward 3 = 23)
    ls_raw = pd.read_excel(path, sheet_name="Lender Summary", header=None, engine=_EXCEL_ENGINE)

    # Read Bucket 1 lender rows (4-8): FB Mains | NFB Mains | Sanctioned Debt | %
    bucket1_data = {}     # lender → dict
    for i in range(4, 9):
        if pd.notna(ls_raw.iloc[i, 0]):
            lender = str(ls_raw.iloc[i, 0])
            bucket1_data[lender] = {
                "FB_Mains": _safe_float(ls_raw.iloc[i, 1]),
                "NFB_Mains_B2": _safe_float(ls_raw.iloc[i, 2]),
                "Sanctioned_Debt": _safe_float(ls_raw.iloc[i, 3]),
                "Pct_Sanctioned": _safe_float(ls_raw.iloc[i, 4]),
            }

    # Read NFB Contingent lender rows (14-18): NFB Mains (B2) | sub of FB | Total | %
    nfb_data = {}
    for i in range(14, 19):
        if pd.notna(ls_raw.iloc[i, 0]):
            lender = str(ls_raw.iloc[i, 0])
            nfb_data[lender] = {
                "NFB_Mains_B2": _safe_float(ls_raw.iloc[i, 1]),
                "NFB_Sub_of_FB": _safe_float(ls_raw.iloc[i, 2]),
                "Total_NFB_Contingent": _safe_float(ls_raw.iloc[i, 3]),
                "Pct_NFB": _safe_float(ls_raw.iloc[i, 4]),
            }

    # Read FD-Backed lender rows (24-28): FD-Backed | % Share
    fd_data = {}
    for i in range(24, 29):
        if pd.notna(ls_raw.iloc[i, 0]):
            lender = str(ls_raw.iloc[i, 0])
            fd_data[lender] = {
                "FD_Backed": _safe_float(ls_raw.iloc[i, 1]),
                "Pct_FD": _safe_float(ls_raw.iloc[i, 2]),
            }

    # Hedge notional memo table (rows 34-35)
    hedge_data = {}
    for i in range(33, 38):
        try:
            lender_v = ls_raw.iloc[i, 0]
            facility_v = ls_raw.iloc[i, 1]
            notional_v = ls_raw.iloc[i, 2]
            if (pd.notna(lender_v) and pd.notna(notional_v)
                and not str(lender_v).startswith(("Total", "Hedge", "Lender"))):
                lender = str(lender_v)
                hedge_data[lender] = hedge_data.get(lender, 0.0) + _safe_float(notional_v)
        except Exception:
            continue

    # Compute TL_Sanctioned per lender from Facility Master
    fm_df = out["facility_master"]
    tl_per_lender = (
        fm_df[fm_df["Category"] == "FB-Term"]
        .groupby("Lender")["Sanction_INR"].sum().to_dict()
    )

    # Build Bucket 1 DataFrame (preserves OLD output keys for downstream compatibility)
    # OLD keys: TL_Sanctioned, WC_FB_Cap, Bucket1_Total_Debt
    bucket1_records = []
    for lender, b1 in bucket1_data.items():
        tl_sanc = float(tl_per_lender.get(lender, 0.0))
        fb_mains = b1["FB_Mains"]
        wc_fb_cap = max(0.0, fb_mains - tl_sanc)
        # NOTE: Bucket1_Total_Debt under the new model = Sanctioned Debt (FB Mains + NFB Mains B2)
        # This matches the dashboard's semantic of "Sanctioned Debt"
        bucket1_records.append({
            "Lender": lender,
            "TL_Sanctioned": tl_sanc,
            "WC_FB_Cap": wc_fb_cap,
            "Bucket1_Total_Debt": b1["Sanctioned_Debt"],
        })
    out["lender_bucket1"] = pd.DataFrame(bucket1_records)

    # Build Bucket 2 DataFrame
    # OLD keys: LCs, SBLCs, BGs_memo, Capex_LCs, Bucket2_Total_NFB
    # NEW model semantics:
    #   LCs           = NFB Mains (Bucket 2 parent LCs)
    #   Capex_LCs     = NFB sub of FB-Main (RBL SBLC for BC ₹190 + RBL Capex LC ₹25 = 215 for RBL)
    #   SBLCs/BGs_memo = 0 (consolidated into LCs in the new model's NFB Mains line)
    #   Bucket2_Total_NFB = Total NFB Contingent
    bucket2_records = []
    for lender, b2 in nfb_data.items():
        bucket2_records.append({
            "Lender": lender,
            "LCs": b2["NFB_Mains_B2"],
            "SBLCs": 0.0,
            "BGs_memo": 0.0,
            "Capex_LCs": b2["NFB_Sub_of_FB"],
            "Bucket2_Total_NFB": b2["Total_NFB_Contingent"],
        })
    out["lender_bucket2"] = pd.DataFrame(bucket2_records)

    # Build Bucket 3 DataFrame
    # OLD keys: FD_Backed, Hedge_Notional, Bucket3_Total
    bucket3_records = []
    for lender, b3 in fd_data.items():
        hedge = float(hedge_data.get(lender, 0.0))
        bucket3_records.append({
            "Lender": lender,
            "FD_Backed": b3["FD_Backed"],
            "Hedge_Notional": hedge,
            "Bucket3_Total": b3["FD_Backed"],  # FD-Backed is the headline; hedge tracked separately
        })
    out["lender_bucket3"] = pd.DataFrame(bucket3_records)

    # ─── Lender Concentration (computed — not present in new Excel layout) ───
    # Provides per-lender Sanctioned Debt for the donut chart.
    # NOTE: 'Banking Exposure' concept (B1+B2+B3 sum = ₹2,235.7) was removed from the
    # dashboard at user request. This DataFrame retains only Sanctioned Debt fields.
    sanc_total = sum(b["Sanctioned_Debt"] for b in bucket1_data.values()) or 1.0
    concentration_records = []
    for lender in bucket1_data:
        concentration_records.append({
            "Lender": lender,
            "Sanctioned_Debt": bucket1_data[lender]["Sanctioned_Debt"],
            "Pct_Sanctioned_Debt": bucket1_data[lender]["Sanctioned_Debt"] / sanc_total,
        })
    out["lender_concentration"] = pd.DataFrame(concentration_records)

    # ─── Headline totals ────────────────────────────────────
    # In the new model:
    #   Bucket1_Sanctioned_Debt → Sanctioned Debt KPI = B1 + B2 = ₹1,320.7 (row 9 col 3)
    #   Bucket2_NFB_Contingent  → NFB Contingent total = ₹815 (row 19 col 3)
    #   Bucket3_Separate        → FD-Backed total = ₹100 (row 29 col 1)
    out["totals"] = {
        "Bucket1_Sanctioned_Debt": _safe_float(ls_raw.iloc[9, 3], default=sum(b["Sanctioned_Debt"] for b in bucket1_data.values())),
        "Bucket2_NFB_Contingent": _safe_float(ls_raw.iloc[19, 3], default=sum(n["Total_NFB_Contingent"] for n in nfb_data.values())),
        "Bucket3_Separate": _safe_float(ls_raw.iloc[29, 1], default=sum(f["FD_Backed"] for f in fd_data.values())),
    }

    # ─── Interest Schedule ─────────────────────────────────
    int_raw = pd.read_excel(path, sheet_name="Interest Schedule", header=2, engine=_EXCEL_ENGINE)
    int_records = []
    for _, r in int_raw.iterrows():
        sno = pd.to_numeric(r.get("S.No"), errors="coerce")
        if pd.isna(sno):
            continue
        int_records.append({
            "S_No": int(sno),
            "Lender": str(r["Lender"]),
            "Facility": str(r["Facility"]),
            "Category": str(r["Category"]),
            "Bucket": int(r["Bucket"]) if pd.notna(r["Bucket"]) else 0,
            "Sanction_INR": _safe_float(r["Sanc INR Cr"]),
            "Effective_OS": _safe_float(r["Eff O/S"]),
            "Effective_Rate": _safe_float(r["Eff Rate"]),
            "Annual_Cost": _safe_float(r["Annual Interest/Comm. ₹Cr"]),
        })
    out["interest_schedule"] = pd.DataFrame(int_records)

    # Interest summary (rows 39-43 in 0-index, col 8)
    int_summary_raw = pd.read_excel(path, sheet_name="Interest Schedule",
                                    header=None, engine=_EXCEL_ENGINE)
    out["interest_summary"] = {
        "Bucket1_Interest": _safe_float(int_summary_raw.iloc[39, 8]),
        "Bucket2_Commission": _safe_float(int_summary_raw.iloc[40, 8]),
        "Bucket3_Interest": _safe_float(int_summary_raw.iloc[41, 8]),
        "Total_Interest_Commission": _safe_float(int_summary_raw.iloc[42, 8]),
        "Weighted_Avg_Cost": _safe_float(int_summary_raw.iloc[43, 8]),
    }

    # ─── Repayment Schedule ────────────────────────────────
    rep_raw = pd.read_excel(path, sheet_name="Repayment Schedule",
                            header=None, engine=_EXCEL_ENGINE)
    rep_records = []
    for i in range(4, len(rep_raw)):
        period_end = rep_raw.iloc[i, 1]
        label = rep_raw.iloc[i, 2]
        if pd.isna(period_end):
            continue
        # Trailing summary rows (e.g. "RBL Bank (excluded)", "YES Bank", "Total") have a
        # text/numeric value in col 1 instead of a real date — skip them. Only accept
        # values that pandas already recognises as datetime-like.
        if not isinstance(period_end, (pd.Timestamp, datetime)):
            continue
        # Skip the trailing GRAND TOTAL row
        if str(label).strip().upper().startswith("GRAND TOTAL"):
            continue
        try:
            rec = {
                "Period_End": pd.Timestamp(period_end),
                "Period_Label": str(label) if pd.notna(label) else "",
                "RBL_Opening": _safe_float(rep_raw.iloc[i, 3]),
                "RBL_Drawdown": _safe_float(rep_raw.iloc[i, 4]),
                "RBL_Principal": _safe_float(rep_raw.iloc[i, 5]),
                "RBL_Interest": _safe_float(rep_raw.iloc[i, 6]),
                "RBL_Closing": _safe_float(rep_raw.iloc[i, 7]),
                "YBL_Opening": _safe_float(rep_raw.iloc[i, 8]),
                "YBL_Drawdown": _safe_float(rep_raw.iloc[i, 9]),
                "YBL_Principal": _safe_float(rep_raw.iloc[i, 10]),
                "YBL_Interest": _safe_float(rep_raw.iloc[i, 11]),
                "YBL_Closing": _safe_float(rep_raw.iloc[i, 12]),
                "Bajaj_Opening": _safe_float(rep_raw.iloc[i, 13]),
                "Bajaj_Drawdown": _safe_float(rep_raw.iloc[i, 14]),
                "Bajaj_Principal": _safe_float(rep_raw.iloc[i, 15]),
                "Bajaj_Interest": _safe_float(rep_raw.iloc[i, 16]),
                "Bajaj_Closing": _safe_float(rep_raw.iloc[i, 17]),
                "Total_Principal": _safe_float(rep_raw.iloc[i, 18]),
                "Total_Interest": _safe_float(rep_raw.iloc[i, 19]),
                "Total_DS": _safe_float(rep_raw.iloc[i, 20]),
                "Combined_OS": _safe_float(rep_raw.iloc[i, 21]),
            }
            rep_records.append(rec)
        except Exception:
            continue
    out["repayment_schedule"] = pd.DataFrame(rep_records)

    # ─── Scenario Analysis ─────────────────────────────────
    sc_raw = pd.read_excel(path, sheet_name="Scenario Analysis",
                           header=None, engine=_EXCEL_ENGINE)
    out["scenario_inputs"] = {
        "Rate_Shock_BPS": [_safe_float(sc_raw.iloc[3, 2])*10000, _safe_float(sc_raw.iloc[3, 3])*10000, _safe_float(sc_raw.iloc[3, 4])*10000],
        "Spread_BPS":     [_safe_float(sc_raw.iloc[4, 2])*10000, _safe_float(sc_raw.iloc[4, 3])*10000, _safe_float(sc_raw.iloc[4, 4])*10000],
        "Util_Change_Pct":  [_safe_float(sc_raw.iloc[5, 2])*100, _safe_float(sc_raw.iloc[5, 3])*100, _safe_float(sc_raw.iloc[5, 4])*100],
        "EBITDA_Change_Pct":[_safe_float(sc_raw.iloc[6, 2])*100, _safe_float(sc_raw.iloc[6, 3])*100, _safe_float(sc_raw.iloc[6, 4])*100],
        "Debt_Change_Pct":  [_safe_float(sc_raw.iloc[7, 2])*100, _safe_float(sc_raw.iloc[7, 3])*100, _safe_float(sc_raw.iloc[7, 4])*100],
    }
    out["scenario_outputs"] = {
        "Annual_B1_Interest": [_safe_float(sc_raw.iloc[11, 2]), _safe_float(sc_raw.iloc[11, 3]), _safe_float(sc_raw.iloc[11, 4])],
        "DSCR_Stressed":      [_safe_float(sc_raw.iloc[12, 2]), _safe_float(sc_raw.iloc[12, 3]), _safe_float(sc_raw.iloc[12, 4])],
        "Total_Debt_EBITDA":  [_safe_float(sc_raw.iloc[13, 2]), _safe_float(sc_raw.iloc[13, 3]), _safe_float(sc_raw.iloc[13, 4])],
        "ICR":                [_safe_float(sc_raw.iloc[14, 2]), _safe_float(sc_raw.iloc[14, 3]), _safe_float(sc_raw.iloc[14, 4])],
    }
    # Rate sensitivity table starts at row 23
    rate_sens = []
    for i in range(23, min(35, len(sc_raw))):
        try:
            label = sc_raw.iloc[i, 0]
            val = sc_raw.iloc[i, 1]
            if pd.notna(label) and pd.notna(val) and isinstance(val, (int, float)):
                rate_sens.append({"Benchmark": str(label), "Delta_Interest_100bps": float(val)})
        except Exception:
            continue
    out["rate_sensitivity"] = pd.DataFrame(rate_sens)

    return out


# ─── PUBLIC API ────────────────────────────────────────────────────────────
def load_all_data() -> Dict[str, Any]:
    """Public entry point. Returns full data dictionary with file metadata."""
    path = get_excel_path()
    sig = file_signature(path)
    if not path.exists():
        return {
            "error": f"Excel not found at {path}",
            "excel_exists": False,
            "excel_path": str(path),
            "excel_mtime": "FILE NOT FOUND",
            "excel_signature": "missing",
        }
    data = load_excel(sig, str(path))
    data["excel_exists"] = True
    data["excel_path"] = str(path)
    data["excel_mtime"] = file_mtime_pretty(path)
    data["excel_signature"] = sig
    return data


def force_reload():
    """Clear cache. Called by Reload button or after Excel upload."""
    st.cache_data.clear()
    try:
        st.cache_resource.clear()
    except Exception:
        pass


def save_uploaded_excel(uploaded_file_bytes: bytes) -> Path:
    """Persist uploaded Excel to the project root, replacing the bundled file."""
    target = get_excel_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        f.write(uploaded_file_bytes)
    return target
