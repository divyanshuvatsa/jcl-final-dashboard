"""Theme: colors, CSS, plotly defaults — production-quality dark mode."""

COLORS = {
    "navy": "#0A2540", "navy_light": "#1F3864",
    "blue": "#2563EB", "blue_light": "#60A5FA",
    "purple": "#8B5CF6", "purple_light": "#C084FC",
    "accent_gold": "#F59E0B",
    "compliant": "#10B981", "watch": "#3B82F6",
    "near_breach": "#F59E0B", "breach": "#EF4444",
    "neutral": "#6B7280", "pending": "#94A3B8",
    "bg_primary": "#0F172A", "bg_secondary": "#1E293B", "bg_tertiary": "#334155",
    "text_primary": "#F1F5F9", "text_secondary": "#94A3B8", "text_dim": "#64748B",
}

LENDER_COLORS = {
    "RBL Bank": "#3B82F6",
    "YES Bank": "#8B5CF6",
    "Bajaj Finance": "#F59E0B",
    "ICICI Bank": "#EC4899",
    "South Indian Bank": "#10B981",
}

CATEGORY_COLORS = {
    "FB": "#3B82F6",
    "FB-Term": "#F59E0B",
    "FB-FCY": "#60A5FA",
    "FB-FDbacked": "#06B6D4",
    "NFB": "#8B5CF6",
    "NFB-FDbacked": "#A78BFA",
    "Hedge": "#10B981",
}

STATUS_COLORS = {
    "Compliant": "#10B981",
    "Watch": "#3B82F6",
    "Near Breach": "#F59E0B",
    "Breach": "#EF4444",
    "Pending": "#94A3B8",
}

CHART_LAYOUT = {
    "template": "plotly_dark",
    "paper_bgcolor": "#1E293B",
    "plot_bgcolor": "#1E293B",
    "font": {"family": "Inter, system-ui, sans-serif", "size": 13, "color": "#F1F5F9"},
    "margin": {"l": 50, "r": 30, "t": 50, "b": 50},
}


CUSTOM_CSS = """
<style>
#MainMenu, footer, header {visibility: hidden;}
.stApp {background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);}
section[data-testid="stSidebar"] {background: #0A1628; border-right: 1px solid #334155;}

h1 {font-size: 2rem !important; font-weight: 800 !important;
    background: linear-gradient(90deg, #60A5FA 0%, #C084FC 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;}
h2 {font-size: 1.4rem !important; font-weight: 700 !important;
    border-bottom: 2px solid #3B82F6; padding-bottom: 6px;}
h3 {font-size: 1.1rem !important; color: #94A3B8 !important;}

/* KPI tiles */
.big-kpi {background: linear-gradient(135deg, #1E293B 0%, #243449 100%);
    border-radius: 16px; padding: 22px; border: 1px solid #334155; height: 100%;}
.big-kpi-label {color: #94A3B8; font-size: 0.75rem; text-transform: uppercase;
    letter-spacing: 0.10em; font-weight: 600; margin-bottom: 8px;}
.big-kpi-value {color: #F1F5F9; font-size: 2.2rem; font-weight: 800; line-height: 1;}
.big-kpi-sub {color: #94A3B8; font-size: 0.8rem; margin-top: 6px;}

/* Hero */
.hero-section {background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
    border-radius: 20px; padding: 28px 32px; margin-bottom: 20px;
    border: 1px solid #334155; position: relative;}
.hero-verdict-badge {display: inline-block; padding: 6px 14px;
    border-radius: 999px; font-size: 0.75rem; font-weight: 800;
    letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 14px;}
.hero-narrative {font-size: 1.15rem; line-height: 1.55; color: #F1F5F9; margin: 0;}
.hero-narrative b {color: #FFFFFF; font-weight: 700;}

/* Tab headers */
.tab-header {margin: 22px 0 14px 0;}
.tab-header-label {color: #60A5FA; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700;}
.tab-header-title {color: #F1F5F9; font-size: 1.5rem; font-weight: 800;
    margin: 4px 0 0 0;}
.tab-header-subtitle {color: #94A3B8; font-size: 0.9rem; margin-top: 4px;}

/* Status pills */
.status-pill {display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;}
.status-compliant {background: rgba(16,185,129,.15); color: #10B981; border: 1px solid #10B981;}
.status-watch {background: rgba(59,130,246,.15); color: #60A5FA; border: 1px solid #3B82F6;}
.status-near {background: rgba(245,158,11,.15); color: #F59E0B; border: 1px solid #F59E0B;}
.status-breach {background: rgba(239,68,68,.15); color: #EF4444; border: 1px solid #EF4444;}

/* Insight cards */
.insight-card {background: linear-gradient(135deg, #1E293B 0%, #243449 100%);
    border-radius: 12px; padding: 14px 18px; margin-bottom: 10px;
    border-left: 4px solid #3B82F6;}
.insight-card.good {border-left-color: #10B981; background: linear-gradient(135deg, rgba(16,185,129,.1) 0%, #1E293B 100%);}
.insight-card.warning {border-left-color: #F59E0B; background: linear-gradient(135deg, rgba(245,158,11,.1) 0%, #1E293B 100%);}
.insight-card.danger {border-left-color: #EF4444; background: linear-gradient(135deg, rgba(239,68,68,.1) 0%, #1E293B 100%);}
.insight-card.info {border-left-color: #3B82F6;}
.insight-title {font-size: 0.82rem; font-weight: 700; color: #F1F5F9;
    text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;}
.insight-body {font-size: 0.9rem; color: #CBD5E1; line-height: 1.5;}

/* Data layer badges */
.badge-live {display: inline-block; background: rgba(16,185,129,.15); color: #10B981;
    border: 1px solid #10B981; font-size: 0.65rem; font-weight: 700;
    padding: 1px 6px; border-radius: 3px; margin-right: 4px;}
.badge-frozen {display: inline-block; background: rgba(245,158,11,.15); color: #F59E0B;
    border: 1px solid #F59E0B; font-size: 0.65rem; font-weight: 700;
    padding: 1px 6px; border-radius: 3px; margin-right: 4px;}

/* Callouts */
.callout-good {background: rgba(16,185,129,.1); border-left: 4px solid #10B981;
    border-radius: 8px; padding: 12px 16px; margin: 10px 0; color: #D1FAE5;}
.callout-warn {background: rgba(245,158,11,.1); border-left: 4px solid #F59E0B;
    border-radius: 8px; padding: 12px 16px; margin: 10px 0; color: #FED7AA;}
.callout-info {background: rgba(59,130,246,.1); border-left: 4px solid #3B82F6;
    border-radius: 8px; padding: 12px 16px; margin: 10px 0; color: #DBEAFE;}
.callout-danger {background: rgba(239,68,68,.1); border-left: 4px solid #EF4444;
    border-radius: 8px; padding: 12px 16px; margin: 10px 0; color: #FECACA;}

/* Live banner */
.live-banner {background: linear-gradient(90deg, #DC2626 0%, #EF4444 100%);
    color: white; padding: 8px 16px; border-radius: 6px; font-weight: 600;
    text-align: center; margin-bottom: 12px; font-size: 13px; letter-spacing: 0.5px;}

/* Mini-stats */
.mini-stat {display: inline-block; padding: 2px 10px; background: rgba(59,130,246,.15);
    border-radius: 12px; color: #60A5FA; font-size: 0.75rem; font-weight: 600; margin: 0 4px;}

/* Heatmap cell */
.heatmap-cell {padding: 8px 12px; border-radius: 6px; text-align: center;
    font-weight: 700; color: white; font-size: 0.85rem;}
</style>
"""
