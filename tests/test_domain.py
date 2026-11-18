import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import from_closes, make_ohlcv

from marketmind import fundamentals, predictions, research
from marketmind.backtest import run_backtest
from marketmind.data import DataError, clean_ticker, ticker_from_filename
from marketmind.engine import analyse, normalize_ohlcv
from marketmind.portfolio import Account, OrderRejected, apply_trade, positions_frame, replay, value_holdings


# ---------------- portfolio / paper trading ----------------
def test_value_holdings_pnl_and_missing_prices():
    h = pd.DataFrame(
        {"ticker": ["A", "B", "C"], "quantity": [10, 5, 1], "avg_cost": [10, 20, 5], "currency": ["USD", "USD", "AUD"]}
    )
    v = value_holdings(h, {"A": 12, "B": 18})
    a = v.set_index("ticker")
    assert a.loc["A", "unrealised_pnl"] == 20 and a.loc["B", "unrealised_pnl"] == -10
    assert a.loc["A", "weight"] == pytest.approx(120 / 210)
    assert np.isnan(a.loc["C", "market_value"])  # never guessed


def test_paper_trading_enforces_cash_and_positions():
    acct = Account("USD", 1000)
    apply_trade(acct, "X", "BUY", 5, 100, 1)
    assert acct.cash == pytest.approx(499) and acct.positions["X"].avg_cost == pytest.approx(100.2)
    with pytest.raises(OrderRejected, match="Insufficient"):
        apply_trade(acct, "X", "BUY", 5, 100, 0)
    with pytest.raises(OrderRejected, match="only 5"):
        apply_trade(acct, "X", "SELL", 6, 100, 0)
    with pytest.raises(OrderRejected, match="only 0"):
        apply_trade(acct, "Y", "SELL", 1, 100, 0)
    apply_trade(acct, "X", "SELL", 5, 120, 1)
    assert acct.positions["X"].quantity == 0
    assert acct.positions["X"].realised_pnl == pytest.approx(5 * 120 - 1 - 5 * 100.2)
    assert acct.cash == pytest.approx(1000 + acct.positions["X"].realised_pnl)


def test_replay_and_positions_frame():
    accts = replay({"USD": 10_000}, [("A", "BUY", 10, 100, 0, "USD"), ("A", "SELL", 4, 110, 0, "USD")])
    f = positions_frame(accts, {"A": 120})
    assert (
        f.loc[0, "Quantity"] == 6
        and f.loc[0, "Unrealised P&L"] == pytest.approx(120)
        and f.loc[0, "Realised P&L"] == pytest.approx(40)
    )
    with pytest.raises(OrderRejected):
        replay({"USD": 100}, [("A", "BUY", 10, 100, 0, "USD")])


# ---------------- predictions ----------------
def _closes(vals, start="2025-01-02"):
    return pd.DataFrame({"date": pd.bdate_range(start, periods=len(vals), tz="UTC"), "close": vals})


@pytest.mark.parametrize(
    "direction,final,outcome",
    [
        ("Bullish", 105, "Correct"),
        ("Bullish", 101, "Incorrect"),
        ("Bearish", 95, "Correct"),
        ("Bearish", 99, "Incorrect"),
        ("Neutral", 101, "Correct"),
        ("Neutral", 105, "Incorrect"),
    ],
)
def test_prediction_scoring(direction, final, outcome):
    closes = _closes([100, 100, 100, final, 1])  # as_of is day 0; horizon 3 → 4th row
    ev = predictions.evaluate(direction, 100, closes.date.iloc[0], closes, horizon_bars=3, threshold_pct=2)
    assert ev.outcome == outcome and ev.realised_return == pytest.approx(final / 100 - 1)


def test_prediction_pending_until_horizon_and_ignores_past_bars():
    closes = _closes([200, 100, 101])
    ev = predictions.evaluate("Bullish", 100, closes.date.iloc[1], closes, horizon_bars=2, threshold_pct=1)
    assert ev.outcome == "Pending" and ev.bars_available == 1
    assert predictions.evaluate("Bullish", 100, "2025-01-03", closes, 1, 0.5).outcome == "Correct"  # naive ts → UTC


def test_hit_rate():
    assert predictions.hit_rate(["Correct", "Incorrect", "Pending", "Correct"]) == (pytest.approx(2 / 3), 3)
    assert predictions.hit_rate(["Pending"]) == (None, 0)


# ---------------- fundamentals ----------------
def test_fundamentals_allow_losses_and_negative_equity():
    r = fundamentals.ratios(revenue=100, prior_revenue=120, net_profit=-15, operating_cf=-5, debt=50, equity=-10)
    assert r["revenue_growth"] == pytest.approx(-1 / 6) and r["net_margin"] == pytest.approx(-0.15)
    assert r["debt_to_equity"] is None
    text = " ".join(r["flags"])
    assert "Loss-making" in text and "negative" in text and "declined" in text


def test_fundamentals_cash_conversion():
    r = fundamentals.ratios(100, 90, 10, 5, 20, 40)
    assert r["cash_conversion"] == 0.5 and r["debt_to_equity"] == 0.5 and any("80%" in f for f in r["flags"])


# ---------------- data helpers ----------------
def test_ticker_cleaning():
    assert clean_ticker(" bhp.ax ") == "BHP.AX" and clean_ticker("^gspc") == "^GSPC"
    for bad in ["", "DROP TABLE", "a" * 20, "../x"]:
        with pytest.raises(DataError):
            clean_ticker(bad)
    assert ticker_from_filename("nvda_2024.csv") == "NVDA"
    assert ticker_from_filename("my data (1).csv") is None


# ---------------- AI research brief ----------------
@pytest.fixture
def facts():
    d = normalize_ohlcv(make_ohlcv())
    rep = analyse(d)
    return research.build_facts("TEST", rep, run_backtest(d))


class FakeClient:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


def test_facts_are_json_serialisable_and_complete(facts):
    s = json.dumps(facts, default=str)
    for k in ("close", "technical_score_0_100", "rules_met", "backtest_ema_rsi", "annualised_volatility_pct"):
        assert k in s


def test_llm_brief_sends_only_fact_sheet_and_verifies_numbers(facts):
    good = f"### Bull case\n- Close is {facts['close']} and RSI {facts['rsi14']}."
    c = FakeClient(good)
    b = research.llm_brief(facts, client=c, model="m")
    assert b.source == "llm" and b.unverified_numbers == []
    call = c.calls[0]
    assert call["model"] == "m" and "ONLY facts" in call["system"]
    assert "TEST" in call["messages"][0]["content"] and len(call["messages"]) == 1

    bad = research.llm_brief(facts, client=FakeClient(good + " Analysts target 987.65 by June."))
    assert "987.65" in bad.unverified_numbers


def test_llm_failure_falls_back_to_rules(facts):
    b = research.llm_brief(facts, client=FakeClient(exc=TimeoutError()))
    assert b.source == "rules" and "unavailable" in b.markdown


def test_no_key_uses_rules(facts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b = research.llm_brief(facts)
    assert b.source == "rules" and "### Bull case" in b.markdown
    assert research.unverified_numbers(b.markdown, facts) == []  # rules brief is fully grounded


def test_build_facts_tolerates_short_history():
    rep = analyse(from_closes(np.linspace(100, 110, 35)))
    f = research.build_facts("S", rep)
    assert f["sma200"] is None and "backtest_ema_rsi" not in f
