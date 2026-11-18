"""Market-data access via the optional, unofficial ``yfinance`` package."""

from __future__ import annotations

import logging
import re
from pathlib import PurePath

import pandas as pd

from .engine import normalize_ohlcv

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=]{0,14}$")
# yfinance only serves limited history for intraday bars.
INTRADAY_MAX = {"1h": {"1mo", "3mo", "6mo", "1y", "2y"}}


class DataError(RuntimeError):
    pass


def clean_ticker(t: str) -> str:
    t = (t or "").strip().upper()
    if not TICKER_RE.fullmatch(t):
        raise DataError(f"'{t}' is not a valid ticker symbol (e.g. NVDA, BHP.AX, ^GSPC).")
    return t


def ticker_from_filename(name: str) -> str | None:
    """Guess a ticker from e.g. ``bhp.ax_2024.csv`` → ``BHP.AX``; None if it doesn't look like one."""
    stem = PurePath(name).stem.split("_")[0].strip().upper()
    return stem if TICKER_RE.fullmatch(stem) else None


def _yf():
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - depends on environment
        raise DataError("Live data requires yfinance (pip install -r requirements.txt).") from e
    return yf


def fetch_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    ticker = clean_ticker(ticker)
    if interval in INTRADAY_MAX and period not in INTRADAY_MAX[interval]:
        raise DataError(f"{interval} bars are only available for up to 2 years of history.")
    try:
        raw = _yf().download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as e:  # network / provider errors
        raise DataError(f"Data provider error for {ticker}: {e}") from e
    if raw is None or raw.empty:
        raise DataError(f"No data returned for {ticker}. Check the symbol, interval and provider availability.")
    raw = raw.reset_index()
    return normalize_ohlcv(raw)


def fetch_history_since(ticker: str, start) -> pd.DataFrame:
    ticker = clean_ticker(ticker)
    start = pd.Timestamp(start).tz_localize(None) if pd.Timestamp(start).tzinfo else pd.Timestamp(start)
    try:
        raw = _yf().download(
            ticker, start=start.date().isoformat(), interval="1d", auto_adjust=True, progress=False, threads=False
        )
    except Exception as e:
        raise DataError(f"Data provider error for {ticker}: {e}") from e
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "close"])
    raw = raw.reset_index()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]) for c in raw.columns]
    raw.columns = [str(c).lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw.get("date", raw.get("datetime")), utc=True)
    return raw[["date", "close"]].dropna()


def latest_prices(tickers: list[str]) -> dict[str, float]:
    """Last available close per ticker; tickers that fail are omitted (never guessed)."""
    out: dict[str, float] = {}
    for t in sorted(set(tickers)):
        try:
            h = fetch_history(t, period="3mo", interval="1d")  # ≥30 bars needed by validation
            out[t] = float(h["close"].iloc[-1])
        except Exception as e:  # one bad symbol must not break the whole refresh
            log.warning("price refresh failed for %s: %s", t, e)
    return out
