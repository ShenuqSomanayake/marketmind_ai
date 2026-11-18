"""Report card: what the user's own track record says about their decisions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import insights, research
from ..db import connect
from ..engine import analyse
from .common import cached_history, current_user, pct, run_ai

_BOX = {"good": st.success, "warn": st.warning, "info": st.info}


def _show(findings: list[insights.Finding]) -> None:
    for f in findings:
        _BOX[f.tone](f"**{f.title}** — {f.detail}  \n_Based on {f.n} record(s)._")


def _predictions(uid: int) -> None:
    which = st.radio(
        "Which predictions",
        ["Live", "Practice", "Both"],
        horizontal=True,
        key="rc_mode",
        help="Live calls are real-time and harder; practice calls are on historical charts. They're kept apart by default.",
    )
    modes = {"Live": ("live",), "Practice": ("practice",), "Both": ("live", "practice")}[which]
    with connect() as con:
        rows = con.execute(
            "SELECT prediction,outcome,realised_return,threshold_pct,score,ret20_at_entry,horizon_bars,mode,patterns_at_entry "
            "FROM prediction_log WHERE user_id=?",
            (uid,),
        ).fetchall()
    cols = [
        "view",
        "outcome",
        "realised_return",
        "threshold_pct",
        "score",
        "ret20_at_entry",
        "horizon_bars",
        "mode",
        "patterns_at_entry",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df = df[df["mode"].isin(modes)].drop(columns="mode")
    rep = insights.prediction_report(df)
    if rep["n"] == 0:
        st.info(
            "No scored predictions here yet. Try **Practice** for an instant report card, or log live calls on **Predictions** "
            "(they're graded automatically once their horizon passes)."
        )
        return
    a, b = st.columns(2)
    a.metric("Hit rate", pct(rep["hit_rate"], 0), f"{rep['n']} scored", delta_color="off", delta_arrow="off")
    b.metric("Pending", int((df.outcome == "Pending").sum()))
    _show(rep["findings"])
    if len(rep["by_view"]):
        v = rep["by_view"].copy()
        v["hit_rate"] = v["hit_rate"].map(lambda x: pct(x, 0))
        v["avg_move"] = v["avg_move"].map(lambda x: pct(x, 1, sign=True))
        st.dataframe(
            v.rename(columns={"view": "View", "calls": "Calls", "hit_rate": "Hit rate", "avg_move": "Avg. move after"}),
            hide_index=True,
        )
    if len(rep.get("by_pattern", [])):
        st.markdown("**Your calls on charts that contained a pattern**")
        bp = rep["by_pattern"].copy()
        bp["hit_rate"] = bp["hit_rate"].map(lambda x: pct(x, 0))
        st.dataframe(
            bp.rename(columns={"pattern": "Pattern on chart", "calls": "Calls", "hit_rate": "Your hit rate"}), hide_index=True
        )


def _trading(uid: int) -> None:
    with connect() as con:
        rows = con.execute(
            "SELECT created_at,ticker,side,quantity,price,fee,currency FROM paper_trades WHERE user_id=? ORDER BY created_at,id",
            (uid,),
        ).fetchall()
    trades = pd.DataFrame(rows, columns=["created_at", "ticker", "side", "quantity", "price", "fee", "currency"])
    rep = insights.trading_report(trades)
    _show(rep["findings"])
    if rep["n"]:
        s = rep["sells"].copy()
        s["return"] = s["return"].map(lambda x: pct(x, 1, sign=True))
        s["days_held"] = s["days_held"].round(1)
        st.dataframe(s.rename(columns=str.title), hide_index=True, width="stretch")


def _theses(uid: int) -> None:
    with connect() as con:
        rows = con.execute(
            "SELECT id,ticker,thesis,invalidation,review_date,entry_price,stop_below,stop_above,created_at FROM theses "
            "WHERE user_id=? AND status IN ('Active','Under review') ORDER BY review_date",
            (uid,),
        ).fetchall()
    if not rows:
        st.info("No active theses. Write one in **Journal**, and add a price trigger to get automatic checks.")
        return
    keys = ["id", "ticker", "thesis", "invalidation", "review_date", "entry_price", "stop_below", "stop_above", "created_at"]
    for row in rows:
        t = dict(zip(keys, row, strict=True))
        try:
            hist = cached_history(t["ticker"], "1y", "1d")
            report = analyse(hist)
            close = report["close"]
        except Exception as e:
            report, close = None, None
            st.caption(f"{t['ticker']}: price unavailable ({e}).")
        status = insights.check_thesis(close, t["stop_below"], t["stop_above"], t["review_date"])
        t["trigger_status"] = f"{status.status}: {status.detail}"
        with st.container(border=True):
            head = f"**{t['ticker']}** · {status.status}"
            if t["entry_price"] and close:
                head += f" · {pct(close / t['entry_price'] - 1, 1, sign=True)} since written"
            st.markdown(head)
            _BOX[status.tone](status.detail)
            with st.expander("Your thesis"):
                st.write(t["thesis"])
                st.caption(f"Proves it wrong: {t['invalidation']}")
            if report is not None and st.button("Review this thesis against the data", key=f"rev_{t['id']}"):
                facts = research.build_facts(t["ticker"], report)
                with st.spinner("Reviewing…"):
                    st.session_state[f"thesis_rev_{t['id']}"] = run_ai(
                        lambda t=t, facts=facts: research.thesis_review(t, facts),
                        lambda t=t, facts=facts: research.rules_thesis_review(t, facts),
                    )
            b = st.session_state.get(f"thesis_rev_{t['id']}")
            if b:
                st.caption(f"Reviewed by {b.model}" if b.source == "llm" else "Rules-based review (no language model used)")
                if b.unverified_numbers:
                    st.error("Unverified numbers: " + ", ".join(b.unverified_numbers))
                st.markdown(b.markdown)
    st.caption(
        "When an API key is configured, the AI review sends this thesis's text and the computed facts for its ticker to Anthropic."
    )


def render() -> None:
    uid = current_user().id
    st.caption(
        "What your own records say about your decisions. These are observations about your past choices, "
        "not recommendations. Small samples are mostly noise, so every finding shows how many records it's based on."
    )
    t1, t2, t3 = st.tabs(["Prediction report card", "Trading habits", "Thesis checker"])
    with t1:
        _predictions(uid)
    with t2:
        _trading(uid)
    with t3:
        _theses(uid)
