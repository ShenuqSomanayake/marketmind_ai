from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import streamlit as st

from ..data import DataError, clean_ticker
from ..db import connect
from ..engine import normalize_ohlcv, periods_per_year
from ..portfolio import value_holdings
from .common import cached_history, cached_prices, current_user, pct

CURRENCIES = ["USD", "AUD", "LKR", "EUR", "GBP"]


def _holdings_df(uid: int) -> pd.DataFrame:
    with connect() as con:
        rows = con.execute(
            "SELECT id,ticker,quantity,avg_cost,currency FROM holdings WHERE user_id=? ORDER BY ticker", (uid,)
        ).fetchall()
    return pd.DataFrame(rows, columns=["id", "ticker", "quantity", "avg_cost", "currency"])


def _holdings(uid: int) -> None:
    with st.form("add_holding", clear_on_submit=True):
        a, b, c, d = st.columns(4)
        t = a.text_input("Ticker")
        q = b.number_input("Quantity", min_value=0.0, step=1.0)
        cost = c.number_input("Average cost", min_value=0.0, step=0.01)
        cur = d.selectbox("Currency", CURRENCIES)
        if st.form_submit_button("Save holding"):
            try:
                tk = clean_ticker(t)
                if q <= 0 or cost <= 0:
                    raise DataError("Quantity and average cost must be greater than zero.")
                with connect() as con:
                    con.execute(
                        "INSERT INTO holdings(user_id,ticker,quantity,avg_cost,currency) VALUES(?,?,?,?,?) ON CONFLICT(user_id,ticker) "
                        "DO UPDATE SET quantity=excluded.quantity,avg_cost=excluded.avg_cost,currency=excluded.currency",
                        (uid, tk, q, cost, cur),
                    )
                st.success(f"Saved {tk}.")
            except DataError as e:
                st.error(str(e))
    h = _holdings_df(uid)
    if h.empty:
        st.info("No holdings saved yet.")
        return
    live = st.toggle("Show live prices (Yahoo, delayed)", value=True, key="pf_live")
    prices = cached_prices(tuple(h.ticker)) if live else {}
    v = value_holdings(h, prices)
    missing = sorted(set(h.ticker) - set(prices)) if live else []
    if missing:
        st.warning("No price for: " + ", ".join(missing) + ". Their value is shown as blank, not estimated.")
    for ccy, g in v.groupby("currency"):
        cols = st.columns(3)
        cols[0].metric(f"Market value ({ccy})", f"{g.market_value.sum():,.2f}" if g.market_value.notna().all() else "incomplete")
        cols[1].metric(f"Cost basis ({ccy})", f"{g.cost_basis.sum():,.2f}")
        pnl = g.unrealised_pnl.sum() if g.unrealised_pnl.notna().all() else None
        cols[2].metric(
            "Unrealised P&L",
            f"{pnl:,.2f}" if pnl is not None else "—",
            pct(pnl / g.cost_basis.sum()) if pnl is not None else None,
        )
    show = v[
        ["ticker", "currency", "quantity", "avg_cost", "last_price", "market_value", "unrealised_pnl", "unrealised_pct", "weight"]
    ].copy()
    show["unrealised_pct"] = show["unrealised_pct"].map(pct)
    show["weight"] = show["weight"].map(lambda x: pct(x, 1))
    st.dataframe(show, width="stretch", hide_index=True)
    top = v.dropna(subset=["weight"]).sort_values("weight", ascending=False).head(1)
    if len(top) and top.weight.iloc[0] > 0.4 and len(v) > 1:
        st.warning(
            f"{top.ticker.iloc[0]} is {pct(top.weight.iloc[0], 0)} of your {top.currency.iloc[0]} holdings — concentrated."
        )
    a, b = st.columns([3, 1])
    sel = a.selectbox("Remove a holding", h.ticker.tolist(), key="pf_del")
    if b.button("Delete", width="stretch"):
        with connect() as con:
            con.execute("DELETE FROM holdings WHERE user_id=? AND ticker=?", (uid, sel))
        st.rerun()


def _watchlist(uid: int) -> None:
    with st.form("watch_add", clear_on_submit=True):
        wt = st.text_input("Add ticker")
        if st.form_submit_button("Add to watchlist") and wt:
            try:
                with connect() as con:
                    con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (uid, clean_ticker(wt)))
            except sqlite3.IntegrityError:
                st.info("Already on your watchlist.")
            except DataError as e:
                st.error(str(e))
    with connect() as con:
        w = [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE user_id=? ORDER BY ticker", (uid,))]
    if not w:
        st.info("Watchlist is empty.")
        return
    prices = cached_prices(tuple(w)) if st.toggle("Show live prices", value=True, key="wl_live") else {}
    st.dataframe(pd.DataFrame({"Ticker": w, "Last close": [prices.get(t) for t in w]}), width="stretch", hide_index=True)
    a, b = st.columns([3, 1])
    rem = a.selectbox("Remove ticker", w, key="wl_del")
    if b.button("Remove", width="stretch"):
        with connect() as con:
            con.execute("DELETE FROM watchlist WHERE user_id=? AND ticker=?", (uid, rem))
        st.rerun()


def _risk(uid: int) -> None:
    st.caption("Correlation, volatility and relative performance across your holdings and watchlist.")
    h = _holdings_df(uid)
    with connect() as con:
        w = [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE user_id=?", (uid,))]
    source = st.radio("Price histories", ["Fetch for my holdings & watchlist", "Upload CSVs"], horizontal=True, key="rk_src")
    closes: dict[str, pd.Series] = {}
    if source.startswith("Fetch"):
        tickers = sorted(set(h.ticker) | set(w))
        if len(tickers) < 2:
            st.info("Add at least two tickers to holdings or watchlist.")
            return
        period = st.selectbox("Lookback", ["6mo", "1y", "2y", "5y"], index=1, key="rk_period")
        for t in tickers:
            try:
                df = cached_history(t, period, "1d")
                closes[t] = df.set_index(df.date.dt.normalize())["close"]
            except Exception as e:
                st.warning(f"{t}: {e}")
    else:
        for f in st.file_uploader("One OHLCV CSV per asset", type=["csv"], accept_multiple_files=True, key="rk_files") or []:
            try:
                df = normalize_ohlcv(pd.read_csv(f))
                closes[f.name.rsplit(".", 1)[0].upper()] = df.set_index(df.date.dt.normalize())["close"]
            except ValueError as e:
                st.warning(f"{f.name}: {e}")
    if len(closes) < 2:
        return
    px = pd.concat(closes, axis=1).sort_index()
    rets = px.pct_change(fill_method=None)
    ppy = periods_per_year(pd.Series(px.index))
    overlap = rets.dropna()
    if len(overlap) < 20:
        st.warning(f"Only {len(overlap)} overlapping bars — correlation is unreliable.")
    st.subheader("Return correlation")
    st.dataframe(overlap.corr().round(2), width="stretch")
    st.caption(f"Computed on {len(overlap)} overlapping bars. Correlation changes over time and rises in sell-offs.")

    first = px.apply(lambda s: s.dropna().iloc[0])
    last = px.apply(lambda s: s.dropna().iloc[-1])
    perf = pd.DataFrame(
        {
            "Period return": (last / first - 1).map(pct),
            "20-bar return": px.apply(
                lambda s: s.dropna().iloc[-1] / s.dropna().iloc[-21] - 1 if s.dropna().size > 20 else np.nan
            ).map(pct),
            "Annualised volatility": (rets.std() * np.sqrt(ppy)).map(lambda x: pct(x, 1)),
        }
    )
    st.subheader("Relative performance")
    st.dataframe(perf, width="stretch")
    st.line_chart(px.div(px.bfill().iloc[0]))


def render() -> None:
    uid = current_user().id
    t1, t2, t3 = st.tabs(["Holdings", "Watchlist", "Risk & comparison"])
    with t1:
        _holdings(uid)
    with t2:
        _watchlist(uid)
    with t3:
        _risk(uid)
