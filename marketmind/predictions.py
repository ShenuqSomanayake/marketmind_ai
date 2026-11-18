"""Objective, rule-based scoring of timestamped directional predictions.

A prediction records the reference close and the date of that bar (``as_of``).
After ``horizon_bars`` further bars exist, the realised return decides the outcome:

* Bullish  → correct if return >  +threshold
* Bearish  → correct if return <  −threshold
* Neutral  → correct if |return| ≤ threshold

The user cannot edit outcomes, so the hit rate is not self-graded.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DIRECTIONS = ("Bullish", "Neutral", "Bearish")


@dataclass(frozen=True)
class Evaluation:
    outcome: str  # "Pending" | "Correct" | "Incorrect"
    realised_return: float | None
    bars_available: int


def evaluate(
    direction: str, reference_price: float, as_of, closes: pd.DataFrame, horizon_bars: int, threshold_pct: float
) -> Evaluation:
    """``closes`` must have ``date`` and ``close`` columns; only bars strictly after ``as_of`` count."""
    if direction not in DIRECTIONS:
        raise ValueError(f"Unknown direction {direction!r}")
    if horizon_bars < 1 or reference_price <= 0:
        raise ValueError("Horizon must be ≥1 bar and reference price positive.")
    as_of = pd.Timestamp(as_of)
    as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
    dates = pd.to_datetime(closes["date"], utc=True)
    after = closes.loc[dates > as_of].sort_values("date")
    if len(after) < horizon_bars:
        return Evaluation("Pending", None, len(after))
    ret = float(after["close"].iloc[horizon_bars - 1] / reference_price - 1)
    thr = threshold_pct / 100
    correct = {"Bullish": ret > thr, "Bearish": ret < -thr, "Neutral": abs(ret) <= thr}[direction]
    return Evaluation("Correct" if correct else "Incorrect", ret, len(after))


def hit_rate(outcomes: list[str]) -> tuple[float | None, int]:
    scored = [o for o in outcomes if o in ("Correct", "Incorrect")]
    if not scored:
        return None, 0
    return sum(o == "Correct" for o in scored) / len(scored), len(scored)
