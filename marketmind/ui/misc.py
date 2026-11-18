"""Overview, journal (thesis + calendar), admin and settings pages."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import __version__
from ..auth import AuthError, authenticate, change_password
from ..backup import ImportErrorMM, delete_account, export_user_data, import_user_data, read_export
from ..data import DataError, clean_ticker
from ..db import connect
from ..insights import check_thesis
from ..portfolio import value_holdings
from ..predictions import hit_rate
from .common import cached_history, cached_prices, current_user, pct
from .style import badge, card, compact, empty, row


def _go(page: str) -> None:
    st.session_state["nav"] = page


def render_overview() -> None:
    u = current_user()
    today = date.today()
    with connect() as con:
        holdings = pd.DataFrame(
            con.execute("SELECT ticker,quantity,avg_cost,currency FROM holdings WHERE user_id=?", (u.id,)).fetchall(),
            columns=["ticker", "quantity", "avg_cost", "currency"],
        )
        preds = pd.DataFrame(
            con.execute(
                "SELECT ticker,prediction,outcome,realised_return,mode,created_at FROM prediction_log WHERE user_id=? "
                "ORDER BY created_at DESC, id DESC",
                (u.id,),
            ).fetchall(),
            columns=["ticker", "view", "outcome", "ret", "mode", "created"],
        )
        due = con.execute(
            "SELECT ticker,review_date FROM theses WHERE user_id=? AND status IN ('Active','Under review') AND review_date<=? ORDER BY review_date",
            (u.id, (today + timedelta(days=7)).isoformat()),
        ).fetchall()
        events = con.execute(
            "SELECT event_date,event,impact FROM calendar_events WHERE user_id=? AND event_date BETWEEN ? AND ? ORDER BY event_date",
            (u.id, today.isoformat(), (today + timedelta(days=14)).isoformat()),
        ).fetchall()
        triggers = con.execute(
            "SELECT ticker,stop_below,stop_above,review_date FROM theses WHERE user_id=? AND status IN ('Active','Under review') "
            "AND (stop_below IS NOT NULL OR stop_above IS NOT NULL)",
            (u.id,),
        ).fetchall()

    # ---- KPI row -------------------------------------------------------------
    value_txt, pnl_txt, pnl_delta, ccy = "—", "—", None, ""
    if len(holdings):
        try:
            prices = cached_prices(tuple(holdings.ticker))
        except Exception:  # prices are optional on the dashboard
            prices = {}
        v = value_holdings(holdings, prices)
        by_ccy = v.groupby("currency")[["market_value", "cost_basis", "unrealised_pnl"]].sum(min_count=1)
        main = by_ccy["cost_basis"].idxmax()
        mv, cb, pnl = by_ccy.loc[main]
        if mv == mv:
            ccy = f" ({main})"
            value_txt = compact(mv)
            pnl_txt = ("+" if pnl >= 0 else "−") + compact(abs(pnl))
            pnl_delta = f"{pnl / cb:+.1%}" if cb else None
    live = preds[(preds["mode"] == "live")]
    prac = preds[(preds["mode"] == "practice")]
    lr, ln = hit_rate(live.outcome.tolist())
    pr, pn = hit_rate(prac.outcome.tolist())
    pending = int((live.outcome == "Pending").sum())
    k = st.columns(5)
    k[0].metric(f"Portfolio{ccy}", value_txt, help="Holdings in your largest currency at the latest close (delayed).")
    k[1].metric(f"P&L{ccy}", pnl_txt, pnl_delta, help="Unrealised profit or loss at the latest close.")
    k[2].metric("Live hit rate", pct(lr, 0) if lr is not None else "—", f"{ln} scored", delta_color="off", delta_arrow="off")
    k[3].metric("Practice hit rate", pct(pr, 0) if pr is not None else "—", f"{pn} rounds", delta_color="off", delta_arrow="off")
    k[4].metric("Awaiting score", pending, f"{len(holdings)} holdings", delta_color="off", delta_arrow="off")

    # ---- Alerts --------------------------------------------------------------
    for tk, lo, hi, rd in triggers:
        try:
            close = float(cached_history(tk, "1y", "1d")["close"].iloc[-1])
        except Exception:  # noqa: S112 - a missing price just means no alert
            continue
        s = check_thesis(close, lo, hi, rd)
        if s.status in ("Triggered", "Near trigger"):
            st.error(
                f"**{tk}** — {s.status}: {s.detail} See **Report card → Thesis checker**.", icon=":material/notifications_active:"
            )
    if due:
        st.warning("Thesis reviews due within 7 days: " + ", ".join(f"{t} ({d})" for t, d in due), icon=":material/event:")

    # ---- Quick actions -------------------------------------------------------
    q = st.columns(4)
    q[0].button(
        "Analyse a stock", icon=":material/query_stats:", width="stretch", on_click=_go, args=("Analyse",), type="primary"
    )
    q[1].button("Play a practice round", icon=":material/sports_esports:", width="stretch", on_click=_go, args=("Practice",))
    q[2].button("Open report card", icon=":material/school:", width="stretch", on_click=_go, args=("Report card",))
    q[3].button("Write a thesis", icon=":material/edit_note:", width="stretch", on_click=_go, args=("Journal",))
    st.write("")

    # ---- Activity + upcoming -------------------------------------------------
    left, right = st.columns([1.35, 1])
    with left:
        rows = ""
        for r in preds.head(7).itertuples(index=False):
            tone = {"Correct": "good", "Incorrect": "bad", "Pending": "warn"}.get(r.outcome, "info")
            move = "" if r.ret is None or r.ret != r.ret else f" · {r.ret:+.1%}"
            label = "practice" if r.mode == "practice" else "live"
            rows += row(f"{r.view} on {r.ticker}", badge(r.outcome, tone), f"{label}{move}")
        card("Recent calls", rows or empty("No calls yet. Try a practice round to build your report card."))
    with right:
        rows = "".join(row(e, badge(i, {"High": "bad", "Medium": "warn"}.get(i, "info")), d) for d, e, i in events)
        rows += "".join(row(f"Review thesis: {t}", badge("Due", "warn"), d) for t, d in due)
        card("Coming up · 14 days", rows or empty("Nothing scheduled. Add events in Journal → Event calendar."))
    st.caption("Research tool only — not a broker and not financial advice. Market data is delayed and unofficial.")


def render_journal() -> None:
    uid = current_user().id
    t1, t2 = st.tabs(["Investment theses", "Event calendar"])
    with t1:
        with st.form("thesis_form", clear_on_submit=True):
            t = st.text_input("Ticker")
            thesis = st.text_area("Why are you considering this investment?")
            invalid = st.text_area("What would prove this thesis wrong? (required)")
            p1, p2, p3 = st.columns(3)
            entry = p1.number_input("Price when written (optional)", min_value=0.0, step=0.01)
            below = p2.number_input("Invalidate if price falls to", min_value=0.0, step=0.01, help="0 = no lower trigger")
            above = p3.number_input("Invalidate if price rises to", min_value=0.0, step=0.01, help="0 = no upper trigger")
            a, b = st.columns(2)
            review = a.date_input("Review by", value=date.today() + timedelta(days=90))
            status = b.selectbox("Status", ["Active", "Under review", "Invalidated", "Closed"])
            if st.form_submit_button("Save thesis"):
                try:
                    tk = clean_ticker(t)
                    if not thesis.strip() or not invalid.strip():
                        raise DataError("A thesis needs both a rationale and invalidation criteria.")
                    if below and above and below >= above:
                        raise DataError("The lower trigger must be below the upper trigger.")
                    with connect() as con:
                        con.execute(
                            "INSERT INTO theses(user_id,ticker,thesis,invalidation,review_date,status,entry_price,stop_below,stop_above) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                uid,
                                tk,
                                thesis.strip(),
                                invalid.strip(),
                                review.isoformat(),
                                status,
                                entry or None,
                                below or None,
                                above or None,
                            ),
                        )
                    st.success("Thesis saved.")
                except DataError as e:
                    st.error(str(e))
        with connect() as con:
            th = con.execute(
                "SELECT id,ticker,thesis,invalidation,review_date,status,stop_below,stop_above,created_at FROM theses "
                "WHERE user_id=? ORDER BY review_date",
                (uid,),
            ).fetchall()
        if th:
            cols = [
                "id",
                "Ticker",
                "Thesis",
                "Invalidation",
                "Review by",
                "Status",
                "Invalidate below",
                "Invalidate above",
                "Created",
            ]
            df = pd.DataFrame(th, columns=cols)
            edited = st.data_editor(
                df.drop(columns="id"),
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=["Active", "Under review", "Invalidated", "Closed"]),
                    "Invalidate below": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                    "Invalidate above": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                },
                disabled=["Ticker", "Created"],
                width="stretch",
                hide_index=True,
                key="thesis_editor",
            )
            st.caption("Price triggers are checked automatically on the **Report card** page.")
            c1, c2 = st.columns(2)
            if c1.button("Save changes"):

                def num(x):
                    return None if x is None or x != x or x == 0 else float(x)

                with connect() as con:
                    for tid, (_, row) in zip(df.id, edited.iterrows(), strict=True):
                        con.execute(
                            "UPDATE theses SET thesis=?,invalidation=?,review_date=?,status=?,stop_below=?,stop_above=? WHERE id=? AND user_id=?",
                            (
                                row["Thesis"],
                                row["Invalidation"],
                                str(row["Review by"]),
                                row["Status"],
                                num(row["Invalidate below"]),
                                num(row["Invalidate above"]),
                                int(tid),
                                uid,
                            ),
                        )
                st.success("Updated.")
            labels = {f"{r[1]} · {r[4]} · {r[5]}": r[0] for r in th}
            sel = c2.selectbox("Delete", list(labels), label_visibility="collapsed")
            if c2.button("Delete selected thesis"):
                with connect() as con:
                    con.execute("DELETE FROM theses WHERE id=? AND user_id=?", (labels[sel], uid))
                st.rerun()
    with t2:
        st.caption("Personal calendar — add events from official sources (central banks, statistics offices, company IR).")
        with st.form("event_form", clear_on_submit=True):
            a, b, c = st.columns(3)
            dt = a.date_input("Date", value=date.today())
            region = b.selectbox("Region", ["United States", "Australia", "Sri Lanka", "Global", "Other"])
            impact = c.selectbox("Impact", ["High", "Medium", "Low"])
            ev = st.text_input("Event", placeholder="e.g. RBA cash rate decision")
            src = st.text_input("Source / why it matters")
            if st.form_submit_button("Add event") and ev.strip():
                with connect() as con:
                    con.execute(
                        "INSERT INTO calendar_events(user_id,event_date,event,region,impact,notes) VALUES(?,?,?,?,?,?)",
                        (uid, dt.isoformat(), ev.strip(), region, impact, src),
                    )
                st.rerun()
        with connect() as con:
            evs = con.execute(
                "SELECT id,event_date,event,region,impact,notes FROM calendar_events WHERE user_id=? ORDER BY event_date", (uid,)
            ).fetchall()
        if evs:
            show_past = st.toggle("Show past events", value=False)
            df = pd.DataFrame(evs, columns=["id", "Date", "Event", "Region", "Impact", "Notes"])
            if not show_past:
                df = df[df.Date >= date.today().isoformat()]
            st.dataframe(df.drop(columns="id"), width="stretch", hide_index=True)
            if len(df):
                labels = {f"{r.Date} · {r.Event}": r.id for r in df.itertuples()}
                sel = st.selectbox("Delete event", list(labels))
                if st.button("Delete selected event"):
                    with connect() as con:
                        con.execute("DELETE FROM calendar_events WHERE id=? AND user_id=?", (int(labels[sel]), uid))
                    st.rerun()


def render_admin() -> None:
    u = current_user()
    if not u.is_admin:  # defence in depth: the page is also hidden from navigation
        st.error("Admin role required.")
        st.stop()
    with connect() as con:
        users = con.execute("SELECT id,username,role,created_at FROM users ORDER BY id").fetchall()
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 - fixed table names
            for t in ("holdings", "watchlist", "prediction_log", "paper_trades", "theses")
        }
        fails = con.execute(
            "SELECT username,COUNT(*) FROM login_attempts WHERE success=0 AND attempted_at>=? GROUP BY username ORDER BY 2 DESC LIMIT 20",
            ((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),),
        ).fetchall()
    cols = st.columns(len(counts) + 1)
    cols[0].metric("Accounts", len(users))
    for col, (k, v) in zip(cols[1:], counts.items(), strict=True):
        col.metric(k.replace("_", " ").title(), v)
    st.subheader("Accounts")
    st.dataframe(pd.DataFrame(users, columns=["ID", "Username", "Role", "Created"]), width="stretch", hide_index=True)
    st.subheader("Failed logins (24 h)")
    if fails:
        st.dataframe(pd.DataFrame(fails, columns=["Username", "Failures"]), width="stretch", hide_index=True)
    else:
        st.write("None.")
    st.caption(
        "Roles are granted from the server shell: `python -m marketmind.manage grant-admin <username>`. User content is not shown here."
    )


def render_settings() -> None:
    u = current_user()
    st.write(f"Signed in as **{u.username}** ({u.role})")
    with st.form("pw", clear_on_submit=True):
        st.subheader("Change password")
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password (12+ characters)", type="password")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change password"):
            try:
                with connect() as con:
                    change_password(con, u, cur, new, new2)
                st.success("Password changed.")
            except AuthError as e:
                st.error(str(e))
    st.subheader("Your data")
    with connect() as con:
        blob = export_user_data(con, u.id, u.username)
    st.download_button(
        "Download all my data (ZIP of CSVs)",
        blob,
        file_name=f"marketmind-{u.username}-{date.today().isoformat()}.zip",
        mime="application/zip",
        help="Holdings, watchlist, journal, calendar, predictions, paper trades and settings. Keep it somewhere safe.",
    )
    with st.expander("Restore from a backup"):
        st.warning("Restoring **replaces** all your current records with the backup's contents.")
        up = st.file_uploader("MarketMind export (.zip)", type=["zip"], key="restore_zip")
        if up is not None:
            raw = up.getvalue()
            try:
                manifest, _ = read_export(raw)
                st.write(
                    f"Backup of **{manifest.get('username')}** from {manifest.get('exported_at')} (v{manifest.get('version')}): "
                    + ", ".join(f"{k} {v}" for k, v in manifest.get("tables", {}).items())
                )
                pw = st.text_input("Confirm with your password", type="password", key="restore_pw")
                if st.button("Replace my data with this backup", type="primary"):
                    with connect() as con:
                        authenticate(con, u.username, pw)
                    with connect() as con:
                        counts = import_user_data(con, u.id, raw)
                    st.session_state.pop("dataset", None)
                    st.success("Restored: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            except (ImportErrorMM, AuthError) as e:
                st.error(str(e))
    with st.expander("Delete my account"):
        st.error("This permanently deletes your account and every record in it. Download your data first if you want to keep it.")
        pw = st.text_input("Password", type="password", key="del_pw")
        confirm = st.text_input('Type "DELETE" to confirm', key="del_confirm")
        if st.button("Delete my account permanently"):
            try:
                if confirm != "DELETE":
                    raise AuthError('Type "DELETE" exactly to confirm.')
                with connect() as con:
                    authenticate(con, u.username, pw)
                with connect() as con:
                    delete_account(con, u.id, u.username)
                st.session_state.clear()
                st.rerun()
            except AuthError as e:
                st.error(str(e))

    st.subheader("Data and privacy")
    ai = "configured" if os.getenv("ANTHROPIC_API_KEY") else "not configured (rules-based briefs only)"
    st.write(
        "Your records are stored in the local SQLite database on the machine running this app. "
        f"AI features: {ai}. When configured, an AI brief sends only the computed fact sheet for the asset you are viewing, and a "
        "thesis review (only when you click it) also sends that one thesis's text. Holdings, trades, other journal entries and "
        "account details are never sent."
    )
    st.write(
        "Market data comes from the unofficial `yfinance` package: delayed, rate-limited and not licensed for redistribution."
    )
    st.code(f"MarketMind AI {__version__}")
