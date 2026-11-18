import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_ohlcv(n=260, seed=42, drift=0.0004, vol=0.012, freq="B", start="2024-01-01"):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "Date": pd.date_range(start, periods=n, freq=freq),
            "Open": open_,
            "High": np.maximum(open_, close) * 1.01,
            "Low": np.minimum(open_, close) * 0.99,
            "Close": close,
            "Volume": rng.integers(100_000, 900_000, n),
        }
    )


def from_closes(closes, start="2024-01-01", freq="B"):
    c = np.asarray(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=len(c), freq=freq, tz="UTC"),
            "open": o,
            "high": np.maximum(o, c),
            "low": np.minimum(o, c),
            "close": c,
            "volume": 1000.0,
        }
    )


@pytest.fixture
def ohlcv():
    return make_ohlcv()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setenv("MARKETMIND_DB_PATH", str(p))
    return p
