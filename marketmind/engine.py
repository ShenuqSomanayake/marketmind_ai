"""Deterministic OHLCV normalisation, indicators and technical assessment.

Everything in this module is a pure function of its inputs: no I/O, no clock,
no randomness. That makes every number shown in the app reproducible and testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REQUIRED = ("open", "high", "low", "close", "volume")
MIN_ROWS = 30
_ALIASES = {
    "adjclose": "adj_close",
    "adj_close": "adj_close",
    "datetime": "date",
    "timestamp": "date",
    "time": "date",
    "vol": "volume",
}


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a clean, validated, date-sorted OHLCV frame with lower-case columns.

    Raises ``ValueError`` with a user-readable message on any data problem.
    """
    if frame is None or frame.empty:
        raise ValueError("The dataset is empty.")
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    df.columns = [_ALIASES.get(k, k) for k in (str(c).strip().lower().replace(" ", "_") for c in df.columns)]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]

    if "date" not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex):
            df.insert(0, "date", df.index)
        else:
            raise ValueError("Could not find a Date/Datetime column.")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing) + ". Required: Date, Open, High, Low, Close, Volume.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    for c in REQUIRED:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    df = df.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0).clip(lower=0)

    if len(df) < MIN_ROWS:
        raise ValueError(f"Only {len(df)} valid rows found. At least {MIN_ROWS} are required; 200+ is better.")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be positive.")
    hi_bad = df["high"] < df[["open", "low", "close"]].max(axis=1)
    lo_bad = df["low"] > df[["open", "high", "close"]].min(axis=1)
    if (hi_bad | lo_bad).any():
        first = df.loc[hi_bad | lo_bad, "date"].iloc[0].date()
        raise ValueError(f"{int((hi_bad | lo_bad).sum())} OHLC rows have inconsistent High/Low values (first: {first}).")
    keep = ["date", *REQUIRED] + (["adj_close"] if "adj_close" in df.columns else [])
    return df[keep]


# --------------------------------------------------------------------------- #
# Frequency handling
# --------------------------------------------------------------------------- #
def periods_per_year(dates: pd.Series) -> float:
    """Infer the annualisation factor from bar spacing.

    Daily → 252, weekly → 52, monthly → 12, intraday → 252 × median bars per day.
    """
    dates = pd.to_datetime(pd.Series(dates)).dropna().sort_values()
    if len(dates) < 3:
        return 252.0
    gap_days = dates.diff().dropna().dt.total_seconds().median() / 86400
    if gap_days < 0.9:  # intraday
        per_day = dates.dt.date.value_counts().median()
        return float(252 * max(per_day, 1))
    if gap_days < 4:
        return 252.0
    if gap_days < 20:
        return 52.0
    if gap_days < 60:
        return 12.0
    return 4.0


def period_return(close: pd.Series, bars: int) -> float:
    """Simple return over the last ``bars`` bars (e.g. 0.05 == +5%). NaN if not enough data."""
    close = pd.Series(close).dropna()
    if len(close) <= bars:
        return float("nan")
    return float(close.iloc[-1] / close.iloc[-1 - bars] - 1)


def annualised_volatility(close: pd.Series, ppy: float, window: int | None = None) -> pd.Series | float:
    rets = pd.Series(close).pct_change()
    if window is None:
        return float(rets.std() * np.sqrt(ppy))
    return rets.rolling(window).std() * np.sqrt(ppy)


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #
def wilder_smooth(x: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: seed with the simple mean of the first ``period`` values, then
    ``avg_t = (avg_{t-1} * (period - 1) + x_t) / period``. Leading NaNs are skipped."""
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    valid = np.flatnonzero(~np.isnan(vals))
    if len(valid) < period:
        return pd.Series(out, index=x.index)
    start = valid[0]
    seed_end = start + period - 1
    out[seed_end] = vals[start : seed_end + 1].mean()
    for i in range(seed_end + 1, len(vals)):
        out[i] = (out[i - 1] * (period - 1) + vals[i]) / period
    return pd.Series(out, index=x.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI (textbook SMA-seeded). NaN during warm-up; 50 for a perfectly flat window."""
    delta = close.diff()
    avg_gain = wilder_smooth(delta.clip(lower=0), period)
    avg_loss = wilder_smooth(-delta.clip(upper=0), period)
    rs = avg_gain / avg_loss.where(avg_loss > 0)
    out = 100 - 100 / (1 + rs)
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out.where(avg_gain.notna())


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, low, v = d["close"], d["high"], d["low"], d["volume"]
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    d["ema50"] = c.ewm(span=50, adjust=False).mean()
    d["sma200"] = c.rolling(200, min_periods=200).mean()
    d["rsi14"] = rsi(c, 14)
    d["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    d["bb_mid"], d["bb_upper"], d["bb_lower"] = mid, mid + 2 * sd, mid - 2 * sd
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1)
    d["atr14"] = wilder_smooth(tr.where(c.shift().notna()), 14)  # Wilder ATR (true range needs a prior close)
    d["volume_avg20"] = v.rolling(20).mean()
    d["return"] = c.pct_change()
    return d


def detect_candles(df: pd.DataFrame) -> list[str]:
    """Heuristic single/two-bar candle shapes on the latest bar."""
    if len(df) < 2:
        return []
    last, prev = df.iloc[-1], df.iloc[-2]
    body = abs(last.close - last.open)
    rng = max(last.high - last.low, 1e-12)
    upper = last.high - max(last.open, last.close)
    lower = min(last.open, last.close) - last.low
    b = max(body, 1e-12)
    out: list[str] = []
    if body / rng < 0.10:
        out.append("Doji-like candle")
    if lower > 2 * b and upper < b:
        out.append("Hammer-like candle")
    if upper > 2 * b and lower < b:
        out.append("Shooting-star-like candle")
    if last.close > last.open and prev.close < prev.open and last.close >= prev.open and last.open <= prev.close:
        out.append("Bullish engulfing")
    if last.close < last.open and prev.close > prev.open and last.open >= prev.close and last.close <= prev.open:
        out.append("Bearish engulfing")
    return out


# --------------------------------------------------------------------------- #
# Technical assessment
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    name: str
    points: int
    met: bool | None  # None = not evaluable (insufficient history)
    detail: str

    @property
    def contribution(self) -> int:
        if self.met is None:
            return 0
        return self.points if self.met else -self.points


def label_for(score: int) -> str:
    if score >= 70:
        return "Bullish setup"
    if score >= 56:
        return "Leaning bullish"
    if score >= 45:
        return "Mixed / wait for confirmation"
    if score >= 30:
        return "Leaning bearish"
    return "Bearish setup"


def analyse(df: pd.DataFrame) -> dict:
    """Score the latest bar with a transparent, additive rule set (base 50, clamped 0–100)."""
    d = add_indicators(df)
    last, prev = d.iloc[-1], d.iloc[-2]
    close = float(last.close)
    r = float(last.rsi14) if pd.notna(last.rsi14) else 50.0

    rules = [
        Rule("Close above EMA 20", 7, close > last.ema20, f"Close {close:,.2f} vs EMA20 {last.ema20:,.2f}"),
        Rule("EMA 20 above EMA 50", 9, bool(last.ema20 > last.ema50), f"EMA20 {last.ema20:,.2f} vs EMA50 {last.ema50:,.2f}"),
        Rule(
            "Close above SMA 200",
            10,
            None if pd.isna(last.sma200) else bool(close > last.sma200),
            "Needs 200 bars" if pd.isna(last.sma200) else f"SMA200 {last.sma200:,.2f}",
        ),
        Rule("RSI momentum", 8, None if 45 < r < 55 else r >= 55, f"RSI {r:.1f} (neutral band 45–55 scores 0)"),
        Rule(
            "MACD above signal", 8, bool(last.macd > last.macd_signal), f"MACD {last.macd:.3f} vs signal {last.macd_signal:.3f}"
        ),
        Rule(
            "MACD histogram rising",
            4,
            bool(last.macd_hist > prev.macd_hist),
            f"Hist {last.macd_hist:.3f} vs {prev.macd_hist:.3f}",
        ),
    ]
    vol_ratio = None
    if pd.notna(last.volume_avg20) and last.volume_avg20 > 0:
        vol_ratio = float(last.volume / last.volume_avg20)
        if vol_ratio >= 1.5 and last.close != last.open:
            rules.append(
                Rule("High-volume confirmation", 5, bool(last.close > last.open), f"Volume {vol_ratio:.1f}× 20-bar average")
            )

    score = int(max(0, min(100, 50 + sum(x.contribution for x in rules))))
    evidence = [f"{x.name}: {x.detail}." for x in rules if x.met is True]
    risks = [f"Not met — {x.name}: {x.detail}." for x in rules if x.met is False]
    if r < 30:
        risks.append("RSI is oversold; this is not a standalone buy signal and price can remain oversold.")
    if r > 70:
        risks.append("RSI is overbought; strong trends can remain overbought.")

    ppy = periods_per_year(d["date"])
    evaluable = [x for x in rules if x.met is not None]
    return {
        "data": d,
        "rules": rules,
        "score": score,
        "label": label_for(score),
        "rules_summary": f"{sum(x.met is True for x in evaluable)} of {len(evaluable)} trend & momentum rules met",
        "close": close,
        "as_of": d["date"].iloc[-1],
        "rsi": r,
        "macd": float(last.macd),
        "macd_signal": float(last.macd_signal),
        "macd_hist": float(last.macd_hist),
        "ema20": float(last.ema20),
        "ema50": float(last.ema50),
        "sma200": None if pd.isna(last.sma200) else float(last.sma200),
        "atr14": None if pd.isna(last.atr14) else float(last.atr14),
        "support20": float(d["low"].tail(20).min()),
        "resistance20": float(d["high"].tail(20).max()),
        "volume_ratio": vol_ratio,
        "return_20": period_return(d["close"], 20),
        "volatility_ann": annualised_volatility(d["close"], ppy),
        "periods_per_year": ppy,
        "evidence": evidence,
        "risks": risks,
        "patterns": detect_candles(d),
    }


def unusual_activity(df: pd.DataFrame) -> list[str]:
    """Threshold-based statistical flags on the latest bar."""
    d = df
    ppy = periods_per_year(d["date"])
    rets = d["close"].pct_change()
    vol = annualised_volatility(d["close"], ppy, window=20)
    avg = float(d["volume"].tail(20).mean())
    flags = []
    if avg > 0 and d["volume"].iloc[-1] / avg >= 2:
        flags.append(f"Volume is {d['volume'].iloc[-1] / avg:.1f}× its 20-bar average.")
    sd = rets.tail(61).iloc[:-1].std()  # exclude the bar being tested
    if pd.notna(sd) and sd > 0 and abs(rets.iloc[-1]) >= 2 * sd:
        flags.append(f"Latest return ({rets.iloc[-1]:+.2%}) is ≥2 standard deviations of the prior 60 bars.")
    if pd.notna(vol.iloc[-1]) and vol.iloc[-1] > vol.tail(60).median() * 1.5:
        flags.append("20-bar volatility is more than 1.5× its 60-bar median.")
    return flags
