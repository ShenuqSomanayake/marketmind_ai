"""Patterns & levels tab: detected chart patterns, their track record, support/resistance and Fibonacci."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import patterns as P
from ..data import DataError
from ..technicals import cluster_levels, fibonacci
from .common import DOWN, UP, cached_history, pct
from .style import TEMPLATE

SHAPE_COLOURS = {1: UP, -1: DOWN, 0: "#E2C044"}


@st.cache_data(show_spinner="Scanning for patterns…", max_entries=32)
def cached_scan(df: pd.DataFrame) -> P.ScanResult:
    return P.scan(df)


def forming_rows(res: P.ScanResult, n: int) -> list[dict]:
    rows = []
    for c in res.forming:
        if c.name.endswith("triangle"):
            up, lo = c.line_at(n - 1, c.upper), c.line_at(n - 1, c.lower)
            trigger = f"close above {up:,.2f} (up) or below {lo:,.2f} (down)"
        else:
            neck = c.line_at(n - 1)
            trigger = f"close {'below' if c.direction < 0 else 'above'} {neck:,.2f}"
        rows.append({"Pattern": c.name, "Confirms on": trigger, "Started": c.points[0][0]})
    return rows


def pattern_chart(
    d: pd.DataFrame, res: P.ScanResult, window: int, show_levels: bool, show_fib: bool, show_pivots: bool, title: str
) -> go.Figure:
    n = len(d)
    start = max(0, n - window)
    v = d.iloc[start:]
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=v.date, open=v.open, high=v.high, low=v.low, close=v.close, name="Price", showlegend=False))
    date = d["date"]

    if show_pivots:
        pv = [p for p in res.pivots if p.idx >= start]
        if pv:
            fig.add_trace(go.Scatter(x=[p.date for p in pv], y=[p.price for p in pv], mode="lines+markers", name="Swings",
                                     line=dict(color="rgba(200,200,200,.45)", width=1), marker=dict(size=4)))  # fmt: skip

    shown = set()
    for e in res.events:
        if e.confirmed_at < start:
            continue
        col = SHAPE_COLOURS[e.direction]
        legend = e.name not in shown
        shown.add(e.name)
        if e.points:
            fig.add_trace(go.Scatter(x=[date.iloc[i] for i, _ in e.points], y=[p for _, p in e.points], mode="lines",
                                     line=dict(color=col, width=2), name=e.name, legendgroup=e.name, showlegend=legend,
                                     hovertemplate=f"{e.name}<extra></extra>"))  # fmt: skip
        fig.add_trace(go.Scatter(x=[e.date], y=[e.price], mode="markers", legendgroup=e.name, showlegend=False,
                                 marker=dict(symbol="triangle-up" if e.direction > 0 else "triangle-down", size=13, color=col,
                                             line=dict(color="white", width=1)),
                                 hovertemplate=f"<b>{e.name}</b><br>{e.direction_word} · confirmed {e.date:%Y-%m-%d}<br>close %{{y:,.2f}}<extra></extra>"))  # fmt: skip
    for c in res.forming:
        x = [date.iloc[i] for i, _ in c.points if i >= start]
        y = [p for i, p in c.points if i >= start]
        if x:
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color="#E2C044", width=2, dash="dot"),
                                     name=f"{c.name} (forming)"))  # fmt: skip

    if show_levels:
        recent = [p for p in res.pivots if n - 1 - p.idx <= P.LEVEL_LOOKBACK]
        for lv in cluster_levels(recent, float(d.close.iloc[-1]), d.date.iloc[-1])[:6]:
            fig.add_hline(y=lv.price, line_dash="dash", line_width=1, line_color=UP if lv.kind == "support" else DOWN,
                          annotation_text=f"{lv.kind} {lv.price:,.2f} ({lv.touches}×)", annotation_position="top left",
                          annotation_font_size=10)  # fmt: skip
    if show_fib:
        fib = fibonacci(d)
        if fib:
            for name, price in fib["levels"].items():
                fig.add_hline(y=price, line_dash="dot", line_width=1, line_color="#B27BD6",
                              annotation_text=f"Fib {name} {price:,.2f}", annotation_position="bottom right", annotation_font_size=10)  # fmt: skip

    fig.update_layout(template=TEMPLATE, height=560, xaxis_rangeslider_visible=False, title=dict(text=title, x=0, font=dict(size=15)),
                      legend=dict(orientation="h", yanchor="top", y=-0.08), margin=dict(l=10, r=10, t=50, b=10))  # fmt: skip
    return fig


def render(ticker: str, d: pd.DataFrame, fetched: bool = False) -> None:
    res = cached_scan(d)
    n = len(d)
    st.caption(
        "Patterns are found by fixed geometric rules, walking forward one bar at a time, so each is marked on the first bar "
        "a live observer could have confirmed it (no hindsight). ▲ bullish, ▼ bearish, dotted yellow = still forming."
    )
    c = st.columns(5)
    window = c[0].selectbox("Chart window", [120, 250, 500, 1000], index=1, key="pt_win", format_func=lambda x: f"{x} bars")
    show_levels = c[1].toggle("Support/resistance", value=True, key="pt_lv")
    show_fib = c[2].toggle("Fibonacci", value=False, key="pt_fib")
    show_pivots = c[3].toggle("Swing points", value=False, key="pt_piv")
    c[4].metric("Patterns found", len(res.events), f"{len(res.forming)} forming", delta_color="off", delta_arrow="off")
    st.plotly_chart(
        pattern_chart(d, res, int(window), show_levels, show_fib, show_pivots, f"{ticker} · patterns & levels"), width="stretch"
    )

    fr = forming_rows(res, n)
    if fr:
        st.subheader("Forming now")
        for r in fr:
            st.info(f"**{r['Pattern']}** — confirms on a {r['Confirms on']}.")

    st.subheader("Recent patterns")
    recent = [e for e in res.events if e.confirmed_at >= n - 250]
    if recent:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Confirmed": e.date.date(),
                        "Pattern": e.name,
                        "Direction": e.direction_word,
                        "Close": round(e.price, 2),
                        "Level": None if e.level is None else round(e.level, 2),
                        "Bars ago": n - 1 - e.confirmed_at,
                    }
                    for e in reversed(recent)
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.write("No patterns confirmed in the last 250 bars.")

    st.subheader("Has this pattern actually worked on this asset?")
    a, b = st.columns(2)
    hz = a.selectbox("Look-ahead", [5, 10, 20, 60], index=2, key="pt_hz", format_func=lambda x: f"{x} bars")
    thr = b.number_input("Counts as worked if it moved more than ±%", 0.5, 20.0, 2.0, 0.5, key="pt_thr")
    hist, hist_res, basis = d, res, f"the {len(d):,} loaded bars"
    if fetched and st.toggle("Measure on up to 10 years of daily history", value=True, key="pt_long",
                             help="More history = more occurrences = a fairer verdict. Uses daily bars."):  # fmt: skip
        try:
            long_df = cached_history(ticker, "10y", "1d")
            if len(long_df) > len(d):
                hist, hist_res, basis = (
                    long_df,
                    cached_scan(long_df),
                    f"{len(long_df):,} daily bars ({long_df.date.iloc[0]:%Y} to {long_df.date.iloc[-1]:%Y})",
                )
        except (DataError, ValueError) as e:
            st.caption(f"Longer history unavailable ({e}); using the loaded data.")
    st.caption(f"Measured on {basis}.")
    tr = P.track_record(hist, hist_res.events, int(hz), float(thr))
    if tr.empty:
        st.write("Not enough history after the patterns to measure outcomes.")
    else:
        show = tr.copy()
        for col in ("Worked", "Base rate"):
            show[col] = show[col].map(lambda x: pct(x, 0))
        show["Edge (pts)"] = show["Edge (pts)"].map(lambda x: f"{x:+.0f}")
        show["z"] = show["z"].map(lambda x: f"{x:+.2f}")
        show["Avg move after"] = show["Avg move after"].map(lambda x: pct(x, 1, sign=True))
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption(
            f"**Worked** = after confirmation, price moved more than ±{thr:g}% in the pattern's direction within {hz} bars. "
            f"**Base rate** = how often ANY bar on this asset was followed by that move. **Edge** = the difference. "
            f"**z** tests whether the edge could be luck: beyond ±1.96 is unlikely to be chance (needs {P.MIN_EVENTS}+ occurrences). "
            "Occurrences close together overlap, so treat small edges with suspicion. Past behaviour is no guarantee."
        )
    with st.expander("How each pattern is defined"):
        st.dataframe(
            pd.DataFrame({"Pattern": list(P.DESCRIPTIONS), "Rule": list(P.DESCRIPTIONS.values())}),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            f"Swing points need {P.PIVOT_K} bars on each side and a move of at least {P.MIN_SWING_ATR}× ATR from the previous swing. "
            f"Double-top peaks within {P.PEAK_TOL:.0%}; shoulders within {P.SHOULDER_TOL:.0%}; breakouts need a {P.BREAK_MARGIN:.1%} close "
            f"beyond the level on {P.BREAK_VOLUME}× average volume."
        )
