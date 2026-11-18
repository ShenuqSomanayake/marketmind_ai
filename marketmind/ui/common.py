"""Shared Streamlit helpers: cached data access, the active dataset and charts."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .. import data
from ..auth import User
from ..config import factual_mode
from .style import DOWN, TEMPLATE, UP  # noqa: E402  (re-exported for other pages)


@dataclass
class Dataset:
    df: pd.DataFrame
    ticker: str
    source: str


def current_user() -> User:
    return st.session_state["user"]


def get_dataset() -> Dataset | None:
    return st.session_state.get("dataset")


def set_dataset(ds: Dataset) -> None:
    st.session_state["dataset"] = ds
    st.session_state.pop("backtest_result", None)


def require_dataset() -> Dataset | None:
    ds = get_dataset()
    if ds is None:
        st.info("Load an asset on **Analyse** first (upload a CSV or fetch market data).")
    return ds


@st.cache_data(ttl=900, show_spinner="Fetching market data…")
def cached_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return data.fetch_history(ticker, period, interval)


@st.cache_data(ttl=900, show_spinner="Refreshing prices…")
def cached_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    return data.latest_prices(list(tickers))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_since(ticker: str, start: str) -> pd.DataFrame:
    return data.fetch_history_since(ticker, start)


def price_chart(d: pd.DataFrame, ticker: str) -> go.Figure:
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.13, 0.16, 0.16],
        subplot_titles=(f"{ticker} · price & trend", "Volume", "RSI (14)", "MACD (12, 26, 9)"),
    )
    fig.add_trace(go.Candlestick(x=d.date, open=d.open, high=d.high, low=d.low, close=d.close, name="Price"), row=1, col=1)
    for col, name, color in [("ema20", "EMA 20", "#24B8D6"), ("ema50", "EMA 50", "#F28E2B"), ("sma200", "SMA 200", "#B27BD6")]:
        fig.add_trace(go.Scatter(x=d.date, y=d[col], name=name, line=dict(color=color, width=1.5)), row=1, col=1)
    band = dict(color="rgba(180,180,180,.5)", dash="dot", width=1)
    fig.add_trace(go.Scatter(x=d.date, y=d.bb_upper, name="BB upper", line=band), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=d.date, y=d.bb_lower, name="BB lower", line=band, fill="tonexty", fillcolor="rgba(150,150,150,.07)"),
        row=1,
        col=1,
    )
    colors = [UP if c >= o else DOWN for o, c in zip(d.open, d.close, strict=True)]
    fig.add_trace(go.Bar(x=d.date, y=d.volume, name="Volume", marker_color=colors, showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=d.date, y=d.rsi14, name="RSI", line=dict(color="#E2C044")), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color=DOWN, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color=UP, row=3, col=1)
    fig.add_trace(
        go.Bar(x=d.date, y=d.macd_hist, name="MACD hist", marker_color=[UP if x >= 0 else DOWN for x in d.macd_hist.fillna(0)]),
        row=4,
        col=1,
    )
    fig.add_trace(go.Scatter(x=d.date, y=d.macd, name="MACD", line=dict(color="#38A9E0")), row=4, col=1)
    fig.add_trace(go.Scatter(x=d.date, y=d.macd_signal, name="Signal", line=dict(color="#E88B40")), row=4, col=1)
    fig.update_layout(
        height=820,
        template=TEMPLATE,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="top", y=-0.04, x=0),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    return fig


def pct(x, digits=2, sign=False) -> str:
    if x is None or x != x:
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def headline(rep: dict) -> str:
    """The one-line summary of a technical report, respecting factual mode."""
    return rep["rules_summary"] if factual_mode() else rep["label"]


def run_ai(generate, fallback):
    """Run an AI generation within the user's daily quota; use the rules-based ``fallback`` once it's spent.

    ``generate`` and ``fallback`` are zero-argument callables returning a ``research.Brief``.
    """
    from .. import usage
    from ..db import connect

    uid = current_user().id
    with connect() as con:
        left = usage.remaining(con, uid)
    if left == 0:
        b = fallback()
        b.markdown = "_Daily AI limit reached; showing the rules-based version. It resets at 00:00 UTC._\n\n" + b.markdown
        return b
    b = generate()
    if b.source == "llm":
        with connect() as con:
            usage.record(con, uid)
    return b
