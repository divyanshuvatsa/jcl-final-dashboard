"""
Historical snapshots — save current state, compare against past states.

Storage: st.session_state (in-memory, per session) + JSON export/import
for cross-session persistence. On Streamlit Cloud, snapshots last for the
session; user can export to JSON to keep them across sessions.
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Dict, Any, List
import pandas as pd
import streamlit as st


def _extract_state(data: Dict[str, Any], cov_df: pd.DataFrame) -> Dict[str, Any]:
    """Extract the key metrics from current data into a snapshottable dict."""
    t = data["totals"]
    isum = data["interest_summary"]
    fy26 = data["financials"]["FY26E"]
    
    # Top-level metrics
    state = {
        "as_of_date": str(data["as_of_date"]),
        "fx_rate": float(data["fx_rate"]),
        "excel_signature": data.get("excel_signature", ""),
        "excel_mtime": data.get("excel_mtime", ""),
        
        # Three-bucket totals
        "Bucket1_Sanctioned_Debt": float(t["Bucket1_Sanctioned_Debt"]),
        "Bucket2_NFB_Contingent": float(t["Bucket2_NFB_Contingent"]),
        "Bucket3_Separate": float(t["Bucket3_Separate"]),
        
        # Cost
        "Annual_Interest_Comm": float(isum["Total_Interest_Commission"]),
        "Bucket1_Interest": float(isum["Bucket1_Interest"]),
        "Bucket2_Commission": float(isum["Bucket2_Commission"]),
        "Bucket3_Interest": float(isum["Bucket3_Interest"]),
        "Weighted_Avg_Cost": float(isum["Weighted_Avg_Cost"]),
        
        # Financials
        "EBITDA": float(fy26["EBITDA"]),
        "Total_Debt": float(fy26["Total Debt"]),
        "Term_Debt": float(fy26["Term Debt"]),
        "TNW": float(fy26["TNW"]),
        "Interest_Expense": float(fy26["Interest Expense"]),
        
        # Covenant counts
        "Total_Covenants": len(cov_df),
        "Compliant": int((cov_df["Status"] == "Compliant").sum()),
        "Watch": int((cov_df["Status"] == "Watch").sum()),
        "Near_Breach": int((cov_df["Status"] == "Near Breach").sum()),
        "Breach": int((cov_df["Status"] == "Breach").sum()),
        
        # Key covenant actuals
        "covenant_actuals": {},
    }
    
    # Per-covenant snapshot
    for _, r in cov_df.iterrows():
        key = f"{r['Lender']}::{r['Covenant']}"
        actual = r.get("Actual")
        if isinstance(actual, (int, float)):
            state["covenant_actuals"][key] = float(actual)
    
    # Per-lender exposure (by Sanctioned Debt)
    state["lender_exposure"] = {}
    b1_snap = data["lender_bucket1"]
    b1_snap = b1_snap[b1_snap["Lender"] != "Grand Total"]
    for _, r in b1_snap.iterrows():
        state["lender_exposure"][r["Lender"]] = float(r["Bucket1_Total_Debt"])
    
    return state


def take_snapshot(data: Dict[str, Any], cov_df: pd.DataFrame, label: str = "") -> Dict[str, Any]:
    """Capture current state and store in session_state."""
    if "snapshots" not in st.session_state:
        st.session_state.snapshots = []
    
    timestamp = datetime.now()
    snap = {
        "id": f"snap_{timestamp.strftime('%Y%m%d_%H%M%S')}",
        "label": label or f"Snapshot {timestamp.strftime('%d-%b-%Y %H:%M')}",
        "captured_at": timestamp.isoformat(),
        "captured_at_pretty": timestamp.strftime("%d-%b-%Y %H:%M:%S"),
        "state": _extract_state(data, cov_df),
    }
    st.session_state.snapshots.append(snap)
    return snap


def list_snapshots() -> List[Dict[str, Any]]:
    return st.session_state.get("snapshots", [])


def get_snapshot(snap_id: str) -> Dict[str, Any]:
    for s in list_snapshots():
        if s["id"] == snap_id:
            return s
    return None


def delete_snapshot(snap_id: str):
    snaps = list_snapshots()
    st.session_state.snapshots = [s for s in snaps if s["id"] != snap_id]


def clear_snapshots():
    st.session_state.snapshots = []


def compare_snapshots(snap_a: Dict[str, Any], snap_b: Dict[str, Any]) -> Dict[str, Any]:
    """Compute delta between two snapshots. snap_a = older, snap_b = newer."""
    a = snap_a["state"]
    b = snap_b["state"]
    delta = {"changed": [], "unchanged": [], "covenant_changes": [], "exposure_changes": []}
    
    skip_keys = {"covenant_actuals", "lender_exposure", "as_of_date",
                  "excel_signature", "excel_mtime"}
    
    for key in a.keys():
        if key in skip_keys: continue
        va = a.get(key); vb = b.get(key)
        if va is None or vb is None: continue
        if isinstance(va, (int, float)):
            if abs(vb - va) > 0.001:
                delta["changed"].append({
                    "metric": key,
                    "before": va, "after": vb,
                    "abs_change": vb - va,
                    "pct_change": ((vb - va) / va * 100) if va != 0 else 0,
                })
            else:
                delta["unchanged"].append(key)
    
    # Covenant deltas
    cov_a = a.get("covenant_actuals", {})
    cov_b = b.get("covenant_actuals", {})
    for k in set(list(cov_a.keys()) + list(cov_b.keys())):
        va = cov_a.get(k); vb = cov_b.get(k)
        if va is None or vb is None: continue
        if abs(vb - va) > 0.001:
            lender, cov = k.split("::", 1)
            delta["covenant_changes"].append({
                "lender": lender, "covenant": cov,
                "before": va, "after": vb, "abs_change": vb - va,
            })
    
    # Lender exposure deltas
    exp_a = a.get("lender_exposure", {})
    exp_b = b.get("lender_exposure", {})
    for lender in set(list(exp_a.keys()) + list(exp_b.keys())):
        va = exp_a.get(lender, 0); vb = exp_b.get(lender, 0)
        if abs(vb - va) > 0.01:
            delta["exposure_changes"].append({
                "lender": lender, "before": va, "after": vb, "abs_change": vb - va,
            })
    
    return delta


def export_snapshots_to_json() -> bytes:
    """Export all snapshots to JSON for download."""
    return json.dumps(list_snapshots(), indent=2, default=str).encode("utf-8")


def import_snapshots_from_json(json_bytes: bytes) -> int:
    """Import snapshots from uploaded JSON. Returns count imported."""
    snaps = json.loads(json_bytes.decode("utf-8"))
    if "snapshots" not in st.session_state:
        st.session_state.snapshots = []
    existing_ids = {s["id"] for s in st.session_state.snapshots}
    count = 0
    for s in snaps:
        if s.get("id") not in existing_ids:
            st.session_state.snapshots.append(s)
            count += 1
    return count
