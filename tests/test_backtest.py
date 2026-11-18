import numpy as np
import pandas as pd
import pytest
from conftest import from_closes, make_ohlcv

from marketmind.backtest import StrategyParams, metrics, run_backtest
from marketmind.engine import normalize_ohlcv


@pytest.fixture
def data():
    return normalize_ohlcv(make_ohlcv(600, seed=7))


def test_no_lookahead_truncation_invariance(data):
    full = run_backtest(data, oos_fraction=0)["series"]
    part = run_backtest(data.iloc[:400], oos_fraction=0)["series"]
    assert (full["position"].iloc[:400].to_numpy() == part["position"].to_numpy()).all()
    assert np.allclose(full["strategy_return"].iloc[:400], part["strategy_return"])


def test_position_lags_signal_by_one_bar(data):
    s = run_backtest(data)["series"]
    assert (s["position"].iloc[1:].to_numpy() == s["signal"].iloc[:-1].to_numpy()).all()
    assert s["position"].iloc[0] == 0


def test_benchmark_is_buy_and_hold(data):
    r = run_backtest(data)
    assert r["benchmark"]["total_return"] == pytest.approx(data["close"].iloc[-1] / data["close"].iloc[0] - 1)


def test_costs_charged_per_position_change(data):
    free = run_backtest(data, StrategyParams(fee_bps=0, slippage_bps=0))
    paid = run_backtest(data, StrategyParams(fee_bps=10, slippage_bps=5))
    changes = free["series"]["turnover"].sum()
    assert changes > 0
    diff = free["series"]["strategy_return"].sum() - paid["series"]["strategy_return"].sum()
    assert diff == pytest.approx(changes * 15 / 10_000)


def test_always_long_equals_benchmark_minus_entry_cost():
    # Down for 100 bars, then up: exactly one crossover after warm-up, never reversed.
    d = from_closes(np.r_[100 * 0.997 ** np.arange(100), 100 * 0.997**99 * 1.004 ** np.arange(1, 151)])
    r = run_backtest(d, StrategyParams(fee_bps=0, slippage_bps=0), oos_fraction=0)
    first_in = int(r["series"]["position"].to_numpy().argmax())
    expected = d["close"].iloc[-1] / d["close"].iloc[first_in - 1] - 1
    assert r["full"]["total_return"] == pytest.approx(expected)
    assert len(r["trades"]) == 1 and bool(r["trades"]["open"].iloc[0])


def test_trade_list_matches_equity(data):
    r = run_backtest(data, StrategyParams(fee_bps=0, slippage_bps=0), oos_fraction=0)
    compounded = float(np.prod(1 + r["trades"]["gross_return"]) - 1)
    assert compounded == pytest.approx(r["full"]["total_return"], rel=1e-9)


def test_oos_segments_partition_history(data):
    r = run_backtest(data, oos_fraction=0.3)
    t = r["table"]
    assert set(t.segment) == {"Full period", "In-sample", "Out-of-sample"}
    ins = t[(t.segment == "In-sample") & (t.series == "Buy & hold")].total_return.iloc[0]
    oos = t[(t.segment == "Out-of-sample") & (t.series == "Buy & hold")].total_return.iloc[0]
    full = t[(t.segment == "Full period") & (t.series == "Buy & hold")].total_return.iloc[0]
    assert (1 + ins) * (1 + oos) - 1 == pytest.approx(full)


def test_metrics_known_values():
    r = pd.Series([0.01] * 252)
    m = metrics(r, 252)
    assert m["total_return"] == pytest.approx(1.01**252 - 1)
    assert m["cagr"] == pytest.approx(1.01**252 - 1)
    assert m["max_drawdown"] == 0
    dd = metrics(pd.Series([0.1, -0.5, 0.2]), 252)["max_drawdown"]
    assert dd == pytest.approx(-0.5)


def test_weekly_data_uses_52_periods():
    d = normalize_ohlcv(make_ohlcv(300, freq="W"))
    assert run_backtest(d)["periods_per_year"] == 52


@pytest.mark.parametrize("p", [StrategyParams(fast=50, slow=20), StrategyParams(fee_bps=-1)])
def test_invalid_params(p, data):
    with pytest.raises(ValueError):
        run_backtest(data, p)


def test_too_short_history():
    with pytest.raises(ValueError, match="Need at least"):
        run_backtest(normalize_ohlcv(make_ohlcv(40)))
