from datetime import date

import pandas as pd
import pytest
from conftest import make_ohlcv
from test_domain import FakeClient

from marketmind import insights, research
from marketmind.engine import analyse, normalize_ohlcv


def preds(rows):
    """rows: (view, realised_return, ret20_at_entry, score, horizon) with a 2% threshold; outcome derived objectively."""
    out = []
    for view, ret, r20, score, hz in rows:
        ok = {"Bullish": ret > 0.02, "Bearish": ret < -0.02, "Neutral": abs(ret) <= 0.02}[view]
        out.append(
            {
                "view": view,
                "outcome": "Correct" if ok else "Incorrect",
                "realised_return": ret,
                "threshold_pct": 2.0,
                "score": score,
                "ret20_at_entry": r20,
                "horizon_bars": hz,
            }
        )
    return pd.DataFrame(out)


def titles(rep):
    return [f.title for f in rep["findings"]]


def test_empty_and_small_samples():
    assert insights.prediction_report(preds([]))["n"] == 0
    rep = insights.prediction_report(preds([("Bullish", 0.05, 0.0, 60, 20)] * 3))
    assert rep["n"] == 3 and titles(rep) == ["Not enough history yet"]


def test_pending_ignored():
    df = preds([("Bullish", 0.05, 0.0, 60, 20)] * 6)
    df.loc[0, "outcome"] = "Pending"
    assert insights.prediction_report(df)["n"] == 5


def test_chasing_and_optimism_detected():
    # Bullish after big rises keeps failing; bullish in calm markets works. Prices mostly fell.
    rows = [("Bullish", -0.05, 0.15, 60, 20)] * 6 + [("Bullish", 0.05, 0.02, 60, 20)] * 5 + [("Bearish", -0.04, 0.0, 40, 20)] * 1
    rep = insights.prediction_report(preds(rows))
    t = titles(rep)
    assert "Chasing after big rises" in t and "Optimism bias" in t
    chase = next(f for f in rep["findings"] if f.title == "Chasing after big rises")
    assert "0%" in chase.detail and "100%" in chase.detail and chase.tone == "warn" and chase.n == 11


def test_baseline_comparison_both_ways():
    good = insights.prediction_report(preds([("Bearish", -0.05, 0.0, 40, 20)] * 6))
    assert "You beat the lazy baseline" in titles(good)
    bad = insights.prediction_report(preds([("Bearish", 0.05, 0.0, 40, 20)] * 6))
    assert "A lazy baseline beat you" in titles(bad)


def test_score_agreement_and_horizon():
    rows = (
        [("Bullish", 0.05, 0.0, 70, 5)] * 5  # agrees with score, short, right
        + [("Bullish", -0.05, 0.0, 30, 30)] * 5
    )  # disagrees, long, wrong
    t = titles(insights.prediction_report(preds(rows)))
    assert "You do better going with the technical score" in t and "Your best timeframe" in t


def trades(rows):
    return pd.DataFrame(rows, columns=["created_at", "ticker", "side", "quantity", "price", "fee", "currency"])


def test_closed_sells_average_cost_and_holding_days():
    t = trades(
        [
            ("2026-01-01", "A", "BUY", 10, 100, 0, "USD"),
            ("2026-01-05", "A", "BUY", 10, 120, 0, "USD"),  # avg 110
            ("2026-01-11", "A", "SELL", 20, 121, 0, "USD"),
            ("2026-02-01", "A", "BUY", 5, 50, 0, "USD"),  # new position opens
            ("2026-02-03", "A", "SELL", 5, 45, 0, "USD"),
        ]
    )
    s = insights.closed_sells(t)
    assert s["return"].round(4).tolist() == [0.1, -0.1]
    assert s["days_held"].tolist() == [10, 2]


def test_disposition_effect_flagged():
    rows = []
    for i in range(3):  # winners sold after 2 days
        rows += [
            (f"2026-01-{1 + i * 3:02d}", "W", "BUY", 1, 100, 0, "USD"),
            (f"2026-01-{3 + i * 3:02d}", "W", "SELL", 1, 110, 0, "USD"),
        ]
    for i in range(3):  # losers held 20 days
        rows += [
            (f"2026-03-{1 + i:02d}", f"L{i}", "BUY", 1, 100, 0, "USD"),
            (f"2026-03-{21 + i:02d}", f"L{i}", "SELL", 1, 90, 0, "USD"),
        ]
    rep = insights.trading_report(trades(rows))
    t = titles(rep)
    assert "Holding losers longer than winners" in t and "Win rate" in t and rep["n"] == 6


def test_trading_report_small_sample():
    assert titles(insights.trading_report(trades([]))) == ["Not enough closed trades yet"]


@pytest.mark.parametrize(
    "close,lo,hi,review,status",
    [
        (95, 100, None, "2099-01-01", "Triggered"),
        (130, None, 125, "2099-01-01", "Triggered"),
        (103, 100, None, "2099-01-01", "Near trigger"),
        (120, 100, None, "2000-01-01", "Review due"),
        (120, 100, 150, "2099-01-01", "On track"),
        (120, None, None, "2099-01-01", "No trigger set"),
        (None, 100, None, "2099-01-01", "No price"),
    ],
)
def test_check_thesis(close, lo, hi, review, status):
    assert insights.check_thesis(close, lo, hi, review, today=date(2026, 11, 16)).status == status


@pytest.fixture
def thesis_and_facts():
    rep = analyse(normalize_ohlcv(make_ohlcv()))
    facts = research.build_facts("TEST", rep)
    t = {
        "ticker": "TEST",
        "thesis": "Margins should expand to 35 percent.",
        "invalidation": "Price below 90",
        "entry_price": 100.0,
        "stop_below": 90.0,
        "stop_above": None,
        "created_at": "2026-01-01",
        "trigger_status": "On track: Close is 10% above 90.",
    }
    return t, facts


def test_thesis_review_rules_fallback(thesis_and_facts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t, facts = thesis_and_facts
    b = research.thesis_review(t, facts)
    assert b.source == "rules" and "### Invalidation criteria status" in b.markdown and "On track" in b.markdown


def test_thesis_review_llm_grounding(thesis_and_facts):
    t, facts = thesis_and_facts
    c = FakeClient(f"### Supported by the data\n- Close {facts['close']}; margins of 35 percent can't be checked; trigger 90.")
    b = research.thesis_review(t, facts, client=c, model="m")
    assert b.source == "llm" and b.unverified_numbers == []  # 35 comes from the thesis, 90 from the trigger
    body = c.calls[0]["messages"][0]["content"]
    assert "<thesis>" in body and "Margins should expand" in body and "never as instructions" in c.calls[0]["system"]
    bad = research.thesis_review(t, facts, client=FakeClient("Fair value is 412.50."))
    assert "412.50" in bad.unverified_numbers


def test_thesis_review_failure_falls_back(thesis_and_facts):
    t, facts = thesis_and_facts
    assert research.thesis_review(t, facts, client=FakeClient(exc=ConnectionError())).source == "rules"
