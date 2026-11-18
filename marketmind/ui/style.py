"""Design system: colours, global CSS, the Plotly template and small layout helpers."""

from __future__ import annotations

import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

ACCENT = "#7C6CFF"
ACCENT_2 = "#2DD4BF"
UP = "#22C55E"
DOWN = "#F43F5E"
WARN = "#F59E0B"
MUTED = "#8B95A7"
SURFACE = "#121826"
BORDER = "#1E2636"

PAGES = {
    "Overview": (":material/space_dashboard:", "Your day at a glance: alerts, performance and what to do next."),
    "Analyse": (":material/query_stats:", "Charts, indicators, patterns, fundamentals and an AI brief for one asset."),
    "Backtest": (":material/history:", "Would a simple trend rule have beaten just buying and holding?"),
    "Portfolio": (":material/account_balance_wallet:", "What you own, what it's worth, and how it moves together."),
    "Paper trading": (":material/swap_horiz:", "Practise execution with a simulated cash account."),
    "Predictions": (":material/flag:", "Timestamped calls, scored automatically when their horizon passes."),
    "Practice": (":material/sports_esports:", "Call real historical charts and get scored instantly."),
    "Report card": (":material/school:", "What your own track record says about your decisions."),
    "Journal": (":material/edit_note:", "Your theses, invalidation levels and event calendar."),
    "Settings": (":material/settings:", "Password, your data, privacy."),
    "Admin": (":material/admin_panel_settings:", "Accounts and sign-in activity."),
}


def nav_label(page: str) -> str:
    return f"{PAGES.get(page, ('', ''))[0]} {page}"


# --------------------------------------------------------------------------- #
# Plotly template shared by every chart
# --------------------------------------------------------------------------- #
_template = go.layout.Template(pio.templates["plotly_dark"])
_template.layout.update(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, system-ui, sans-serif", color="#C9D1E0", size=12),
    colorway=[ACCENT, ACCENT_2, WARN, "#F472B6", "#60A5FA", "#A3E635", "#FB7185", "#C084FC"],
    xaxis=dict(gridcolor="#182033", zerolinecolor="#232C40", linecolor="#232C40"),
    yaxis=dict(gridcolor="#182033", zerolinecolor="#232C40", linecolor="#232C40"),
    hoverlabel=dict(bgcolor="#151C2B", bordercolor=BORDER, font=dict(family="Inter", color="#E6EAF2")),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB7C7")),
    title=dict(font=dict(size=15, color="#E6EAF2")),
)
pio.templates["marketmind"] = _template
TEMPLATE = "marketmind"


# --------------------------------------------------------------------------- #
# Global CSS
# --------------------------------------------------------------------------- #
CSS = f"""
<style>
/* layout */
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1280px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
footer {{ visibility: hidden; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}

/* page header */
.mm-hero {{ display:flex; align-items:center; gap:16px; margin: 0 0 1.4rem 0; }}
.mm-hero-icon {{ width:48px; height:48px; border-radius:14px; display:flex; align-items:center; justify-content:center;
  background: linear-gradient(135deg, {ACCENT} 0%, {ACCENT_2} 140%); box-shadow: 0 8px 24px rgba(124,108,255,.35);
  font-family: 'Material Symbols Rounded'; font-size: 26px; color: white; }}
.mm-hero h1 {{ font-size: 1.85rem; font-weight: 800; margin: 0; padding: 0; line-height: 1.15; }}
.mm-hero p {{ margin: 2px 0 0 0; color: {MUTED}; font-size: .95rem; }}

/* metric cards */
[data-testid="stMetric"] {{ background: linear-gradient(180deg, #141B2A 0%, #10161F 100%); border: 1px solid {BORDER};
  border-radius: 16px; padding: 16px 18px; transition: border-color .15s ease, transform .15s ease; }}
[data-testid="stMetric"]:hover {{ border-color: #2C3650; transform: translateY(-1px); }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
[data-testid="stMetricValue"] {{ font-weight: 700; letter-spacing: -0.02em; font-size: clamp(1.25rem, 2.1vw, 1.85rem); }}
[data-testid="stMetricValue"] > div {{ overflow: visible; text-overflow: clip; }}

/* tabs as pills */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; background: #0F1521; padding: 6px; border-radius: 14px; border: 1px solid {BORDER}; width: fit-content; max-width: 100%; overflow-x: auto; }}
.stTabs [data-baseweb="tab"] {{ height: 38px; padding: 0 16px; border-radius: 10px; font-weight: 600; color: {MUTED}; }}
.stTabs [aria-selected="true"] {{ background: rgba(124,108,255,.16); color: #FFFFFF; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}

/* buttons */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{ font-weight: 600; padding: .5rem 1.1rem; transition: all .15s ease; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: linear-gradient(135deg, {ACCENT} 0%, #6352F5 100%); border: 0; box-shadow: 0 6px 18px rgba(124,108,255,.28); }}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); box-shadow: 0 8px 24px rgba(124,108,255,.4); }}

/* containers, forms, expanders, alerts, tables */
[data-testid="stForm"], [data-testid="stExpander"] details, div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ border-radius: 16px; }}
[data-testid="stForm"] {{ background: #0F1521; border: 1px solid {BORDER}; padding: 1.1rem 1.2rem; }}
[data-testid="stExpander"] details {{ background: #0F1521; border: 1px solid {BORDER}; }}
[data-testid="stAlert"] {{ border-radius: 14px; }}
[data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; border: 1px solid {BORDER}; }}
[data-testid="stPlotlyChart"] {{ background: #0F1521; border: 1px solid {BORDER}; border-radius: 16px; padding: 8px 6px; }}

/* sidebar */
[data-testid="stSidebar"] {{ border-right: 1px solid #161D2C; }}
.mm-brand {{ display:flex; align-items:center; gap:12px; margin: 4px 0 18px 4px; }}
.mm-logo {{ width:38px; height:38px; border-radius:11px; background: linear-gradient(135deg, {ACCENT}, {ACCENT_2});
  display:flex; align-items:center; justify-content:center; font-weight:800; color:white; font-size:17px;
  box-shadow: 0 6px 18px rgba(124,108,255,.35); }}
.mm-brand-name {{ font-weight: 800; font-size: 1.12rem; letter-spacing: -0.02em; line-height: 1.1; }}
.mm-brand-tag {{ color: {MUTED}; font-size: .74rem; }}
.mm-user {{ display:flex; align-items:center; gap:10px; padding:10px 12px; border:1px solid #1A2232; border-radius:12px;
  background:#111827; margin: 6px 0 14px 0; }}
.mm-avatar {{ width:30px; height:30px; border-radius:50%; background:#26304A; display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:.85rem; color:#C9D1E0; }}
.mm-user-name {{ font-weight:600; font-size:.88rem; }}
.mm-user-role {{ color:{MUTED}; font-size:.72rem; }}
.mm-section {{ color:#5F6B80; font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; margin: 6px 0 4px 8px; }}
[data-testid="stSidebar"] [data-testid="stRadio"], [data-testid="stSidebar"] [data-testid="stRadioGroup"],
[data-testid="stSidebar"] [role="radiogroup"] {{ width: 100%; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ display: flex; flex-direction: column; gap: 2px; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] {{ width: 100%; display: flex; padding: 8px 12px; border-radius: 10px; margin: 0; transition: background .12s ease; cursor: pointer; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {{ background: #161E2E; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div {{ width: 100%; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child:not([data-testid]) {{ display: none; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:checked) {{ background: rgba(124,108,255,.16); box-shadow: inset 3px 0 0 {ACCENT}; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:checked) p {{ color: #FFFFFF; font-weight: 600; }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{ font-size: .93rem; color: #AEB7C7; }}

/* small UI atoms */
.mm-card {{ background: linear-gradient(180deg, #141B2A 0%, #10161F 100%); border: 1px solid {BORDER}; border-radius: 16px; padding: 16px 18px; height: 100%; }}
.mm-card h4 {{ margin: 0 0 10px 0; font-size: .82rem; color: {MUTED}; text-transform: uppercase; letter-spacing: .05em; font-weight: 700; }}
.mm-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding: 9px 0; border-bottom: 1px solid #182033; font-size: .92rem; }}
.mm-row:last-child {{ border-bottom: 0; }}
.mm-muted {{ color: {MUTED}; font-size: .84rem; }}
.mm-badge {{ display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .74rem; font-weight: 700; white-space: nowrap; }}
.mm-badge.good {{ background: rgba(34,197,94,.14); color: #4ADE80; }}
.mm-badge.bad {{ background: rgba(244,63,94,.14); color: #FB7185; }}
.mm-badge.warn {{ background: rgba(245,158,11,.14); color: #FBBF24; }}
.mm-badge.info {{ background: rgba(124,108,255,.16); color: #B4AAFF; }}
.mm-empty {{ color:{MUTED}; padding: 14px 0; font-size: .9rem; }}

/* auth screen */
.mm-auth-hero h1 {{ font-size: 3rem; font-weight: 800; line-height: 1.05; letter-spacing: -0.03em; margin: .4rem 0 1rem 0;
  background: linear-gradient(120deg, #FFFFFF 10%, #B4AAFF 55%, {ACCENT_2} 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }}
.mm-auth-hero p.lead {{ color: #AEB7C7; font-size: 1.08rem; max-width: 30rem; }}
.mm-feature {{ display:flex; gap:12px; align-items:flex-start; margin: 14px 0; }}
.mm-feature .ico {{ font-family:'Material Symbols Rounded'; font-size:22px; color:{ACCENT}; background: rgba(124,108,255,.12);
  border-radius:10px; width:38px; height:38px; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
.mm-feature b {{ display:block; font-size: .95rem; }}
.mm-feature span {{ color:{MUTED}; font-size:.86rem; }}

/* practice call buttons */
.st-key-pr_Bullish button {{ background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.45); color: #4ADE80; height: 3.2rem; font-size: 1.05rem; }}
.st-key-pr_Bullish button:hover {{ background: rgba(34,197,94,.22); border-color: #22C55E; color: #86EFAC; }}
.st-key-pr_Bearish button {{ background: rgba(244,63,94,.12); border: 1px solid rgba(244,63,94,.45); color: #FB7185; height: 3.2rem; font-size: 1.05rem; }}
.st-key-pr_Bearish button:hover {{ background: rgba(244,63,94,.22); border-color: #F43F5E; color: #FDA4AF; }}
.st-key-pr_Neutral button {{ background: rgba(139,149,167,.10); border: 1px solid rgba(139,149,167,.4); color: #C9D1E0; height: 3.2rem; font-size: 1.05rem; }}
.st-key-pr_Neutral button:hover {{ background: rgba(139,149,167,.2); }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


_ICON_GLYPH = {  # Material Symbols ligature names for the HTML hero icon
    page: icon.removeprefix(":material/").removesuffix(":") for page, (icon, _) in PAGES.items()
}


def page_header(page: str) -> None:
    icon = _ICON_GLYPH.get(page, "insights")
    sub = PAGES.get(page, ("", ""))[1]
    st.markdown(
        f'<div class="mm-hero"><div class="mm-hero-icon">{html.escape(icon)}</div>'
        f"<div><h1>{html.escape(page)}</h1><p>{html.escape(sub)}</p></div></div>",
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "info") -> str:
    return f'<span class="mm-badge {tone}">{html.escape(text)}</span>'


def card(title: str, rows_html: str) -> None:
    """A titled card. ``rows_html`` must already be escaped (use ``row``)."""
    st.markdown(f'<div class="mm-card"><h4>{html.escape(title)}</h4>{rows_html}</div>', unsafe_allow_html=True)


def row(left: str, right_html: str = "", sub: str = "") -> str:
    sub_html = f'<div class="mm-muted">{html.escape(sub)}</div>' if sub else ""
    return f'<div class="mm-row"><div>{html.escape(left)}{sub_html}</div><div>{right_html}</div></div>'


def empty(text: str) -> str:
    return f'<div class="mm-empty">{html.escape(text)}</div>'


def compact(x: float) -> str:
    """12345 → '12.3k', 1_234_567 → '1.23M' (keeps KPI cards from truncating)."""
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:.2f}B"
    if a >= 1e6:
        return f"{x / 1e6:.2f}M"
    if a >= 1e4:
        return f"{x / 1e3:.1f}k"
    return f"{x:,.0f}"
