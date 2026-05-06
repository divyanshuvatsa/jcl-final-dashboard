"""
Excel reader — JCL_Debt_Model_Final.xlsx is the single source of truth.

Reads pre-computed values from the Excel:
  - Effective Outstanding (col 15) — Excel handles cap allocation, sub-limits, USD INR caps
  - Effective Rate p.a. (col 20) — Excel handles benchmark + spread
  - Covenant actuals & status — read directly from Covenant Tracker
  - Lender Summary three-bucket totals — read from Lender Summary tab
  - Repayment Schedule — read quarterly schedule
  - Interest Schedule — read per-facility annual cost

Falls back to recomputation only if Excel cells are blank.
"""

from __future__ import annotations
import hashlib
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


def file_signature(path: Path) -> str:
    """Hash + mtime composite — invalidates cache on any change."""
    if not path.exists():
        return "missing"
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"{h.hexdigest()}_{path.stat().st_mtime:.0f}"


def file_mtime_pretty(path: Path) -> str:
    if not path.exists():
        return "FILE NOT FOUND"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d-%b-%Y %H:%M:%S")


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
                        header=None, engine="openpyxl")

    # Section A: parameters (rows 4-8 in pandas 0-index)
    out["as_of_date"] = pd.Timestamp(ins.iloc[3, 1]).date()
    out["fx_rate"] = float(ins.iloc[4, 1])
    out["use_full_util"] = bool(ins.iloc[5, 1])
    out["days_in_year"] = int(ins.iloc[6, 1])
    out["financial_basis"] = str(ins.iloc[7, 1])

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

    # Section C: financials (rows 24-39)
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
                    if key in ("External Rating",):
                        out["financials"][tag][key] = str(val)
                    else:
                        out["financials"][tag][key] = float(val)
        except Exception:
            continue

    # Section D: sanction-letter caps (rows 42-46)
    out["caps"] = {}
    for i in range(41, 50):
        try:
            label = ins.iloc[i, 0]
            val = ins.iloc[i, 1]
            if pd.notna(label) and pd.notna(val) and isinstance(val, (int, float)):
                out["caps"][str(label).strip()] = float(val)
        except Exception:
            continue

    # ─── Facility Master ─────────────────────────────────────
    fm_raw = pd.read_excel(path, sheet_name="Facility Master", header=3, engine="openpyxl")
    # Filter rows where S.No is numeric
    fm_raw = fm_raw[pd.to_numeric(fm_raw["S.No"], errors="coerce").notna()].copy()
    fm_raw["S.No"] = fm_raw["S.No"].astype(int)
    
    fm_records = []
    for _, r in fm_raw.iterrows():
        rec = {
            "S_No": int(r["S.No"]),
            "Lender": str(r["Lender"]),
            "Facility": str(r["Facility"]),
            "Category": str(r["Category"]),
            "Nature": str(r["Nature"]),
            "Sub_Limit_Flag": bool(r["Sub-Limit Flag"]) if pd.notna(r["Sub-Limit Flag"]) else False,
            "WC_Cap_Group": str(r["WC Cap Group"]) if pd.notna(r["WC Cap Group"]) else None,
            "WC_Cap_Amount": float(r["WC Cap Amount"]) if pd.notna(r["WC Cap Amount"]) else None,
            "FD_Backed": bool(r["FD-Backed"]) if pd.notna(r["FD-Backed"]) else False,
            "Bucket": int(r["Bucket"]) if pd.notna(r["Bucket"]) else 0,
            "Currency": str(r["Currency"]),
            "Sanc_Orig_Ccy": float(r["Sanc Orig Ccy"]) if pd.notna(r["Sanc Orig Ccy"]) else 0.0,
            "Sanction_INR": float(r["Sanc INR Cr"]) if pd.notna(r["Sanc INR Cr"]) else 0.0,
            "Current_OS": float(r["Current O/S"]) if pd.notna(r["Current O/S"]) else 0.0,
            "Effective_OS": float(r["Effective O/S"]) if pd.notna(r["Effective O/S"]) else 0.0,
            "Util_Pct": float(r["Util %"]) if pd.notna(r["Util %"]) else 0.0,
            "Headroom": float(r["Headroom"]) if pd.notna(r["Headroom"]) else 0.0,
            "Benchmark": str(r["Benchmark"]) if pd.notna(r["Benchmark"]) else "",
            "Spread_BPS": float(r["Spread"]) * 10000 if pd.notna(r["Spread"]) else 0.0,
            "Effective_Rate": float(r["Eff Rate p.a."]) if pd.notna(r["Eff Rate p.a."]) else 0.0,
            "Rate_Type": str(r["Rate Type"]) if pd.notna(r["Rate Type"]) else "",
            "Moratorium_Months": int(r["Moratorium Mths"]) if pd.notna(r["Moratorium Mths"]) else 0,
            "Repayment_Frequency": str(r["Rep Frequency"]) if pd.notna(r["Rep Frequency"]) else "",
            "Tenor_Months": int(r["Tenor Mths"]) if pd.notna(r["Tenor Mths"]) else 0,
            "Num_Instalments": int(r["No of Instalments"]) if pd.notna(r["No of Instalments"]) else 0,
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
    cov_raw = pd.read_excel(path, sheet_name="Covenant Tracker", header=2, engine="openpyxl")
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
    ls_raw = pd.read_excel(path, sheet_name="Lender Summary", header=None, engine="openpyxl")
    bucket1 = []  # rows 5-9 (0-indexed 4-8): TL, WC FB Cap, Total Debt, %
    for i in range(4, 9):
        if pd.notna(ls_raw.iloc[i, 0]):
            bucket1.append({
                "Lender": str(ls_raw.iloc[i, 0]),
                "TL_Sanctioned": float(ls_raw.iloc[i, 1]) if pd.notna(ls_raw.iloc[i, 1]) else 0,
                "WC_FB_Cap": float(ls_raw.iloc[i, 2]) if pd.notna(ls_raw.iloc[i, 2]) else 0,
                "Bucket1_Total_Debt": float(ls_raw.iloc[i, 3]) if pd.notna(ls_raw.iloc[i, 3]) else 0,
            })
    out["lender_bucket1"] = pd.DataFrame(bucket1)

    # Bucket 2 — rows 15-19
    bucket2 = []
    for i in range(14, 19):
        if pd.notna(ls_raw.iloc[i, 0]):
            bucket2.append({
                "Lender": str(ls_raw.iloc[i, 0]),
                "LCs": float(ls_raw.iloc[i, 1]) if pd.notna(ls_raw.iloc[i, 1]) else 0,
                "SBLCs": float(ls_raw.iloc[i, 2]) if pd.notna(ls_raw.iloc[i, 2]) else 0,
                "BGs_memo": float(ls_raw.iloc[i, 3]) if pd.notna(ls_raw.iloc[i, 3]) else 0,
                "Capex_LCs": float(ls_raw.iloc[i, 4]) if pd.notna(ls_raw.iloc[i, 4]) else 0,
                "Bucket2_Total_NFB": float(ls_raw.iloc[i, 5]) if pd.notna(ls_raw.iloc[i, 5]) else 0,
            })
    out["lender_bucket2"] = pd.DataFrame(bucket2)

    # Bucket 3 — rows 25-29
    bucket3 = []
    for i in range(24, 29):
        if pd.notna(ls_raw.iloc[i, 0]):
            bucket3.append({
                "Lender": str(ls_raw.iloc[i, 0]),
                "FD_Backed": float(ls_raw.iloc[i, 1]) if pd.notna(ls_raw.iloc[i, 1]) else 0,
                "Hedge_Notional": float(ls_raw.iloc[i, 2]) if pd.notna(ls_raw.iloc[i, 2]) else 0,
                "Bucket3_Total": float(ls_raw.iloc[i, 3]) if pd.notna(ls_raw.iloc[i, 3]) else 0,
            })
    out["lender_bucket3"] = pd.DataFrame(bucket3)

    # Total Banking Exposure (row 44-48 lender concentration)
    concentration = []
    for i in range(43, 48):
        if pd.notna(ls_raw.iloc[i, 0]):
            concentration.append({
                "Lender": str(ls_raw.iloc[i, 0]),
                "Total_Banking_Exposure": float(ls_raw.iloc[i, 1]) if pd.notna(ls_raw.iloc[i, 1]) else 0,
                "Pct_Sanctioned_Debt": float(ls_raw.iloc[i, 2]) if pd.notna(ls_raw.iloc[i, 2]) else 0,
                "Pct_Banking_Exposure": float(ls_raw.iloc[i, 3]) if pd.notna(ls_raw.iloc[i, 3]) else 0,
            })
    out["lender_concentration"] = pd.DataFrame(concentration)

    # Headline totals (Lender Summary R34-R37)
    out["totals"] = {
        "Bucket1_Sanctioned_Debt": float(ls_raw.iloc[33, 3]) if pd.notna(ls_raw.iloc[33, 3]) else 0,
        "Bucket2_NFB_Contingent": float(ls_raw.iloc[34, 3]) if pd.notna(ls_raw.iloc[34, 3]) else 0,
        "Bucket3_Separate": float(ls_raw.iloc[35, 3]) if pd.notna(ls_raw.iloc[35, 3]) else 0,
        "Total_Banking_Exposure": float(ls_raw.iloc[36, 3]) if pd.notna(ls_raw.iloc[36, 3]) else 0,
    }

    # ─── Interest Schedule ─────────────────────────────────
    int_raw = pd.read_excel(path, sheet_name="Interest Schedule", header=2, engine="openpyxl")
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
            "Sanction_INR": float(r["Sanc INR Cr"]) if pd.notna(r["Sanc INR Cr"]) else 0,
            "Effective_OS": float(r["Eff O/S"]) if pd.notna(r["Eff O/S"]) else 0,
            "Effective_Rate": float(r["Eff Rate"]) if pd.notna(r["Eff Rate"]) else 0,
            "Annual_Cost": float(r["Annual Interest/Comm. ₹Cr"]) if pd.notna(r["Annual Interest/Comm. ₹Cr"]) else 0,
        })
    out["interest_schedule"] = pd.DataFrame(int_records)

    # Interest summary (rows 39-44 in 1-index, 38-43 in 0-index)
    int_summary_raw = pd.read_excel(path, sheet_name="Interest Schedule",
                                    header=None, engine="openpyxl")
    out["interest_summary"] = {
        "Bucket1_Interest": float(int_summary_raw.iloc[39, 8]) if pd.notna(int_summary_raw.iloc[39, 8]) else 0,
        "Bucket2_Commission": float(int_summary_raw.iloc[40, 8]) if pd.notna(int_summary_raw.iloc[40, 8]) else 0,
        "Bucket3_Interest": float(int_summary_raw.iloc[41, 8]) if pd.notna(int_summary_raw.iloc[41, 8]) else 0,
        "Total_Interest_Commission": float(int_summary_raw.iloc[42, 8]) if pd.notna(int_summary_raw.iloc[42, 8]) else 0,
        "Weighted_Avg_Cost": float(int_summary_raw.iloc[43, 8]) if pd.notna(int_summary_raw.iloc[43, 8]) else 0,
    }

    # ─── Repayment Schedule ────────────────────────────────
    rep_raw = pd.read_excel(path, sheet_name="Repayment Schedule",
                            header=None, engine="openpyxl")
    rep_records = []
    for i in range(4, len(rep_raw)):
        period_end = rep_raw.iloc[i, 1]
        label = rep_raw.iloc[i, 2]
        if pd.isna(period_end):
            continue
        try:
            rec = {
                "Period_End": pd.Timestamp(period_end),
                "Period_Label": str(label) if pd.notna(label) else "",
                "RBL_Opening": float(rep_raw.iloc[i, 3]) if pd.notna(rep_raw.iloc[i, 3]) else 0,
                "RBL_Drawdown": float(rep_raw.iloc[i, 4]) if pd.notna(rep_raw.iloc[i, 4]) else 0,
                "RBL_Principal": float(rep_raw.iloc[i, 5]) if pd.notna(rep_raw.iloc[i, 5]) else 0,
                "RBL_Interest": float(rep_raw.iloc[i, 6]) if pd.notna(rep_raw.iloc[i, 6]) else 0,
                "RBL_Closing": float(rep_raw.iloc[i, 7]) if pd.notna(rep_raw.iloc[i, 7]) else 0,
                "YBL_Opening": float(rep_raw.iloc[i, 8]) if pd.notna(rep_raw.iloc[i, 8]) else 0,
                "YBL_Drawdown": float(rep_raw.iloc[i, 9]) if pd.notna(rep_raw.iloc[i, 9]) else 0,
                "YBL_Principal": float(rep_raw.iloc[i, 10]) if pd.notna(rep_raw.iloc[i, 10]) else 0,
                "YBL_Interest": float(rep_raw.iloc[i, 11]) if pd.notna(rep_raw.iloc[i, 11]) else 0,
                "YBL_Closing": float(rep_raw.iloc[i, 12]) if pd.notna(rep_raw.iloc[i, 12]) else 0,
                "Bajaj_Opening": float(rep_raw.iloc[i, 13]) if pd.notna(rep_raw.iloc[i, 13]) else 0,
                "Bajaj_Drawdown": float(rep_raw.iloc[i, 14]) if pd.notna(rep_raw.iloc[i, 14]) else 0,
                "Bajaj_Principal": float(rep_raw.iloc[i, 15]) if pd.notna(rep_raw.iloc[i, 15]) else 0,
                "Bajaj_Interest": float(rep_raw.iloc[i, 16]) if pd.notna(rep_raw.iloc[i, 16]) else 0,
                "Bajaj_Closing": float(rep_raw.iloc[i, 17]) if pd.notna(rep_raw.iloc[i, 17]) else 0,
                "Total_Principal": float(rep_raw.iloc[i, 18]) if pd.notna(rep_raw.iloc[i, 18]) else 0,
                "Total_Interest": float(rep_raw.iloc[i, 19]) if pd.notna(rep_raw.iloc[i, 19]) else 0,
                "Total_DS": float(rep_raw.iloc[i, 20]) if pd.notna(rep_raw.iloc[i, 20]) else 0,
                "Combined_OS": float(rep_raw.iloc[i, 21]) if pd.notna(rep_raw.iloc[i, 21]) else 0,
            }
            rep_records.append(rec)
        except Exception:
            continue
    out["repayment_schedule"] = pd.DataFrame(rep_records)

    # ─── Scenario Analysis ─────────────────────────────────
    sc_raw = pd.read_excel(path, sheet_name="Scenario Analysis",
                           header=None, engine="openpyxl")
    out["scenario_inputs"] = {
        "Rate_Shock_BPS": [float(sc_raw.iloc[3, 2])*10000, float(sc_raw.iloc[3, 3])*10000, float(sc_raw.iloc[3, 4])*10000],
        "Spread_BPS": [float(sc_raw.iloc[4, 2])*10000, float(sc_raw.iloc[4, 3])*10000, float(sc_raw.iloc[4, 4])*10000],
        "Util_Change_Pct": [float(sc_raw.iloc[5, 2])*100, float(sc_raw.iloc[5, 3])*100, float(sc_raw.iloc[5, 4])*100],
        "EBITDA_Change_Pct": [float(sc_raw.iloc[6, 2])*100, float(sc_raw.iloc[6, 3])*100, float(sc_raw.iloc[6, 4])*100],
        "Debt_Change_Pct": [float(sc_raw.iloc[7, 2])*100, float(sc_raw.iloc[7, 3])*100, float(sc_raw.iloc[7, 4])*100],
    }
    out["scenario_outputs"] = {
        "Annual_B1_Interest": [float(sc_raw.iloc[11, 2]), float(sc_raw.iloc[11, 3]), float(sc_raw.iloc[11, 4])],
        "DSCR_Stressed": [float(sc_raw.iloc[12, 2]), float(sc_raw.iloc[12, 3]), float(sc_raw.iloc[12, 4])],
        "Total_Debt_EBITDA": [float(sc_raw.iloc[13, 2]), float(sc_raw.iloc[13, 3]), float(sc_raw.iloc[13, 4])],
        "ICR": [float(sc_raw.iloc[14, 2]), float(sc_raw.iloc[14, 3]), float(sc_raw.iloc[14, 4])],
    }
    # Rate sensitivity (rows 23-29)
    rate_sens = []
    for i in range(23, 32):
        try:
            label = sc_raw.iloc[i, 0]
            val = sc_raw.iloc[i, 1]
            if pd.notna(label) and pd.notna(val):
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
