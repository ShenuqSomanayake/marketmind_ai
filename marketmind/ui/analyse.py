from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import fundamentals as fund
from .. import research
from ..data import DataError, clean_ticker, ticker_from_filename
from ..engine import analyse, annualised_volatility, normalize_ohlcv, unusual_activity
from ..technicals import technical_summary
from . import patterns as patterns_ui
from .common import Dataset, cached_history, get_dataset, headline, pct, price_chart, run_ai, set_dataset


def _load_controls() -> None:
    mode = st.radio("Data source", ["Fetch market data", "Upload CSV"], horizontal=True, key="an_mode")
    if mode == "Upload CSV":
        up = st.file_uploader("CSV with Date, Open, High, Low, Close, Volume", type=["csv"], key="an_upload")
        guess = ticker_from_filename(up.name) if up else None
        t = st.text_input(
            "Ticker for this file",
            value=guess or "",
            key="an_csv_ticker",
            help="Used to label predictions and fetch later prices.",
        )
        if up and st.button("Load file", type="primary"):
            try:
                df = normalize_ohlcv(pd.read_csv(up))
                set_dataset(Dataset(df, clean_ticker(t), f"CSV · {up.name}"))
            except (ValueError, DataError) as e:
                st.error(str(e))
    else:
        a, b, c = st.columns([2, 1, 1])
        t = a.text_input("Ticker", value="NVDA", key="an_ticker", help="Yahoo symbols, e.g. NVDA, BHP.AX, ^GSPC")
        period = b.selectbox("History", ["6mo", "1y", "2y", "5y", "10y", "max"], index=2, key="an_period")
        interval = c.selectbox("Interval", ["1d", "1wk", "1mo", "1h"], key="an_interval")
        if st.button("Fetch", type="primary"):
            try:
                tk = clean_ticker(t)
                set_dataset(
                    Dataset(
                        cached_history(tk, period, interval), tk, f"Yahoo Finance (yfinance, adjusted) · {period} · {interval}"
                    )
                )
            except (ValueError, DataError) as e:
                st.error(str(e))


def _technical(ds: Dataset, rep: dict) -> None:
    d = rep["data"]
    m = st.columns(5)
    m[0].metric("Close", f"{rep['close']:,.2f}")
    m[1].metric(
        "Rule score",
        f"{rep['score']}/100",
        headline(rep),
        delta_color="off",
        delta_arrow="off",
        help="Weighted count of the rules below. A heuristic, not a probability.",
    )
    m[2].metric("RSI 14", f"{rep['rsi']:.1f}")
    m[3].metric("20-bar return", pct(rep["return_20"], sign=True))
    m[4].metric("Annualised vol.", pct(rep["volatility_ann"], 1))
    st.plotly_chart(price_chart(d, ds.ticker), width="stretch")

    st.subheader("How the score is built")
    st.caption(
        "Base 50. Each rule adds its points when met and subtracts them when not; unevaluable rules score 0. Clamped to 0–100. A heuristic, not a probability."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"Rule": r.name, "Met": {True: "✅", False: "❌", None: "—"}[r.met], "Points": r.contribution, "Detail": r.detail}
                for r in rep["rules"]
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if rep["risks"]:
        for x in [r for r in rep["risks"] if r.startswith("RSI is")]:
            st.warning(x)
    lv = st.columns(4)
    lv[0].metric("20-bar support", f"{rep['support20']:,.2f}")
    lv[1].metric("20-bar resistance", f"{rep['resistance20']:,.2f}")
    lv[2].metric("ATR 14 (Wilder)", f"{rep['atr14']:,.3f}" if rep["atr14"] else "—")
    lv[3].metric("Volume / 20-bar avg", f"{rep['volume_ratio']:.2f}×" if rep["volume_ratio"] else "—")
    st.subheader("Technical readings")
    st.dataframe(pd.DataFrame(technical_summary(d)), hide_index=True, width="stretch")
    st.write(
        "**Candle observations:** "
        + (", ".join(rep["patterns"]) if rep["patterns"] else "none on the latest bar")
        + " _(heuristic)_"
    )
    st.download_button(
        "Download analysed data (CSV)", d.to_csv(index=False).encode(), f"{ds.ticker.lower()}_analysis.csv", "text/csv"
    )


def _volatility(rep: dict) -> None:
    d = rep["data"]
    ppy = rep["periods_per_year"]
    vol = annualised_volatility(d["close"], ppy, window=20) * 100
    st.caption(f"Annualised with {ppy:g} periods/year, inferred from bar spacing.")
    st.line_chart(pd.DataFrame({"20-bar annualised volatility %": vol.values}, index=d["date"]))
    flags = unusual_activity(d)
    for f in flags:
        st.warning(f)
    if not flags:
        st.success("No threshold-based unusual-activity flag on the latest bar.")
    st.caption("Statistical alerts only — not evidence of manipulation, insider activity or a breakout.")


def _fundamentals(ds: Dataset) -> None:
    st.caption("Enter figures from the company's filings (same currency and period basis). Negative values are allowed.")
    with st.form("fund_form"):
        a, b, c = st.columns(3)
        rev = a.number_input("Revenue (latest period)", min_value=0.0, step=1.0)
        prior = b.number_input("Revenue (prior comparable period)", min_value=0.0, step=1.0)
        np_ = c.number_input("Net profit / loss", value=0.0, step=1.0)
        d, e, f = st.columns(3)
        ocf = d.number_input("Operating cash flow", value=0.0, step=1.0)
        debt = e.number_input("Total debt", min_value=0.0, step=1.0)
        eq = f.number_input("Shareholders' equity", value=0.0, step=1.0)
        src = st.text_input("Filing / source reference")
        go = st.form_submit_button("Review fundamentals")
    if go:
        r = fund.ratios(rev, prior, np_, ocf, debt, eq)
        st.session_state["fundamentals"] = {k: v for k, v in r.items() if k != "flags"}
        x = st.columns(4)
        x[0].metric("Revenue growth", pct(r["revenue_growth"]))
        x[1].metric("Net margin", pct(r["net_margin"]))
        x[2].metric("Debt / equity", f"{r['debt_to_equity']:.2f}×" if r["debt_to_equity"] is not None else "n/m")
        x[3].metric("Cash conversion (OCF/NP)", f"{r['cash_conversion']:.2f}×" if r["cash_conversion"] is not None else "n/m")
        for fl in r["flags"]:
            st.warning(fl)
        st.caption(f"Source: {src or 'not supplied'}. A single-period screen, not a valuation.")


def _ai_brief(ds: Dataset, rep: dict) -> None:
    st.caption(
        "Claude writes a brief from MarketMind's computed fact sheet only — no outside data. Every number in the reply is "
        "checked against the fact sheet. Without ANTHROPIC_API_KEY a rules-based brief is shown instead."
    )
    bt = st.session_state.get("backtest_result")
    facts = research.build_facts(ds.ticker, rep, bt, st.session_state.get("fundamentals"))
    with st.expander("Fact sheet sent to the model"):
        st.json(facts)
    if st.button("Generate brief", type="primary"):
        with st.spinner("Writing brief…"):
            st.session_state["brief"] = (
                ds.ticker,
                rep["as_of"],
                run_ai(lambda: research.llm_brief(facts), lambda: research.rules_brief(facts)),
            )
    saved = st.session_state.get("brief")
    if saved and saved[0] == ds.ticker and saved[1] == rep["as_of"]:
        b: research.Brief = saved[2]
        st.caption(f"Generated by {b.model}" if b.source == "llm" else "Rules-based brief (no language model used)")
        if b.unverified_numbers:
            st.error("Unverified numbers (not in the fact sheet — treat with suspicion): " + ", ".join(b.unverified_numbers))
        st.markdown(b.markdown)
        st.caption("General information only, not financial advice. Consider your circumstances and seek licensed advice.")


def render() -> None:
    _load_controls()
    ds = get_dataset()
    if ds is None:
        st.info("Fetch a ticker or upload a CSV to begin. A synthetic demo file is included: `sample_demo_ohlcv.csv`.")
        return
    rep = analyse(ds.df)
    d = rep["data"]
    st.caption(f"**{ds.ticker}** · {ds.source} · {len(d):,} bars · {d.date.min().date()} → {d.date.max().date()}")
    t1, t1b, t2, t3, t4 = st.tabs(["Technical", "Patterns & levels", "Volatility", "Fundamentals", "AI brief"])
    with t1:
        _technical(ds, rep)
    with t1b:
        patterns_ui.render(ds.ticker, ds.df, fetched=not ds.source.startswith("CSV"))
    with t2:
        _volatility(rep)
    with t3:
        _fundamentals(ds)
    with t4:
        _ai_brief(ds, rep)
