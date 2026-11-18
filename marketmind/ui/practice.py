"""Practice page: call historical charts and get scored instantly."""

from __future__ import annotations

import secrets

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from .. import patterns as P
from .. import practice
from ..data import DataError, clean_ticker
from ..db import connect
from ..predictions import DIRECTIONS
from . import patterns as patterns_ui
from .common import cached_history, current_user, get_dataset, headline, pct, price_chart
from .style import TEMPLATE

KEY = "practice_state"


def _new_round(source: str, custom: str, horizon: int, blind: bool) -> None:
    rng = np.random.default_rng(secrets.randbits(64))
    ds = get_dataset()
    if source == "My loaded asset" and ds is not None:
        ticker, df = ds.ticker, ds.df
    else:
        ticker = clean_ticker(custom) if source == "Choose a ticker" else str(rng.choice(practice.DEFAULT_UNIVERSE))
        df = cached_history(ticker, "10y", "1d")
    st.session_state[KEY] = {"round": practice.pick_round(df, ticker, horizon, rng, blind=blind), "result": None}


def _reveal_chart(r: practice.Round) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r.visible.date, y=r.visible.close, name="What you saw", line=dict(color="#4EA1FF")))
    joined_x = [r.visible.date.iloc[-1], *r.future.date]
    joined_y = [r.visible.close.iloc[-1], *r.future.close]
    fig.add_trace(go.Scatter(x=joined_x, y=joined_y, name="What happened next", line=dict(color="#F28E2B", width=3)))
    fig.add_vline(x=r.visible.date.iloc[-1], line_dash="dash", line_color="#999")
    fig.update_layout(template=TEMPLATE, height=360, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
    return fig


def _record(r: practice.Round, view: str, thr: float, rep: dict, ev) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO prediction_log(user_id,ticker,prediction,score,reference_price,as_of,horizon_bars,threshold_pct,"
            "ret20_at_entry,rsi_at_entry,outcome,realised_return,evaluated_at,mode,notes,patterns_at_entry) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,'practice',?,?)",
            (
                current_user().id,
                r.ticker,
                view,
                rep["score"],
                r.real_reference_price,
                r.real_as_of.isoformat(),
                r.horizon,
                thr,
                None if rep["return_20"] != rep["return_20"] else rep["return_20"],
                rep["rsi"],
                ev.outcome,
                ev.realised_return,
                "blind" if r.blind else "",
                P.encode_tags(practice.pattern_tags(r)),
            ),
        )


def render() -> None:
    st.caption(
        "Make calls on real historical charts and get scored instantly. Everything you see is computed only from bars "
        "before the cut-off, so there's no peeking. Practice results build your **Report card** right away and are kept "
        "separate from live predictions."
    )
    with st.expander("Round settings", expanded=KEY not in st.session_state):
        a, b = st.columns(2)
        source = a.radio("Chart source", ["Random well-known stock", "My loaded asset", "Choose a ticker"], key="pr_src")
        custom = b.text_input("Ticker (for 'Choose a ticker')", value="AAPL", key="pr_tk")
        c, d, e = st.columns(3)
        horizon = c.selectbox("Horizon (trading days)", [5, 10, 20, 60], index=2, key="pr_hz")
        thr = d.number_input("Threshold ±%", 0.0, 20.0, 2.0, 0.5, key="pr_thr")
        blind = e.toggle("Blind mode", value=True, key="pr_blind", help="Hide the ticker and dates and rebase prices to 100.")
        e.toggle(
            "Pattern hints",
            value=False,
            key="pr_hints",
            help="Overlay detected chart patterns and levels before you call. Off = test your own eye; the report card still "
            "records which patterns were present either way.",
        )
    if st.button("New round", type="primary"):
        try:
            _new_round(source, custom, int(horizon), blind)
        except (DataError, ValueError) as err:
            st.error(str(err))
    state = st.session_state.get(KEY)
    if not state:
        return
    r: practice.Round = state["round"]
    rep = practice.snapshot(r)
    name = "Mystery stock" if r.blind and state["result"] is None else r.ticker
    st.subheader(f"{name} · where will it be in {r.horizon} trading days?")
    m = st.columns(4)
    m[0].metric("Last close", f"{rep['close']:,.2f}")
    m[1].metric("Rule score", f"{rep['score']}/100", headline(rep), delta_color="off", delta_arrow="off")
    m[2].metric("RSI 14", f"{rep['rsi']:.1f}")
    m[3].metric("20-bar return", pct(rep["return_20"], sign=True))

    tags = practice.pattern_tags(r)
    if state["result"] is None:
        if st.session_state.get("pr_hints"):
            res = patterns_ui.cached_scan(r.visible)
            st.plotly_chart(
                patterns_ui.pattern_chart(r.visible, res, len(r.visible), True, False, False, f"{name} · pattern hints"),
                width="stretch",
            )
            st.caption("Patterns at the cut-off: " + (", ".join(P.describe_tags(tags)) or "none detected"))
        else:
            st.plotly_chart(price_chart(rep["data"], name), width="stretch")
        st.write(f"Bullish = up more than {thr:g}% · Bearish = down more than {thr:g}% · Neutral = within ±{thr:g}%")
        cols = st.columns(3)
        for col, view in zip(cols, DIRECTIONS, strict=True):
            if col.button(view, key=f"pr_{view}", width="stretch"):
                ev = practice.score(r, view, float(thr))
                _record(r, view, float(thr), rep, ev)
                state["result"] = (view, ev, float(thr))
                tally = st.session_state.setdefault("practice_tally", [])
                tally.append(ev.outcome)
                st.rerun()
        return

    view, ev, used_thr = state["result"]
    (st.success if ev.outcome == "Correct" else st.error)(
        f"**{ev.outcome}.** You said {view}; price moved {pct(ev.realised_return, 1, sign=True)} over {r.horizon} days "
        f"(threshold ±{used_thr:g}%)."
    )
    st.plotly_chart(_reveal_chart(r), width="stretch")
    st.caption("Patterns detected at the cut-off: " + (", ".join(P.describe_tags(tags)) or "none"))
    if r.blind:
        st.caption(f"It was **{r.ticker}**; the cut-off was {r.real_as_of.date()} at {r.real_reference_price:,.2f}.")
    tally = st.session_state.get("practice_tally", [])
    if tally:
        st.metric("This session", f"{tally.count('Correct')}/{len(tally)} correct")
    st.caption("Press **New round** for another. See patterns across all your calls on **Report card → Practice**.")
