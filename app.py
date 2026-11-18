"""MarketMind AI — Streamlit entry point: authentication, app shell and navigation only."""

from __future__ import annotations

import html

import streamlit as st

from marketmind import __version__
from marketmind.auth import AuthError, authenticate, create_user, get_user
from marketmind.db import connect
from marketmind.ui import analyse, backtest, insights, misc, portfolio, practice, style, trading

st.set_page_config(page_title="MarketMind AI", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
style.inject()

PAGES = {
    "Overview": misc.render_overview,
    "Analyse": analyse.render,
    "Backtest": backtest.render,
    "Portfolio": portfolio.render,
    "Paper trading": trading.render_paper,
    "Predictions": trading.render_predictions,
    "Practice": practice.render,
    "Report card": insights.render,
    "Journal": misc.render_journal,
    "Settings": misc.render_settings,
}

FEATURES = [
    ("school", "A report card for your decisions", "See if you chase run-ups, sell winners early or beat a lazy baseline."),
    ("sports_esports", "Practice on real history", "Call blind historical charts and get scored instantly."),
    ("query_stats", "Patterns with a track record", "Every detected pattern is tested against the base rate."),
    ("verified", "AI that can't make numbers up", "Every figure the AI writes is checked against computed facts."),
]


def auth_screen() -> None:
    left, _, right = st.columns([1.15, 0.1, 1])
    with left:
        st.markdown(
            '<div class="mm-brand"><div class="mm-logo">M</div><div><div class="mm-brand-name">MarketMind AI</div>'
            '<div class="mm-brand-tag">Evidence-led investing journal</div></div></div>'
            '<div class="mm-auth-hero"><h1>The investing journal<br>that grades you.</h1>'
            '<p class="lead">Record your views before outcomes are known. MarketMind scores them objectively and shows you '
            "the patterns in your own decisions.</p></div>"
            + "".join(
                f'<div class="mm-feature"><div class="ico">{ico}</div><div><b>{html.escape(t)}</b><span>{html.escape(d)}</span></div></div>'
                for ico, t, d in FEATURES
            ),
            unsafe_allow_html=True,
        )
    with right:
        st.write("")
        with st.form("login"):
            st.markdown("#### Sign in")
            u = st.text_input("Username", key="login_user")
            p = st.text_input("Password", type="password", key="login_pass")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                try:
                    with connect() as con:
                        st.session_state["user"] = authenticate(con, u, p)
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
        with st.form("register"):
            st.markdown("#### New here? Create an account")
            nu = st.text_input("Username", key="new_user")
            npw = st.text_input("Password (12+ characters)", type="password", key="new_pass")
            npw2 = st.text_input("Confirm password", type="password", key="new_pass2")
            if st.form_submit_button("Create account", width="stretch"):
                try:
                    with connect() as con:
                        st.session_state["user"] = create_user(con, nu, npw, npw2)
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
        st.caption("Accounts live in a local database on the machine running this app. Not financial advice.")


def sidebar(user, pages: list[str]) -> str:
    with st.sidebar:
        st.markdown(
            '<div class="mm-brand"><div class="mm-logo">M</div><div><div class="mm-brand-name">MarketMind AI</div>'
            f'<div class="mm-brand-tag">v{html.escape(__version__)} · not financial advice</div></div></div>'
            f'<div class="mm-user"><div class="mm-avatar">{html.escape(user.username[:1].upper())}</div><div>'
            f'<div class="mm-user-name">{html.escape(user.username)}</div>'
            f'<div class="mm-user-role">{"Administrator" if user.is_admin else "Member"}</div></div></div>'
            '<div class="mm-section">Workspace</div>',
            unsafe_allow_html=True,
        )
        page = st.radio("Workspace", pages, key="nav", label_visibility="collapsed", format_func=style.nav_label)
        ds = st.session_state.get("dataset")
        if ds is not None:
            st.markdown(
                f'<div class="mm-section" style="margin-top:18px">Loaded asset</div>'
                f'<div class="mm-user"><div class="mm-avatar" style="background:rgba(124,108,255,.18);color:#B4AAFF">'
                f'{html.escape(ds.ticker[:1])}</div><div><div class="mm-user-name">{html.escape(ds.ticker)}</div>'
                f'<div class="mm-user-role">{len(ds.df):,} bars</div></div></div>',
                unsafe_allow_html=True,
            )
        st.write("")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()
    return page


def main() -> None:
    if "user" not in st.session_state:
        auth_screen()
        st.stop()
    # Re-load the user every run so role changes and deletions take effect immediately.
    with connect() as con:
        user = get_user(con, st.session_state["user"].id)
    if user is None:
        st.session_state.clear()
        st.rerun()
    st.session_state["user"] = user

    pages = dict(PAGES)
    if user.is_admin:
        pages["Admin"] = misc.render_admin
    page = sidebar(user, list(pages))
    style.page_header(page)
    pages[page]()


main()
