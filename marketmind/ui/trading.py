"""Paper trading (cash/position-enforced) and objectively scored predictions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import patterns as P
from .. import predictions as pred
from ..data import DataError, clean_ticker
from ..db import connect
from ..engine import analyse
from ..portfolio import DEFAULT_PAPER_CASH, PAPER_CURRENCIES, OrderRejected, apply_trade, positions_frame, replay
from .common import cached_prices, cached_since, current_user, get_dataset, headline, pct

CCYS = list(PAPER_CURRENCIES)
DEFAULT_CASH = DEFAULT_PAPER_CASH


def _accounts(uid: int):
    with connect() as con:
        cash = dict(con.execute("SELECT currency,starting_cash FROM paper_accounts WHERE user_id=?", (uid,)).fetchall())
        trades = con.execute(
            "SELECT ticker,side,quantity,price,fee,currency FROM paper_trades WHERE user_id=? ORDER BY created_at,id", (uid,)
        ).fetchall()
    for c in CCYS:
        cash.setdefault(c, DEFAULT_CASH)
    return cash, trades, replay(cash, trades)


def render_paper() -> None:
    uid = current_user().id
    try:
        cash, trades, accts = _accounts(uid)
    except OrderRejected as err:
        st.error(f"Your saved paper trades are inconsistent with cash/position rules (likely from an older version): {err}")
        if st.button("Reset paper account", type="primary"):
            with connect() as con:
                con.execute("DELETE FROM paper_trades WHERE user_id=?", (uid,))
            st.rerun()
        return
    st.caption("Simulated long-only ledger. Buys need enough cash; sells need enough units. No broker connection.")
    cols = st.columns(len(accts))
    for col, a in zip(cols, accts.values(), strict=True):
        col.metric(f"{a.currency} cash", f"{a.cash:,.2f}", f"start {cash[a.currency]:,.0f}", delta_color="off", delta_arrow="off")

    with st.form("paper_trade", clear_on_submit=True):
        a, b, c = st.columns(3)
        t = a.text_input("Ticker")
        side = b.selectbox("Side", ["BUY", "SELL"])
        qty = c.number_input("Quantity", min_value=0.0, step=1.0)
        d, e, f = st.columns(3)
        price = d.number_input("Price (0 = use latest close)", min_value=0.0)
        fee = e.number_input("Fee", min_value=0.0, value=0.0)
        ccy = f.selectbox("Currency", CCYS)
        if st.form_submit_button("Place simulated order", type="primary"):
            try:
                tk = clean_ticker(t)
                px = price or cached_prices((tk,)).get(tk)
                if not px:
                    raise DataError(f"No latest price available for {tk}; enter a price manually.")
                # Validate against a fresh replay so concurrent tabs can't overspend.
                _, _, fresh = _accounts(uid)
                apply_trade(fresh[ccy], tk, side, qty, float(px), fee)
                with connect() as con:
                    con.execute(
                        "INSERT INTO paper_trades(user_id,ticker,side,quantity,price,fee,currency) VALUES(?,?,?,?,?,?,?)",
                        (uid, tk, side, qty, float(px), fee, ccy),
                    )
                st.success(f"{side} {qty:g} {tk} @ {float(px):,.2f} {ccy} recorded.")
                st.rerun()
            except (OrderRejected, DataError) as err:
                st.error(str(err))

    pos = positions_frame(accts)
    if not pos.empty:
        if st.toggle("Mark positions to latest close", value=False, key="pt_mark"):
            prices = cached_prices(tuple(pos.Ticker))
            pos = positions_frame(accts, prices)
        st.subheader("Positions")
        st.dataframe(pos, width="stretch", hide_index=True)
    if trades:
        with st.expander(f"Order history ({len(trades)})"):
            st.dataframe(
                pd.DataFrame(trades, columns=["Ticker", "Side", "Qty", "Price", "Fee", "Currency"]),
                width="stretch",
                hide_index=True,
            )

    with st.expander("Account settings"):
        with st.form("cash_form"):
            c1, c2 = st.columns(2)
            cc = c1.selectbox("Currency", CCYS, key="pa_ccy")
            amt = c2.number_input("Starting cash", min_value=0.0, value=DEFAULT_CASH, step=1000.0)
            if st.form_submit_button("Set starting cash"):
                try:
                    replay({**cash, cc: amt}, trades)  # must still be consistent with history
                except OrderRejected as err:
                    st.error(f"Existing trades would be invalid with that balance: {err}")
                else:
                    with connect() as con:
                        con.execute(
                            "INSERT INTO paper_accounts(user_id,currency,starting_cash) VALUES(?,?,?) "
                            "ON CONFLICT(user_id,currency) DO UPDATE SET starting_cash=excluded.starting_cash",
                            (uid, cc, amt),
                        )
                    st.rerun()
        if st.button("Reset paper account (delete all simulated trades)"):
            st.session_state["confirm_reset"] = True
        if st.session_state.get("confirm_reset"):
            st.warning("This deletes every simulated trade permanently.")
            if st.button("Yes, reset", type="primary"):
                with connect() as con:
                    con.execute("DELETE FROM paper_trades WHERE user_id=?", (uid,))
                st.session_state.pop("confirm_reset")
                st.rerun()


def _evaluate_due(uid: int) -> int:
    with connect() as con:
        pending = con.execute(
            "SELECT id,ticker,prediction,reference_price,COALESCE(as_of,created_at),horizon_bars,threshold_pct "
            "FROM prediction_log WHERE user_id=? AND outcome='Pending' AND mode='live'",
            (uid,),
        ).fetchall()
    done = 0
    for pid, tk, direction, ref, as_of, hz, thr in pending:
        try:
            closes = cached_since(tk, str(pd.Timestamp(as_of).date()))
        except DataError:
            continue
        ev = pred.evaluate(direction, ref, as_of, closes, hz, thr)
        if ev.outcome != "Pending":
            with connect() as con:
                con.execute(
                    "UPDATE prediction_log SET outcome=?, realised_return=?, evaluated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                    (ev.outcome, ev.realised_return, pid, uid),
                )
            done += 1
    return done


def render_predictions() -> None:
    uid = current_user().id
    st.caption(
        "Record a directional view on the loaded asset. After the horizon passes, MarketMind scores it automatically "
        "from market closes — you can't edit outcomes, so the hit rate is not self-graded."
    )
    ds = get_dataset()
    if ds is not None:
        rep = analyse(ds.df)
        st.write(
            f"**{ds.ticker}** · close {rep['close']:,.2f} on {rep['as_of'].date()} · rule score {rep['score']}/100 ({headline(rep)})"
        )
        with st.form("prediction_save", clear_on_submit=True):
            a, b, c = st.columns(3)
            direction = a.selectbox("View", pred.DIRECTIONS)
            hz = b.number_input("Horizon (trading days)", 1, 260, 20)
            thr = c.number_input(
                "Threshold ±%", 0.0, 50.0, 2.0, 0.5, help="Bullish needs > +thr, Bearish < −thr, Neutral within ±thr."
            )
            note = st.text_input("Reasoning")
            if st.form_submit_button("Save timestamped prediction"):
                with connect() as con:
                    con.execute(
                        "INSERT INTO prediction_log(user_id,ticker,prediction,score,reference_price,notes,as_of,horizon_bars,"
                        "threshold_pct,ret20_at_entry,rsi_at_entry,patterns_at_entry) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            uid,
                            ds.ticker,
                            direction,
                            rep["score"],
                            rep["close"],
                            note,
                            rep["as_of"].isoformat(),
                            int(hz),
                            float(thr),
                            None if rep["return_20"] != rep["return_20"] else rep["return_20"],  # NaN → NULL
                            rep["rsi"],
                            P.encode_tags(P.tags_at_end(P.scan(ds.df), ds.df)),
                        ),
                    )
                st.success("Prediction saved.")
        if rep["as_of"] < pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=5):
            st.caption(
                "⚠️ The loaded data ends more than 5 days ago; the prediction is anchored to that last bar, and is scored on the bars after it."
            )
    else:
        st.info("Load an asset on **Analyse** to record a new prediction.")

    if st.button("Score due predictions now"):
        n = _evaluate_due(uid)
        if n:
            st.success(f"Scored {n} prediction(s).")
        else:
            st.info("Nothing is due yet (or prices were unavailable).")
    with connect() as con:
        logs = con.execute(
            "SELECT ticker,prediction,score,reference_price,as_of,horizon_bars,threshold_pct,outcome,realised_return,notes "
            "FROM prediction_log WHERE user_id=? AND mode='live' ORDER BY created_at DESC",
            (uid,),
        ).fetchall()
    if not logs:
        return
    df = pd.DataFrame(
        logs, columns=["Ticker", "View", "Score", "Ref. price", "As of", "Horizon", "Thr %", "Outcome", "Realised", "Notes"]
    )
    rate, n = pred.hit_rate(df.Outcome.tolist())
    a, b = st.columns(2)
    a.metric("Hit rate", pct(rate, 1) if rate is not None else "—", f"{n} scored", delta_color="off", delta_arrow="off")
    by_view = df[df.Outcome.isin(["Correct", "Incorrect"])].groupby("View").Outcome.apply(lambda s: (s == "Correct").mean())
    b.write("By view: " + (", ".join(f"{k} {pct(v, 0)}" for k, v in by_view.items()) or "—"))
    if 0 < n < 20:
        st.caption("Fewer than 20 scored predictions — the hit rate is mostly noise.")
    df["Realised"] = df["Realised"].map(pct)
    st.dataframe(df, width="stretch", hide_index=True)
