"""Practice mode: make calls on historical charts and get scored instantly.

A round picks a random cut-off bar. Everything the user sees (chart, indicators, score)
is computed from bars up to and including the cut-off only, so there is no look-ahead.
The next ``horizon`` bars decide the outcome, using the same objective rule as live predictions.

Blind mode hides the ticker and dates and rebases prices to 100 at the start of the
visible window, so people can't lean on remembering what a famous stock did.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import predictions
from .engine import analyse
from .patterns import scan, tags_at_end

MIN_VISIBLE = 60  # bars shown before the cut-off
DEFAULT_UNIVERSE = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "BHP.AX", "CBA.AX", "CSL.AX", "WES.AX")


@dataclass(frozen=True)
class Round:
    ticker: str
    cut: int  # index of the last visible bar
    horizon: int
    visible: pd.DataFrame
    future: pd.DataFrame
    blind: bool
    scale: float  # multiply real prices by this to get displayed prices
    real_as_of: pd.Timestamp  # true date of the cut-off bar (stored; shown after the reveal)

    @property
    def reference_price(self) -> float:
        """Last visible close, in displayed units."""
        return float(self.visible["close"].iloc[-1])

    @property
    def real_reference_price(self) -> float:
        return self.reference_price / self.scale


def pick_round(
    df: pd.DataFrame, ticker: str, horizon: int, rng: np.random.Generator, blind: bool = True, window: int = 180
) -> Round:
    """Choose a random cut-off with at least ``MIN_VISIBLE`` bars before it and ``horizon`` bars after."""
    if horizon < 1:
        raise ValueError("Horizon must be at least 1 bar.")
    lo, hi = MIN_VISIBLE - 1, len(df) - horizon - 1
    if hi < lo:
        raise ValueError(f"Need at least {MIN_VISIBLE + horizon} bars of history for a {horizon}-bar round.")
    cut = int(rng.integers(lo, hi + 1))
    start = max(0, cut + 1 - window)
    visible = df.iloc[start : cut + 1].reset_index(drop=True)
    future = df.iloc[cut + 1 : cut + 1 + horizon].reset_index(drop=True)
    scale = 1.0
    if blind:
        scale = 100.0 / float(visible["close"].iloc[0])
        visible, future = _disguise(visible, scale), _disguise(future, scale, offset=len(visible))
    return Round(ticker, cut, horizon, visible, future, blind, scale, pd.Timestamp(df["date"].iloc[cut]))


def _disguise(d: pd.DataFrame, scale: float, offset: int = 0) -> pd.DataFrame:
    """Rebase prices and replace real dates with a neutral business-day calendar."""
    out = d.copy()
    for c in ("open", "high", "low", "close"):
        out[c] = out[c] * scale
    out["date"] = pd.bdate_range("2000-01-03", periods=offset + len(d), tz="UTC")[offset:]
    if "adj_close" in out:
        out = out.drop(columns="adj_close")
    return out


def snapshot(r: Round) -> dict:
    """The analysis a user sees before calling, computed from visible bars only."""
    return analyse(r.visible)


def score(r: Round, view: str, threshold_pct: float) -> predictions.Evaluation:
    closes = r.future[["date", "close"]]
    return predictions.evaluate(view, r.reference_price, r.visible["date"].iloc[-1], closes, r.horizon, threshold_pct)


def pattern_tags(r: Round) -> list[tuple[str, int, str]]:
    """Patterns confirmed in the last 10 visible bars or forming at the cut-off (visible bars only)."""
    return tags_at_end(scan(r.visible), r.visible)
