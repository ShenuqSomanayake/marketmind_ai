"""End-to-end smoke tests of every page using Streamlit's AppTest (network calls are stubbed)."""

from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from conftest import make_ohlcv
from streamlit.testing.v1 import AppTest

from marketmind import auth, data
from marketmind.db import connect
from marketmind.engine import normalize_ohlcv
from marketmind.ui.common import Dataset

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def stub_network(monkeypatch, tmp_db):
    df = normalize_ohlcv(make_ohlcv(300))
    monkeypatch.setattr(data, "fetch_history", lambda t, period="1y", interval="1d": df)
    monkeypatch.setattr(data, "latest_prices", lambda ts: {t: 123.0 for t in ts})
    later = pd.DataFrame({"date": pd.bdate_range("2030-01-01", periods=40, tz="UTC"), "close": 500.0})
    monkeypatch.setattr(data, "fetch_history_since", lambda t, start: later)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st.cache_data.clear()
    yield df


def _app(role="user", dataset=True):
    with connect() as con:
        u = auth.create_user(con, f"tester{role}", "a long test password")
        if role == "admin":
            auth.set_role(con, u.username, "admin")
        u = auth.get_user(con, u.id)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["user"] = u
    if dataset:
        at.session_state["dataset"] = Dataset(normalize_ohlcv(make_ohlcv(300)), "TEST", "unit test")
    return at.run()


def _go(at, page):
    at.sidebar.radio(key="nav").set_value(page).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_login_screen_and_register():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and any("grades you" in m.value for m in at.markdown)
    at.text_input(key="new_user").input("newbie")
    at.text_input(key="new_pass").input("short")
    at.text_input(key="new_pass2").input("short")
    at.button[1].click().run()
    assert any("12 characters" in e.value for e in at.error)
    at.text_input(key="new_pass").input("long enough password")
    at.text_input(key="new_pass2").input("long enough password")
    at.button[1].click().run()
    assert at.session_state["user"].username == "newbie"


@pytest.mark.parametrize(
    "page", ["Overview", "Analyse", "Backtest", "Portfolio", "Paper trading", "Predictions", "Journal", "Settings"]
)
def test_every_page_renders(page):
    _go(_app(), page)


def test_pages_render_without_dataset():
    at = _app(dataset=False)
    for p in ["Analyse", "Backtest", "Predictions"]:
        _go(at, p)


def test_admin_hidden_from_users_and_shown_to_admins():
    assert not any(o.endswith("Admin") for o in _app().sidebar.radio(key="nav").options)
    at = _app("admin")
    assert any(o.endswith("Admin") for o in at.sidebar.radio(key="nav").options)
    _go(at, "Admin")


def test_backtest_runs_and_shows_benchmark():
    at = _go(_app(), "Backtest")
    at.button[0].click().run()  # form submit
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Buy & hold return" in labels and "Strategy return" in labels


def test_ai_brief_rules_fallback():
    at = _go(_app(), "Analyse")
    btn = next(b for b in at.button if b.label == "Generate brief")
    btn.click().run()
    assert not at.exception
    assert any("Bull case" in m.value for m in at.markdown)


def test_paper_trade_flow_rejects_overspend():
    at = _go(_app(), "Paper trading")
    at.text_input[0].input("ABC")
    at.number_input[0].set_value(10)  # qty
    at.number_input[1].set_value(50)  # price
    at.button[0].click().run()
    assert not at.exception
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0] == 1
    at.text_input[0].input("ABC")
    at.number_input[0].set_value(1_000_000)
    at.number_input[1].set_value(50)
    at.button[0].click().run()
    assert any("Insufficient" in e.value for e in at.error)


def test_prediction_saved_then_auto_scored():
    at = _go(_app(), "Predictions")
    at.button[0].click().run()  # save prediction (form submit)
    with connect() as con:
        assert con.execute("SELECT outcome FROM prediction_log").fetchone()[0] == "Pending"
    next(b for b in at.button if b.label == "Score due predictions now").click().run()
    assert not at.exception
    with connect() as con:
        outcome, realised = con.execute("SELECT outcome, realised_return FROM prediction_log").fetchone()
    assert outcome in ("Correct", "Incorrect") and realised is not None


def test_portfolio_live_pnl():
    at = _app()
    uid = at.session_state["user"].id
    with connect() as con:
        con.execute(
            "INSERT INTO holdings(user_id,ticker,quantity,avg_cost,currency) VALUES(?,?,?,?,?)", (uid, "ABC", 10, 100, "USD")
        )
        con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (uid, "XYZ"))
    at = _go(at, "Portfolio")
    pnl = next(m for m in at.metric if m.label == "Unrealised P&L")
    assert pnl.value == "230.00"


def test_deleted_user_is_logged_out():
    at = _app()
    with connect() as con:
        con.execute("DELETE FROM users")
    at.run()
    assert "user" not in at.session_state


def test_report_card_with_data_and_thesis_trigger():
    at = _app()
    uid = at.session_state["user"].id
    with connect() as con:
        for i in range(6):
            con.execute(
                "INSERT INTO prediction_log(user_id,ticker,prediction,score,reference_price,outcome,realised_return,threshold_pct,"
                "horizon_bars,ret20_at_entry) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, "T", "Bullish", 60, 100, "Incorrect" if i < 4 else "Correct", -0.05 if i < 4 else 0.05, 2, 20, 0.15),
            )
        close = normalize_ohlcv(make_ohlcv(300))["close"].iloc[-1]
        con.execute(
            "INSERT INTO theses(user_id,ticker,thesis,invalidation,review_date,status,stop_below) VALUES(?,?,?,?,?,?,?)",
            (uid, "ABC", "Because reasons", "Below trigger", "2099-01-01", "Active", float(close) * 1.01),
        )
    at = _go(at, "Report card")
    assert any(m.label == "Hit rate" for m in at.metric)
    assert any("Triggered" in m.value for m in at.markdown)
    assert any("at or below your invalidation price" in w.value for w in at.warning)
    assert any("Optimism bias" in w.value for w in at.warning)
    next(b for b in at.button if b.label.startswith("Review this thesis")).click().run()
    assert not at.exception and any("Invalidation criteria status" in m.value for m in at.markdown)
    at = _go(at, "Overview")
    assert any("Triggered" in e.value for e in at.error)


def test_report_card_empty():
    _go(_app(), "Report card")


def test_journal_saves_price_triggers():
    at = _go(_app(), "Journal")
    at.text_input[0].input("ABC")
    at.text_area[0].input("Thesis text")
    at.text_area[1].input("Falls below 80")
    at.number_input[1].set_value(80.0)
    at.button[0].click().run()
    assert not at.exception
    with connect() as con:
        assert con.execute("SELECT stop_below, stop_above FROM theses").fetchone() == (80.0, None)


def test_practice_round_flow():
    at = _go(_app(), "Practice")
    next(b for b in at.button if b.label == "New round").click().run()
    assert not at.exception
    assert any("Mystery stock" in s.value for s in at.subheader)
    next(b for b in at.button if b.label == "Bullish").click().run()
    assert not at.exception
    assert any(("Correct" in m.value or "Incorrect" in m.value) for m in [*at.success, *at.error])
    assert any("It was" in c.value for c in at.caption)
    with connect() as con:
        mode, outcome = con.execute("SELECT mode, outcome FROM prediction_log").fetchone()
    assert mode == "practice" and outcome in ("Correct", "Incorrect")
    at = _go(at, "Predictions")  # practice calls never appear in live stats
    assert not any(m.label == "Hit rate" for m in at.metric)
    at = _go(at, "Report card")
    at.radio(key="rc_mode").set_value("Practice").run()
    assert any(m.label == "Hit rate" for m in at.metric)


def test_factual_mode_ui(monkeypatch):
    monkeypatch.setenv("MARKETMIND_FACTUAL_MODE", "1")
    at = _go(_app(), "Analyse")
    score = next(m for m in at.metric if m.label == "Rule score")
    assert "rules met" in score.delta
    next(b for b in at.button if b.label == "Generate brief").click().run()
    md = " ".join(m.value for m in at.markdown)
    assert "Rules currently met" in md and "Bull case" not in md


def test_ai_quota_falls_back_in_ui(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("MARKETMIND_AI_DAILY_LIMIT", "1")
    from marketmind import research

    calls = []

    def fake(facts, client=None, model=None):
        calls.append(1)
        return research.Brief("### Bull case\n- llm", "llm", "m")

    monkeypatch.setattr(research, "llm_brief", fake)
    at = _go(_app(), "Analyse")
    for _ in range(2):
        next(b for b in at.button if b.label == "Generate brief").click().run()
    assert len(calls) == 1
    assert any("Daily AI limit reached" in m.value for m in at.markdown)


def test_settings_export_download_present():
    at = _go(_app(), "Settings")
    assert not at.exception


def test_patterns_tab_and_technical_readings():
    at = _go(_app(), "Analyse")
    assert any(m.label == "Patterns found" for m in at.metric)
    subs = [s.value for s in at.subheader]
    assert "Technical readings" in subs and "Has this pattern actually worked on this asset?" in subs


def test_practice_pattern_hints_and_tagging():
    at = _go(_app(), "Practice")
    at.toggle(key="pr_hints").set_value(True).run()
    next(b for b in at.button if b.label == "New round").click().run()
    assert not at.exception and any("Patterns at the cut-off" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Neutral").click().run()
    with connect() as con:
        tags = con.execute("SELECT patterns_at_entry FROM prediction_log").fetchone()[0]
    assert tags is not None  # recorded (possibly empty when no pattern was present)


def test_live_prediction_records_patterns():
    at = _go(_app(), "Predictions")
    at.button[0].click().run()
    with connect() as con:
        assert con.execute("SELECT patterns_at_entry FROM prediction_log").fetchone()[0] is not None


def test_overview_quick_action_navigates():
    at = _go(_app(), "Overview")
    next(b for b in at.button if b.label == "Play a practice round").click().run()
    assert not at.exception and at.session_state["nav"] == "Practice"
