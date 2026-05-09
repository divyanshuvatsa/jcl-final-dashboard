# JCL Debt Monitoring Dashboard

Real-time, fully-dynamic, Excel-driven debt and covenant monitoring dashboard for **Jindal Coke Limited**.

## What's included (10 tabs)

1. **Overview** — three-bucket totals, KPIs, lender concentration donut
2. **Repayment** — TL outstanding, FY-by-FY principal stack, upcoming renewals
3. **Covenants** — all 24 covenants, attention items, status pills
4. **Scenarios** — live stress sliders + Excel preset library
5. **Heatmap** — lender × facility category exposure (free feature)
6. **Rate Path** — 8-quarter RBI rate decision simulator (free feature)
7. **Renewals** — 5-bucket priority calendar (≤30, 31-60, 61-90, 91-180, >180 days)
8. **AI Analyst** — 10 rule-based answers + 4 proactive insight cards
9. **Snapshots** — capture state, compare against past, JSON backup (NEW)
10. **Export** — CSV downloads + **PDF board memo** (NEW)

## Architecture

The Excel is the **single source of truth**. Every number is read from the workbook each reload — no hardcoded magic values.

```
JCL_Debt_Model_Final.xlsx  →  data_loader.load_all_data()
                            ↓
                     scenario_engine (applies user shocks)
                            ↓
                     dashboard_ui (renders 10 tabs)
```

**Update the Excel → click "Reload from Excel" → dashboard updates instantly.**

## Quick Start (Local)

```bash
unzip JCL_Debt_Dashboard_Final.zip
cd JCL_Debt_Dashboard_Final
pip install -r requirements.txt
streamlit run main.py
```

Browse to `http://localhost:8501`.

## Deploy to Streamlit Cloud

1. Push folder to a GitHub repo
2. Visit [share.streamlit.io](https://share.streamlit.io)
3. New app → connect to repo → main file = `main.py`
4. Deploy

## Verification

```bash
python3 verify_all.py
```

Expected output: **46/46 PASSED** across 10 phases.

## What gets verified

- All 34 facilities load correctly
- All 24 covenants match Excel thresholds and actuals
- Three-bucket totals: B1 ₹720.7 + B2 ₹600 = Sanctioned Debt ₹1,320.7
- NFB Contingent ₹815 (off-B/S) | FD-Backed ₹100 (separate line)
- Annual interest+commission = ₹49.04 Cr
- WAC = 8.08%
- 10 AI questions all return valid answers
- 4 proactive insight cards generate
- Lender heatmap excludes sub-limits
- Rate path simulator: cuts reduce interest as expected
- PDF board memo: 2 pages, all key data, valid PDF
- Historical snapshots: capture, compare, JSON round-trip
- Live Excel update: edit Excel → values update in dashboard
- Streamlit app launches without errors

## Files

| File | Purpose |
|------|---------|
| `main.py` | Streamlit entry point |
| `data_loader.py` | Excel reader (cache-keyed on file hash + mtime) |
| `scenario_engine.py` | Dynamic recompute layer (covenants, interest, ratios) |
| `dashboard_ui.py` | All 10 tabs |
| `rule_based_ai.py` | Q&A + insights (deterministic, zero API) |
| `theme.py` | Dark mode CSS |
| `lender_heatmap.py` | Heatmap visualization |
| `rate_path_simulator.py` | 8-quarter rate path tool |
| `pdf_export.py` | Board memo PDF generator (reportlab) |
| `snapshots.py` | Historical state capture/compare |
| `verify_all.py` | Full V&V test suite |
| `requirements.txt` | Python deps |
| `JCL_Debt_Model_Final.xlsx` | Source workbook (single source of truth) |

## How to update data

**Method A (local)**: Edit `JCL_Debt_Model_Final.xlsx`, save, click sidebar → 🔄 Reload from Excel.

**Method B (cloud)**: Use the sidebar uploader (📤 Upload Updated Excel) — works on Streamlit Cloud where the local filesystem is read-only.

Both methods invalidate the cache and rebuild everything from the new Excel.

## Health Check Numbers (May-2026 baseline)

If you see different values, the Excel has been edited:

- Sanctioned Debt: **₹1,320.7 Cr** (B1 FB ₹720.7 + B2 NFB ₹600)
- NFB Contingent: **₹815 Cr** (off-balance-sheet face)
- FD-Backed Separate: **₹100 Cr** (RBL FDOD only)
- Annual Interest+Commission: **₹49.04 Cr**
- Weighted Avg Cost: **8.08%**
- All 24 covenants: **Compliant**
- DSCR: **3.49x** | ICR: **7.82x** | Total Debt/EBITDA: **1.60x**
- Top lender: **YES Bank at 39.4%** of sanctioned debt

---

**No API keys** · **No external services** · **Zero runtime cost** · **Streamlit Cloud-ready**
