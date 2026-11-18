"""Chart patterns, technical indicators, track records and pattern-aware insights."""

import numpy as np
import pandas as pd
import pytest
from conftest import make_ohlcv

from marketmind import insights
from marketmind import patterns as P
from marketmind.engine import normalize_ohlcv
from marketmind.technicals import adx, cluster_levels, fibonacci, obv, stochastic, technical_summary


def path(start, segments, vol=1000.0, start_date="2020-01-01"):
    """Piecewise-linear closes: segments = [(target, bars), ...]."""
    closes = [start]
    for target, bars in segments:
        closes += list(np.linspace(closes[-1], target, bars + 1)[1:])
    c = np.array(closes)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start_date, periods=len(c), tz="UTC"),
            "open": o,
            "high": np.maximum(o, c) * 1.003,
            "low": np.minimum(o, c) * 0.997,
            "close": c,
            "volume": np.full(len(c), vol),
        }
    )


def names(df):
    return [e.name for e in P.scan(df).events]


def first(df, name):
    return next(e for e in P.scan(df).events if e.name == name)


# ---------------- patterns ----------------
def test_double_top_confirmed_on_neckline_break():
    d = path(80, [(100, 25), (90, 15), (100.5, 15), (82, 25)])
    e = first(d, "Double top")
    assert e.direction == -1 and e.level == pytest.approx(d["low"].iloc[40], rel=0.01)
    assert d["close"].iloc[e.confirmed_at] < e.level <= d["close"].iloc[e.confirmed_at - 1]  # first close below


def test_double_bottom():
    d = path(120, [(100, 25), (110, 15), (99.5, 15), (118, 25)])
    e = first(d, "Double bottom")
    assert e.direction == 1 and d["close"].iloc[e.confirmed_at] > e.level


def test_head_and_shoulders_and_inverse():
    hs = path(80, [(100, 20), (92, 12), (108, 14), (92.5, 14), (100.5, 12), (80, 25)])
    e = first(hs, "Head and shoulders")
    assert e.direction == -1 and len(e.points) == 5
    ihs = path(120, [(100, 20), (108, 12), (92, 14), (107.5, 14), (99.5, 12), (120, 25)])
    assert first(ihs, "Inverse head and shoulders").direction == 1


def test_symmetrical_triangle_breakout_direction():
    up = path(100, [(110, 15), (90, 15), (106, 12), (94, 12), (118, 25)])
    e = first(up, "Symmetrical triangle")
    assert e.direction == 1
    down = path(100, [(110, 15), (90, 15), (106, 12), (94, 12), (101, 6), (80, 20)])
    assert first(down, "Symmetrical triangle").direction == -1


def test_ascending_triangle_classified():
    d = path(90, [(100, 15), (88, 12), (100.1, 12), (93, 12), (112, 20)])
    assert "Ascending triangle" in names(d)


def test_resistance_breakout_needs_volume():
    segs = [(100, 20), (92, 12), (100.3, 12), (93, 12), (108, 20)]
    quiet = path(90, segs)
    assert "Resistance breakout" not in names(quiet)
    loud = quiet.copy()
    loud.loc[loud.index >= 60, "volume"] = 5000.0
    e = first(loud, "Resistance breakout")
    assert e.direction == 1 and e.level == pytest.approx(100.2, abs=0.5) and e.price >= e.level * 1.005


def test_bullish_rsi_divergence():
    warmup = [(101, 2), (99, 2)] * 8  # 32 bars so RSI is defined before the first low
    slow = [(86, 4), (88, 2), (84, 4), (86, 2), (82, 4), (84, 2), (79, 4)]  # grinding lower with bounces
    d = path(100, [*warmup, (80, 8), (90, 12), *slow, (90, 15)])
    e = first(d, "Bullish RSI divergence")
    assert e.direction == 1 and e.points[1][1] < e.points[0][1]  # lower low in price


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_no_lookahead_truncation_invariance(seed):
    d = normalize_ohlcv(make_ohlcv(900, seed=seed, vol=0.02))
    full = P.scan(d).events
    for m in (300, 600, 850):
        part = P.scan(d.iloc[:m]).events
        assert [(e.name, e.confirmed_at, e.price) for e in full if e.confirmed_at < m] == [
            (e.name, e.confirmed_at, e.price) for e in part
        ]


def test_pivots_known_only_after_k_bars():
    d = normalize_ohlcv(make_ohlcv(400, seed=3, vol=0.02))
    res = P.scan(d)
    assert res.pivots and all(p.known_at >= p.idx + P.PIVOT_K for p in res.pivots)
    kinds = [p.kind for p in res.pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False))  # strictly alternating


def test_forming_pattern_reported():
    d = path(80, [(100, 25), (90, 15), (100.5, 15), (95, 8)])  # second top in, neckline not yet broken
    res = P.scan(d)
    assert any(c.name == "Double top" for c in res.forming)
    assert ("Double top", -1, "forming") in P.tags_at_end(res, d)


def test_tags_roundtrip():
    tags = [("Double top", -1, "confirmed"), ("Symmetrical triangle", 0, "forming")]
    assert P.decode_tags(P.encode_tags(tags)) == tags
    assert P.decode_tags(None) == [] and P.decode_tags(float("nan")) == []
    assert P.describe_tags(tags)[1] == "Symmetrical triangle (direction open, forming)"


# ---------------- track record ----------------
def test_track_record_matches_manual_calculation():
    d = normalize_ohlcv(make_ohlcv(300, seed=9, vol=0.02))
    c = d["close"].to_numpy()
    ev = [P.Event("Test", 1, i, d.date.iloc[i], float(c[i]), None) for i in (50, 100, 150, 200)]
    tr = P.track_record(d, ev, horizon=10, threshold_pct=1.0).iloc[0]
    fwd = np.array([c[i + 10] / c[i] - 1 for i in (50, 100, 150, 200)])
    allf = c[10:] / c[:-10] - 1
    assert tr["Occurrences"] == 4 and tr["Worked"] == pytest.approx((fwd > 0.01).mean())
    assert tr["Base rate"] == pytest.approx((allf > 0.01).mean()) and tr["Verdict"] == "Too few to judge"
    late = [P.Event("Late", -1, 295, d.date.iloc[295], float(c[295]), None)]
    assert P.track_record(d, late, horizon=10).empty  # no future bars yet → not counted


def test_edge_significance():
    assert P.verdict(0.9, 0.5, 30) == "Better than base rate"
    assert P.verdict(0.1, 0.5, 30) == "Worse than base rate"
    assert P.verdict(0.55, 0.5, 30) == "No clear edge"
    assert P.verdict(1.0, 0.5, 5) == "Too few to judge"
    assert P.edge_z(0.6, 0.5, 100) == pytest.approx(2.0)
    assert np.isnan(P.edge_z(0.5, 1.0, 10))


# ---------------- technicals ----------------
def test_adx_trend_strength():
    up = path(100, [(200, 120)])
    a = adx(up).iloc[-1]
    assert a.adx > 40 and a.plus_di > a.minus_di
    chop = path(100, [(105, 3), (100, 3)] * 20)
    assert adx(chop).adx.iloc[-1] < adx(up).adx.iloc[-1]


def test_stochastic_bounds_and_flat():
    d = normalize_ohlcv(make_ohlcv(200))
    s = stochastic(d).dropna()
    assert s.stoch_k.between(0, 100).all() and s.stoch_d.between(0, 100).all()
    flat = path(100, [(100, 40)])
    flat[["high", "low"]] = 100.0
    assert stochastic(flat).stoch_k.iloc[-1] == 50


def test_obv_signs():
    d = pd.DataFrame({"close": [10, 11, 10.5, 10.5, 12], "volume": [100, 200, 300, 400, 500]})
    assert obv(d).tolist() == [0, 200, -100, -100, 400]


def test_fibonacci_up_swing():
    d = path(100, [(200, 60), (180, 20)])
    f = fibonacci(d)
    hi, lo = f["swing_high"], f["swing_low"]
    assert f["direction"] == "up-swing" and f["levels"]["50.0%"] == pytest.approx((hi + lo) / 2)
    assert f["levels"]["61.8%"] == pytest.approx(hi - 0.618 * (hi - lo))


def test_cluster_levels():
    Pv = P.Pivot
    t = pd.Timestamp("2026-01-01")
    piv = [
        Pv(1, 100.0, "H", 6, t),
        Pv(5, 100.8, "H", 10, t),
        Pv(9, 90.0, "L", 14, t),
        Pv(12, 90.5, "L", 17, t),
        Pv(20, 120.0, "H", 25, t),
    ]
    lv = cluster_levels(piv, 95.0, t)
    assert [(round(x.price, 2), x.kind, x.touches) for x in lv] == [(90.25, "support", 2), (100.4, "resistance", 2)]


def test_technical_summary_rows():
    rows = technical_summary(normalize_ohlcv(make_ohlcv(300)))
    areas = [r["Area"] for r in rows]
    assert {"Trend strength", "Stochastic (14,3,3)", "Volume flow (OBV)", "Volatility regime"} <= set(areas)


# ---------------- pattern-aware insights ----------------
def test_pattern_reading_findings():
    rows = []
    for _ in range(6):  # went with a confirmed bearish double top → right
        rows.append(("Bearish", -0.05, "Double top|-1|confirmed"))
    for _ in range(6):  # went against a confirmed bullish breakout → wrong
        rows.append(("Bearish", 0.05, "Resistance breakout|1|confirmed"))
    df = pd.DataFrame([{"view": v, "outcome": ("Correct" if (v == "Bearish" and r < -0.02) else "Incorrect"), "realised_return": r,
                        "threshold_pct": 2.0, "score": 50, "ret20_at_entry": 0.0, "horizon_bars": 20, "patterns_at_entry": t}
                       for v, r, t in rows])  # fmt: skip
    rep = insights.prediction_report(df)
    titles = [f.title for f in rep["findings"]]
    assert "You do better going with confirmed patterns" in titles and "Patterns you read best and worst" in titles
    assert set(rep["by_pattern"]["pattern"]) == {"Double top", "Resistance breakout"}


def test_practice_tags_are_scale_invariant():
    from marketmind import practice

    d = normalize_ohlcv(make_ohlcv(600, seed=21, vol=0.02))
    a = practice.pick_round(d, "X", 20, np.random.default_rng(4), blind=True)
    b = practice.pick_round(d, "X", 20, np.random.default_rng(4), blind=False)
    assert [t[0] for t in practice.pattern_tags(a)] == [t[0] for t in practice.pattern_tags(b)]
