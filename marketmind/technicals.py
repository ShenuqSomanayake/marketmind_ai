"""Extended technical toolkit: trend strength, oscillators, volume flow, levels and a plain-English summary.

Every function is causal (a value at bar *t* uses bars ≤ *t* only) unless its docstring says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import wilder_smooth

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #
def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder's Directional Movement System: +DI, −DI and ADX (trend strength, 0–100)."""
    h, low, c = df["high"], df["low"], df["close"]
    up, down = h.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1)
    valid = c.shift().notna()
    atr = wilder_smooth(tr.where(valid), period)
    plus_di = 100 * wilder_smooth(plus_dm.where(valid), period) / atr
    minus_di = 100 * wilder_smooth(minus_dm.where(valid), period) / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / denom).fillna(0.0).where(plus_di.notna())
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": wilder_smooth(dx, period)})


def stochastic(df: pd.DataFrame, k: int = 14, smooth: int = 3) -> pd.DataFrame:
    """Slow stochastic: %K = SMA(smooth) of raw %K; %D = SMA(smooth) of %K. 50 when the range is flat."""
    lo = df["low"].rolling(k).min()
    hi = df["high"].rolling(k).max()
    rng = hi - lo
    raw = 100 * (df["close"] - lo) / rng.where(rng > 0)
    raw = raw.mask(rng == 0, 50.0)  # flat window: the close is mid-range by definition
    pk = raw.rolling(smooth).mean()
    return pd.DataFrame({"stoch_k": pk, "stoch_d": pk.rolling(smooth).mean()})


def obv(df: pd.DataFrame) -> pd.Series:
    """On-balance volume: cumulative volume signed by the close-to-close direction."""
    sign = np.sign(df["close"].diff()).fillna(0.0)
    return (sign * df["volume"]).cumsum()


def bollinger_width_pct_rank(close: pd.Series, window: int = 20, lookback: int = 120) -> float:
    """Where today's Bollinger band width sits in its last ``lookback`` values (0 = narrowest, 1 = widest)."""
    mid = close.rolling(window).mean()
    width = (4 * close.rolling(window).std(ddof=0) / mid).dropna().tail(lookback)
    if len(width) < 20:
        return float("nan")
    return float((width < width.iloc[-1]).mean())


def add_technicals(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d = d.join(adx(d)).join(stochastic(d))
    d["obv"] = obv(d)
    d["roc10"] = d["close"].pct_change(10)
    return d


# --------------------------------------------------------------------------- #
# Levels
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Level:
    price: float
    kind: str  # "support" | "resistance"
    touches: int
    last_touch: pd.Timestamp


def cluster_levels(pivots: list, close: float, last_date, tolerance: float = 0.015, min_touches: int = 2) -> list[Level]:
    """Group pivot prices within ``tolerance`` of each other into horizontal levels.

    ``pivots`` items need ``price`` and ``date``. Levels below the close are support; above, resistance.
    """
    pts = sorted(pivots, key=lambda p: p.price)
    clusters: list[list] = []
    for p in pts:
        if clusters and abs(p.price - np.mean([q.price for q in clusters[-1]])) / p.price <= tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    out = []
    for cl in clusters:
        if len(cl) >= min_touches:
            price = float(np.mean([q.price for q in cl]))
            out.append(Level(price, "support" if price < close else "resistance", len(cl), max(q.date for q in cl)))
    return sorted(out, key=lambda lv: abs(lv.price - close))


def fibonacci(df: pd.DataFrame, lookback: int = 120) -> dict | None:
    """Retracement levels of the dominant swing in the last ``lookback`` bars (uses only those bars)."""
    w = df.tail(lookback)
    if len(w) < 20:
        return None
    hi_i, lo_i = w["high"].idxmax(), w["low"].idxmin()
    hi, lo = float(w.loc[hi_i, "high"]), float(w.loc[lo_i, "low"])
    if hi <= lo:
        return None
    up = lo_i < hi_i  # the swing ran low → high, so retracements are measured down from the high
    levels = {f"{r * 100:.1f}%": (hi - r * (hi - lo)) if up else (lo + r * (hi - lo)) for r in FIB_RATIOS}
    return {
        "direction": "up-swing" if up else "down-swing",
        "swing_low": lo,
        "swing_high": hi,
        "low_date": w.loc[lo_i, "date"],
        "high_date": w.loc[hi_i, "date"],
        "levels": levels,
    }


# --------------------------------------------------------------------------- #
# Plain-English technical summary
# --------------------------------------------------------------------------- #
def technical_summary(d: pd.DataFrame) -> list[dict]:
    """Rows of {area, reading, detail} describing the latest bar. Descriptive only — no recommendation."""
    t = add_technicals(d) if "adx" not in d.columns else d
    last = t.iloc[-1]
    rows = []

    a = last.get("adx")
    if pd.notna(a):
        strength = "very strong" if a >= 40 else "strong" if a >= 25 else "weak" if a >= 20 else "no clear"
        direction = "upward" if last.plus_di > last.minus_di else "downward"
        rows.append(
            {
                "Area": "Trend strength",
                "Reading": f"ADX {a:.1f}: {strength} trend"
                + ("" if strength == "no clear" else f", {direction} (+DI {last.plus_di:.1f} vs −DI {last.minus_di:.1f})"),
                "How to read": "ADX measures strength, not direction. Above 25 = trending; below 20 = range-bound.",
            }
        )
    k, dd = last.get("stoch_k"), last.get("stoch_d")
    if pd.notna(k) and pd.notna(dd):
        zone = "overbought zone (>80)" if k > 80 else "oversold zone (<20)" if k < 20 else "mid-range"
        cross = "%K above %D" if k > dd else "%K below %D"
        rows.append(
            {
                "Area": "Stochastic (14,3,3)",
                "Reading": f"%K {k:.1f}, %D {dd:.1f}: {zone}, {cross}",
                "How to read": "Where the close sits in its 14-bar range. Extremes can persist in strong trends.",
            }
        )
    if len(t) > 21:
        obv_chg = t["obv"].iloc[-1] - t["obv"].iloc[-21]
        px_chg = t["close"].iloc[-1] / t["close"].iloc[-21] - 1
        agree = (obv_chg > 0) == (px_chg > 0)
        rows.append(
            {
                "Area": "Volume flow (OBV)",
                "Reading": f"OBV {'rising' if obv_chg > 0 else 'falling'} over 20 bars while price {'rose' if px_chg > 0 else 'fell'} {px_chg:+.1%}"
                + ("" if agree else " (disagreement)"),
                "How to read": "Volume confirming the price move is a stronger reading than volume disagreeing with it.",
            }
        )
    roc = last.get("roc10")
    if pd.notna(roc):
        rows.append({"Area": "Rate of change (10)", "Reading": f"{roc:+.2%} over 10 bars", "How to read": "Raw momentum."})
    rank = bollinger_width_pct_rank(t["close"])
    if rank == rank:
        squeeze = "squeeze (narrowest 20%)" if rank <= 0.2 else "expanded (widest 20%)" if rank >= 0.8 else "normal"
        rows.append(
            {
                "Area": "Volatility regime",
                "Reading": f"Bollinger width at {rank:.0%} of its 120-bar range: {squeeze}",
                "How to read": "Squeezes often precede bigger moves, in either direction.",
            }
        )
    return rows
