import numpy as np
import pandas as pd
import pytest
from conftest import from_closes, make_ohlcv

from marketmind.engine import (
    add_indicators,
    analyse,
    annualised_volatility,
    label_for,
    normalize_ohlcv,
    period_return,
    periods_per_year,
    rsi,
    unusual_activity,
)


def test_normalize_accepts_yahoo_style_and_aliases():
    raw = make_ohlcv().rename(columns={"Date": "Datetime", "Volume": "Vol"})
    raw["Adj Close"] = raw["Close"]
    raw["Close"] = raw["Close"].map(lambda x: f"{x:,.4f}")  # thousands separators as text
    d = normalize_ohlcv(raw)
    assert list(d.columns) == ["date", "open", "high", "low", "close", "volume", "adj_close"]
    assert d["date"].is_monotonic_increasing and str(d["date"].dt.tz) == "UTC"


def test_normalize_handles_multiindex_and_dedupes():
    raw = make_ohlcv(40)
    raw = pd.concat([raw, raw.tail(1)])  # duplicate last date
    raw.columns = pd.MultiIndex.from_tuples([(c, "NVDA") for c in raw.columns])
    assert len(normalize_ohlcv(raw)) == 40


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda d: d.drop(columns="Volume"), "Missing required"),
        (lambda d: d.head(10), "Only 10"),
        (lambda d: d.assign(Close=-1.0), "positive"),
        (lambda d: d.assign(High=d.Low * 0.5), "inconsistent"),
    ],
)
def test_normalize_rejects_bad_data(mutate, msg):
    with pytest.raises(ValueError, match=msg):
        normalize_ohlcv(mutate(make_ohlcv(40)))


def test_rsi_matches_stockcharts_wilder_example():
    # StockCharts ChartSchool worked example. Their table shows 70.53, 66.32, 66.55, 69.41, 66.36, 57.97 because the
    # spreadsheet rounds intermediate averages to 2 dp; full precision gives the values below (all within 0.07).
    closes = pd.Series(
        [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
            46.03,
            46.41,
            46.22,
            45.64,
        ]
    )
    r = rsi(closes, 14)
    assert r.iloc[:14].isna().all()
    assert r.iloc[14:].round(2).tolist() == pytest.approx([70.46, 66.25, 66.48, 69.35, 66.29, 57.92], abs=0.01)
    stockcharts = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]
    assert np.allclose(r.iloc[14:], stockcharts, atol=0.08)


def test_rsi_edges():
    flat = pd.Series([100.0] * 30)
    up = pd.Series(np.arange(1, 31, dtype=float))
    down = pd.Series(np.arange(30, 0, -1, dtype=float))
    assert rsi(flat).iloc[-1] == 50
    assert rsi(up).iloc[-1] == 100
    assert rsi(down).iloc[-1] == pytest.approx(0)


def test_indicators_hand_checked():
    d = add_indicators(normalize_ohlcv(make_ohlcv()))
    c = d["close"]
    assert d["sma200"].notna().sum() == 61
    assert d["sma200"].iloc[-1] == pytest.approx(c.tail(200).mean())
    # EMA(20) recursion: ema_t = a*c_t + (1-a)*ema_{t-1}, a = 2/21
    a = 2 / 21
    assert d["ema20"].iloc[-1] == pytest.approx(a * c.iloc[-1] + (1 - a) * d["ema20"].iloc[-2])
    assert d["bb_upper"].iloc[-1] == pytest.approx(c.tail(20).mean() + 2 * c.tail(20).std(ddof=0))
    assert d["macd_hist"].iloc[-1] == pytest.approx(d["macd"].iloc[-1] - d["macd_signal"].iloc[-1])
    assert (d["atr14"].dropna() > 0).all()


def test_period_return_is_a_return_not_a_ratio():
    d = from_closes([100] * 10 + [110] * 21)
    assert period_return(d["close"], 20) == pytest.approx(0.0)
    d = from_closes(list(np.linspace(100, 120, 31)))
    assert period_return(d["close"], 20) == pytest.approx(120 / d["close"].iloc[-21] - 1)
    assert np.isnan(period_return(d["close"], 40))


@pytest.mark.parametrize("freq,expected", [("B", 252), ("W", 52), ("MS", 12)])
def test_periods_per_year_inferred(freq, expected):
    assert periods_per_year(pd.Series(pd.date_range("2020-01-01", periods=60, freq=freq))) == expected


def test_periods_per_year_intraday():
    days = pd.bdate_range("2024-01-01", periods=10)
    stamps = pd.DatetimeIndex([dd + pd.Timedelta(hours=9 + h) for dd in days for h in range(7)])
    assert periods_per_year(pd.Series(stamps)) == 252 * 7


def test_weekly_volatility_annualised_with_52():
    d = from_closes(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, 80))), freq="W")
    expected = d["close"].pct_change().std() * np.sqrt(52)
    assert analyse(d)["volatility_ann"] == pytest.approx(expected)
    assert annualised_volatility(d["close"], 52) == pytest.approx(expected)


def test_score_is_sum_of_rules_and_labelled():
    rep = analyse(normalize_ohlcv(make_ohlcv()))
    assert rep["score"] == max(0, min(100, 50 + sum(r.contribution for r in rep["rules"])))
    assert rep["label"] == label_for(rep["score"])
    assert len(rep["evidence"]) == sum(r.met is True for r in rep["rules"])


def test_strong_uptrend_scores_high_and_downtrend_low():
    up = from_closes(100 * 1.004 ** np.arange(260))
    down = from_closes(100 * 0.996 ** np.arange(260))
    assert analyse(up)["score"] >= 70
    assert analyse(down)["score"] <= 30


def test_sma200_rule_not_evaluable_on_short_history():
    rep = analyse(normalize_ohlcv(make_ohlcv(60)))
    rule = next(r for r in rep["rules"] if "200" in r.name)
    assert rule.met is None and rule.contribution == 0 and rep["sma200"] is None


def test_unusual_activity_flags_spike():
    d = from_closes(list(100 + np.random.default_rng(3).normal(0, 0.2, 100)) + [115])
    d.loc[d.index[-1], "volume"] = 10_000
    flags = unusual_activity(d)
    assert any("Volume" in f for f in flags) and any("standard deviations" in f for f in flags)
