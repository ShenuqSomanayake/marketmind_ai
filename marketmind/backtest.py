"""EMA-crossover + RSI backtest with buy-and-hold benchmark and out-of-sample split.

Signals are computed on bar *t*'s close and the position is applied from bar *t+1*,
so no future information is used. Costs (fee + slippage) are charged on every
change in position.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import periods_per_year, rsi


@dataclass(frozen=True)
class StrategyParams:
    fast: int = 20
    slow: int = 50
    rsi_period: int = 14
    rsi_min: float = 50.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    def validate(self) -> None:
        if not 1 < self.fast < self.slow:
            raise ValueError("Fast EMA must be greater than 1 and shorter than the slow EMA.")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("Costs cannot be negative.")


def metrics(returns: pd.Series, ppy: float, position: pd.Series | None = None) -> dict:
    """Performance statistics for a per-bar simple-return series."""
    returns = pd.Series(returns).fillna(0.0)
    n = len(returns)
    if n == 0:
        return {k: float("nan") for k in ("total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "exposure")}
    equity = (1 + returns).cumprod()
    total = float(equity.iloc[-1] - 1)
    years = n / ppy
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else float("nan")
    sd = returns.std()
    downside = returns[returns < 0].std()
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": float(sd * np.sqrt(ppy)) if n > 1 else float("nan"),
        "sharpe": float(returns.mean() / sd * np.sqrt(ppy)) if sd and sd > 0 else 0.0,
        "sortino": float(returns.mean() / downside * np.sqrt(ppy)) if downside and downside > 0 else 0.0,
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "exposure": float(position.mean()) if position is not None and len(position) else 1.0,
    }


def _trades(d: pd.DataFrame) -> pd.DataFrame:
    """Round-trip trade list using next-bar-close execution prices (matches the return model)."""
    pos = d["position"].to_numpy()
    rows, entry_i = [], None
    for i in range(len(pos)):
        prev = pos[i - 1] if i else 0
        if pos[i] == 1 and prev == 0:
            entry_i = i - 1 if i else 0  # position earns from bar i, so entry fill is close of bar i-1
        elif pos[i] == 0 and prev == 1 and entry_i is not None:
            exit_i = i - 1
            rows.append((entry_i, exit_i, False))
            entry_i = None
    if entry_i is not None:
        rows.append((entry_i, len(pos) - 1, True))
    out = []
    for a, b, is_open in rows:
        gross = d["close"].iloc[b] / d["close"].iloc[a] - 1
        out.append(
            {
                "entry_date": d["date"].iloc[a],
                "exit_date": d["date"].iloc[b],
                "entry_price": float(d["close"].iloc[a]),
                "exit_price": float(d["close"].iloc[b]),
                "bars_held": int(b - a),
                "gross_return": float(gross),
                "open": is_open,
            }
        )
    return pd.DataFrame(
        out, columns=["entry_date", "exit_date", "entry_price", "exit_price", "bars_held", "gross_return", "open"]
    )


def run_backtest(df: pd.DataFrame, params: StrategyParams | None = None, oos_fraction: float = 0.3) -> dict:
    """Run the strategy and benchmark; report full, in-sample and out-of-sample metrics."""
    p = params or StrategyParams()
    p.validate()
    if not 0 <= oos_fraction < 0.9:
        raise ValueError("Out-of-sample fraction must be between 0 and 0.9.")
    d = df[["date", "open", "high", "low", "close", "volume"]].copy().reset_index(drop=True)
    if len(d) < p.slow + 10:
        raise ValueError(f"Need at least {p.slow + 10} bars for a {p.slow}-period slow EMA.")

    fast = d["close"].ewm(span=p.fast, adjust=False).mean()
    slow = d["close"].ewm(span=p.slow, adjust=False).mean()
    r = rsi(d["close"], p.rsi_period)
    warm = d.index >= p.slow  # ignore crossovers while the slow EMA is still seeding
    enter = (fast > slow) & (fast.shift(1) <= slow.shift(1)) & (r > p.rsi_min) & warm
    leave = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    held, state = [], 0
    for e, x in zip(enter.fillna(False), leave.fillna(False), strict=True):
        if not state and e:
            state = 1
        elif state and x:
            state = 0
        held.append(state)
    d["signal"] = held
    d["position"] = d["signal"].shift(1).fillna(0).astype(int)
    cost = (p.fee_bps + p.slippage_bps) / 10_000
    d["asset_return"] = d["close"].pct_change().fillna(0.0)
    d["turnover"] = d["position"].diff().abs().fillna(d["position"].iloc[0])
    d["strategy_return"] = d["position"] * d["asset_return"] - d["turnover"] * cost
    d["benchmark_return"] = d["asset_return"]
    d["strategy_equity"] = (1 + d["strategy_return"]).cumprod()
    d["benchmark_equity"] = (1 + d["benchmark_return"]).cumprod()

    ppy = periods_per_year(d["date"])
    split = int(len(d) * (1 - oos_fraction)) if oos_fraction > 0 else len(d)
    segments = {"Full period": slice(0, len(d))}
    if oos_fraction > 0:
        segments["In-sample"] = slice(0, split)
        segments["Out-of-sample"] = slice(split, len(d))

    trades = _trades(d)
    closed = trades[~trades["open"]] if len(trades) else trades
    table = []
    for name, sl in segments.items():
        seg = d.iloc[sl]
        s = metrics(seg["strategy_return"], ppy, seg["position"])
        b = metrics(seg["benchmark_return"], ppy)
        seg_trades = (
            trades[(trades["entry_date"] >= seg["date"].iloc[0]) & (trades["entry_date"] <= seg["date"].iloc[-1])]
            if len(trades)
            else trades
        )
        table.append({"segment": name, "series": "Strategy", **s, "trades": int(len(seg_trades))})
        table.append({"segment": name, "series": "Buy & hold", **b, "trades": 1})

    return {
        "params": p,
        "series": d,
        "periods_per_year": ppy,
        "split_date": d["date"].iloc[split] if split < len(d) else None,
        "table": pd.DataFrame(table),
        "trades": trades,
        "win_rate": float((closed["gross_return"] > 0).mean()) if len(closed) else float("nan"),
        "full": metrics(d["strategy_return"], ppy, d["position"]),
        "benchmark": metrics(d["benchmark_return"], ppy),
    }
