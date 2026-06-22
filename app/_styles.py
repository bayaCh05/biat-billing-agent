"""Global BIAT IT design system — CSS injection + sidebar branding."""
from __future__ import annotations
import streamlit as st

# ── Brand tokens ──────────────────────────────────────────────────────────────
NAVY  = "#1A3A5C"
NAVY_D = "#14293F"
NAVY_H = "#244E82"
AMBER = "#F0A600"
LB    = "#5BA3C9"
BG    = "#F0F4F9"
OK    = "#1D9E76"
ERR   = "#C0391B"
WARN  = "#F0A600"
PURP  = "#804CD7"

_CSS = """
<style>
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Base ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

/* ── App background ── */
[data-testid="stAppViewContainer"] {
    background: #F0F4F9;
}

/* ── Hide Streamlit chrome ── */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu { display: none !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #1A3A5C !important;
    border-right: none !important;
}
[data-testid="stSidebar"] * {
    color: rgba(255,255,255,0.85) !important;
}
[data-testid="stSidebar"] a {
    text-decoration: none !important;
}
/* Active nav item highlight */
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: #244E82 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    border-left: 3px solid #F0A600 !important;
    color: #fff !important;
}
[data-testid="stSidebarNavLink"] {
    border-radius: 8px !important;
    margin: 1px 8px !important;
    padding: 8px 12px !important;
    transition: background 0.15s;
}
[data-testid="stSidebarNavLink"]:hover {
    background: rgba(255,255,255,0.08) !important;
}
/* Sidebar brand header */
.biat-brand {
    background: #14293F;
    padding: 16px 20px;
    margin: -1rem -1rem 0.5rem -1rem;
    display: flex;
    align-items: center;
    gap: 12px;
}
.biat-logo {
    width: 36px; height: 36px;
    background: #1A3A5C;
    border-radius: 8px;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 4px; flex-shrink: 0;
}
.biat-logo .l1 { width:20px; height:3px; background:#5BA3C9; border-radius:2px; }
.biat-logo .l2 { width:14px; height:3px; background:#F0A600; border-radius:2px; }
.biat-brand-text h3 {
    color: #fff !important; font-size: 15px !important;
    font-weight: 700 !important; margin: 0 !important; line-height: 1.2 !important;
}
.biat-brand-text p {
    color: #5BA3C9 !important; font-size: 11px !important;
    margin: 0 !important;
}
.biat-user {
    background: #14293F;
    padding: 12px 20px;
    margin: 0.5rem -1rem -1rem -1rem;
    display: flex; align-items: center; gap: 10px;
}
.biat-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 600; color: #fff; flex-shrink: 0;
}
.biat-user-info .name { color:#fff !important; font-size:12px !important; font-weight:600 !important; }
.biat-user-info .role { color:#5BA3C9 !important; font-size:11px !important; }

/* ── Page header ── */
.biat-page-header {
    background: #fff;
    border-bottom: 1px solid #D5E8F5;
    padding: 14px 28px;
    margin: -2rem -2rem 1.5rem -2rem;
    display: flex; align-items: center; gap: 14px;
}
.biat-page-header h1 {
    font-size: 18px !important; font-weight: 700 !important;
    color: #1A1A2E !important; margin: 0 !important; flex: 1;
}
.biat-badge {
    padding: 4px 12px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
}
.biat-badge-blue  { background:#E3F0F9; color:#5BA3C9; }
.biat-badge-green { background:#E8F5F0; color:#1D9E76; }
.biat-badge-amber { background:#FFF8E8; color:#F0A600; }
.biat-badge-purp  { background:#F0EBF9; color:#804CD7; }

/* ── KPI cards ── */
[data-testid="metric-container"] {
    background: #fff !important;
    border: 1px solid #D5E8F5 !important;
    border-radius: 12px !important;
    padding: 16px 20px !important;
    box-shadow: 0 1px 4px rgba(26,58,92,0.06) !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 26px !important; font-weight: 700 !important; color: #1A3A5C !important;
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-size: 12px !important; font-weight: 500 !important; color: #5D6D7E !important;
}
[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-size: 11px !important;
}

/* ── Dataframes ── */
[data-testid="stDataFrame"] {
    border-radius: 12px !important;
    overflow: hidden !important;
    border: 1px solid #D5E8F5 !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] [data-testid="stTab"] {
    font-weight: 600 !important;
}

/* ── Buttons ── */
.stButton > button[kind="primary"] {
    background: #1A3A5C !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: background 0.15s !important;
}
.stButton > button[kind="primary"]:hover {
    background: #244E82 !important;
}
.stButton > button[kind="secondary"] {
    border: 1px solid #D5E8F5 !important;
    border-radius: 8px !important;
    color: #1A3A5C !important;
    font-weight: 600 !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: #fff !important;
    border: 1px solid #D5E8F5 !important;
    border-radius: 12px !important;
}

/* ── Inputs ── */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] > div,
[data-testid="stNumberInput"] input {
    border-radius: 8px !important;
    border-color: #D5E8F5 !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stSelectbox"] > div:focus-within {
    border-color: #5BA3C9 !important;
    box-shadow: 0 0 0 2px rgba(91,163,201,0.2) !important;
}

/* ── Alert boxes ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
}

/* ── Divider ── */
hr { border-color: #D5E8F5 !important; }

/* ── Card container helper ── */
.biat-card {
    background: #fff;
    border: 1px solid #D5E8F5;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
</style>
"""


def inject_css() -> None:
    """Inject the global BIAT CSS. Call once per page at the top."""
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar_brand(role: str = "Comptable", initials: str = "BC",
                  avatar_color: str = NAVY) -> None:
    """Render BIAT IT logo + user footer in the sidebar."""
    st.sidebar.markdown(f"""
    <div class="biat-brand">
        <div class="biat-logo">
            <div class="l1"></div>
            <div class="l2"></div>
        </div>
        <div class="biat-brand-text">
            <h3>BIAT IT</h3>
            <p>Facturation</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f"""
    <div class="biat-user">
        <div class="biat-avatar" style="background:{avatar_color};">{initials}</div>
        <div class="biat-user-info">
            <div class="name">{"Baya C." if initials == "BC" else initials}</div>
            <div class="role">{role}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def page_header(title: str, badge: str = "", badge_cls: str = "biat-badge-blue") -> None:
    """Render a clean white page header with optional badge."""
    badge_html = f'<span class="biat-badge {badge_cls}">{badge}</span>' if badge else ""
    st.markdown(f"""
    <div class="biat-page-header">
        <h1>{title}</h1>
        {badge_html}
    </div>
    """, unsafe_allow_html=True)
