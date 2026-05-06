"""
Live Market Rates — fetches current benchmark rates from public sources.

Sources (all FREE, no API key needed):
- USD/INR: exchangerate.host (ECB-backed)
- US 10Y Treasury: Yahoo Finance (^TNX)
- SOFR: NY Fed public JSON API
- Indian 10Y G-Sec: scrape from worldgovernmentbonds.com or fall back to estimate
- RBI Repo Rate: scrape RBI press release page

Caching: 1 hour TTL via @st.cache_data
Graceful failure: if a source fails, returns None for that rate (UI shows "N/A")
"""

from __future__ import annotations
import streamlit as st
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import re
import json


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}


def _safe_get_json(url: str, timeout: int = 8) -> Optional[Any]:
    """HTTP GET → JSON with graceful failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _safe_get_text(url: str, timeout: int = 8) -> Optional[str]:
    """HTTP GET → text with graceful failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


# ─── Individual fetchers (each isolated, fails gracefully) ───────────

def fetch_usd_inr() -> Optional[Dict]:
    """USD/INR via exchangerate.host (free, no key)."""
    # Try primary source
    data = _safe_get_json("https://api.exchangerate.host/latest?base=USD&symbols=INR")
    if data and data.get("success") is not False:
        rate = data.get("rates", {}).get("INR")
        if rate:
            return {"value": float(rate), "source": "exchangerate.host"}
    
    # Fallback: open.er-api.com (free, no key)
    data = _safe_get_json("https://open.er-api.com/v6/latest/USD")
    if data and data.get("rates", {}).get("INR"):
        return {"value": float(data["rates"]["INR"]), "source": "er-api.com"}
    
    return None


def fetch_us_10y_treasury() -> Optional[Dict]:
    """US 10Y Treasury yield via US Treasury XML."""
    # Try US Treasury XML feed
    today = datetime.now()
    url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
           f"interest-rates/daily-treasury-rates.csv/{today.year}/all"
           f"?type=daily_treasury_yield_curve&field_tdr_date_value={today.year}&page&_format=csv")
    text = _safe_get_text(url)
    if text:
        # Parse CSV: first row is header, find latest with 10Y data
        lines = text.strip().split("\n")
        if len(lines) > 1:
            header = lines[0].split(",")
            # Find 10 Yr column
            try:
                idx = next(i for i, h in enumerate(header) if "10 Yr" in h or '"10 Yr"' in h)
                latest = lines[1].split(",")
                rate = float(latest[idx].strip('"'))
                return {"value": rate, "source": "US Treasury"}
            except (StopIteration, ValueError, IndexError):
                pass
    
    return None


def fetch_sofr() -> Optional[Dict]:
    """SOFR via NY Fed public JSON API."""
    url = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json"
    data = _safe_get_json(url)
    if data:
        refRates = data.get("refRates", [])
        if refRates:
            rate = refRates[0].get("percentRate")
            if rate is not None:
                return {"value": float(rate), "source": "NY Fed"}
    return None


def fetch_rbi_repo_rate() -> Optional[Dict]:
    """RBI Repo Rate — scrape from RBI website. Falls back to known last value."""
    # The RBI repo rate is published on https://www.rbi.org.in/
    # We'll scrape the home page and look for "Policy Repo Rate"
    text = _safe_get_text("https://www.rbi.org.in/")
    if text:
        # Match pattern like "Policy Repo Rate : 6.50%" or similar
        m = re.search(r"Policy\s+Repo\s+Rate[^\d]*([\d.]+)\s*%", text, re.IGNORECASE)
        if m:
            try:
                return {"value": float(m.group(1)), "source": "RBI"}
            except ValueError:
                pass
    
    # Fallback: known stable rate (manually maintained)
    return {"value": 6.50, "source": "RBI (last known)"}


def fetch_india_10y() -> Optional[Dict]:
    """India 10Y G-Sec yield — scrape from worldgovernmentbonds.com."""
    text = _safe_get_text("http://www.worldgovernmentbonds.com/country/india/")
    if text:
        # Look for 10Y yield pattern
        m = re.search(r"10\s*Years[^\d]*([\d.]+)\s*%", text)
        if m:
            try:
                return {"value": float(m.group(1)), "source": "worldgovernmentbonds.com"}
            except ValueError:
                pass
    return None


# ─── Master fetcher with caching ─────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)  # 1 hour cache
def fetch_all_market_rates() -> Dict[str, Any]:
    """Fetch all market rates. Cached for 1 hour."""
    rates = {
        "fetched_at": datetime.now().isoformat(),
        "fetched_at_pretty": datetime.now().strftime("%d-%b-%Y %H:%M IST"),
    }
    
    rates["USD_INR"] = fetch_usd_inr()
    rates["US_10Y"] = fetch_us_10y_treasury()
    rates["SOFR"] = fetch_sofr()
    rates["RBI_Repo"] = fetch_rbi_repo_rate()
    rates["India_10Y"] = fetch_india_10y()
    
    return rates


def render_market_rates_sidebar():
    """Renders the market rates section in the sidebar (collapsible)."""
    with st.sidebar:
        with st.expander("📊 Live Market Rates", expanded=False):
            with st.spinner("Fetching..."):
                try:
                    rates = fetch_all_market_rates()
                except Exception as e:
                    st.warning(f"Couldn't fetch rates: {e}")
                    return
            
            # Display each rate
            def _fmt(label, key, suffix="%", icon=""):
                r = rates.get(key)
                if r and r.get("value") is not None:
                    val = r["value"]
                    src = r.get("source", "")
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:6px 0;border-bottom:1px solid #334155;'>"
                        f"<span style='color:#94A3B8;font-size:0.82rem;'>{icon} {label}</span>"
                        f"<span style='color:#F1F5F9;font-weight:600;font-size:0.95rem;'>"
                        f"{val:.2f}{suffix}</span></div>",
                        unsafe_allow_html=True,
                    )
                    return src
                else:
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:6px 0;border-bottom:1px solid #334155;'>"
                        f"<span style='color:#94A3B8;font-size:0.82rem;'>{icon} {label}</span>"
                        f"<span style='color:#64748B;font-size:0.85rem;'>N/A</span></div>",
                        unsafe_allow_html=True,
                    )
                    return None
            
            sources = []
            s = _fmt("USD/INR", "USD_INR", suffix="", icon="💱")
            if s: sources.append(s)
            s = _fmt("RBI Repo Rate", "RBI_Repo", icon="🏦")
            if s: sources.append(s)
            s = _fmt("India 10Y G-Sec", "India_10Y", icon="🇮🇳")
            if s: sources.append(s)
            s = _fmt("US 10Y Treasury", "US_10Y", icon="🇺🇸")
            if s: sources.append(s)
            s = _fmt("SOFR", "SOFR", icon="💵")
            if s: sources.append(s)
            
            st.markdown(
                f"<div style='font-size:0.7rem;color:#64748B;padding-top:8px;'>"
                f"Updated: {rates['fetched_at_pretty']}<br>"
                f"Auto-refresh every hour</div>",
                unsafe_allow_html=True,
            )
            
            if st.button("🔄 Refresh now", key="refresh_market_rates", use_container_width=True):
                fetch_all_market_rates.clear()
                st.rerun()
