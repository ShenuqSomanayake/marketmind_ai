from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ..backtest import StrategyParams, run_backtest
from .common import pct, require_dataset
from .style import TEMPLATE


def render() -> None:
    ds = require_dataset()
    if ds is None:
        return
    st.caption(
        f"**{ds.ticker}** · Enter when the fast EMA crosses above the slow EMA with RSI above the threshold; exit on the "
        "reverse cross. Signals use bar *t*'s close and trade from bar *t+1*. Long-only, fully invested when in."
    )
    with st.form("bt"):
        a, b, c = st.columns(3)
        fast = a.number_input("Fast EMA", 2, 200, 20)
        slow = b.number_input("Slow EMA", 3, 400, 50)
        rmin = c.number_input("RSI entry threshold", 0.0, 100.0, 50.0)
        d, e, f = st.columns(3)
        fee = d.number_input("Fee per trade (bps)", 0.0, 200.0, 10.0)
        slip = e.number_input("Slippage per trade (bps)", 0.0, 200.0, 5.0)
        oos = f.slider("Out-of-sample share", 0.0, 0.5, 0.3, 0.05, help="Last part of the history, reported separately.")
        run = st.form_submit_button("Run backtest", type="primary")
    if run:
        try:
            params = StrategyParams(int(fast), int(slow), 14, rmin, fee, slip)
            st.session_state["backtest_result"] = run_backtest(ds.df, params, oos)
        except ValueError as e:
            st.error(str(e))
            return
    res = st.session_state.get("backtest_result")
    if not res:
        return

    s, bh = res["full"], res["benchmark"]
    m = st.columns(5)
    m[0].metric(
        "Strategy return", pct(s["total_return"]), f"{(s['total_return'] - bh['total_return']) * 100:+.2f} pts vs buy & hold"
    )
    m[1].metric("Buy & hold return", pct(bh["total_return"]))
    m[2].metric("Max drawdown", pct(s["max_drawdown"]), f"B&H {pct(bh['max_drawdown'])}", delta_color="off", delta_arrow="off")
    m[3].metric("Sharpe", f"{s['sharpe']:.2f}", f"B&H {bh['sharpe']:.2f}", delta_color="off", delta_arrow="off")
    m[4].metric(
        "Win rate (closed)", pct(res["win_rate"], 0), f"{len(res['trades'])} trades", delta_color="off", delta_arrow="off"
    )

    ser = res["series"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ser.date, y=ser.strategy_equity, name="Strategy"))
    fig.add_trace(go.Scatter(x=ser.date, y=ser.benchmark_equity, name="Buy & hold", line=dict(dash="dot")))
    if res["split_date"] is not None:
        fig.add_vline(x=res["split_date"], line_dash="dash", line_color="#999")
        fig.add_annotation(x=res["split_date"], y=1, yref="paper", text="out-of-sample →", showarrow=False, xanchor="left")
    fig.update_layout(template=TEMPLATE, height=380, title="Growth of $1", margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Metrics by segment")
    t = res["table"].copy()
    for col in ("total_return", "cagr", "volatility", "max_drawdown", "exposure"):
        t[col] = t[col].map(lambda x: pct(x))
    for col in ("sharpe", "sortino"):
        t[col] = t[col].map(lambda x: f"{x:.2f}")
    labels = {"segment": "Segment", "series": "Series", "total_return": "Total return", "cagr": "CAGR", "volatility": "Volatility",
              "sharpe": "Sharpe", "sortino": "Sortino", "max_drawdown": "Max drawdown", "exposure": "Exposure", "trades": "Trades"}  # fmt: skip
    st.dataframe(t.rename(columns=labels), width="stretch", hide_index=True)

    oos_rows = res["table"][(res["table"].segment == "Out-of-sample") & (res["table"].series == "Strategy")]
    if len(oos_rows) and oos_rows["trades"].iloc[0] < 3:
        st.warning("Fewer than 3 trades out-of-sample — far too few to judge the strategy.")
    if s["total_return"] < bh["total_return"]:
        st.info("The strategy under-performed simply holding the asset over the full period.")

    with st.expander(f"Trade list ({len(res['trades'])})"):
        tr = res["trades"].copy()
        if len(tr):
            tr["gross_return"] = tr["gross_return"].map(pct)
        st.dataframe(tr, width="stretch", hide_index=True)
    st.caption(
        f"Annualised with {res['periods_per_year']:g} periods/year. Excludes taxes, dividends beyond adjusted prices, "
        "borrowing and survivorship bias. If you tune parameters while watching the out-of-sample numbers, they stop being out-of-sample."
    )
