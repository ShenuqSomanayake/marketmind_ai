"""Holdings valuation and a cash- and position-aware paper-trading ledger."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

PAPER_CURRENCIES = ("AUD", "USD", "LKR")
DEFAULT_PAPER_CASH = 100_000.0


def value_holdings(holdings: pd.DataFrame, prices: dict[str, float]) -> pd.DataFrame:
    """Add market value, unrealised P&L and weights. Missing prices stay NaN (never guessed)."""
    h = holdings.copy()
    h["cost_basis"] = h["quantity"] * h["avg_cost"]
    h["last_price"] = h["ticker"].map(prices).astype(float)
    h["market_value"] = h["quantity"] * h["last_price"]
    h["unrealised_pnl"] = h["market_value"] - h["cost_basis"]
    h["unrealised_pct"] = h["unrealised_pnl"] / h["cost_basis"]
    # Weights are per currency; mixing currencies without FX would be wrong.
    h["weight"] = h["market_value"] / h.groupby("currency")["market_value"].transform("sum")
    return h


class OrderRejected(ValueError):
    pass


@dataclass
class Position:
    quantity: float = 0.0
    avg_cost: float = 0.0
    realised_pnl: float = 0.0


@dataclass
class Account:
    currency: str
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    fees_paid: float = 0.0


EPS = 1e-9


def apply_trade(acct: Account, ticker: str, side: str, qty: float, price: float, fee: float) -> None:
    """Mutate ``acct`` for one fill, or raise ``OrderRejected``. Average-cost method; long-only."""
    if qty <= 0 or price <= 0 or fee < 0:
        raise OrderRejected("Quantity and price must be positive; fee cannot be negative.")
    pos = acct.positions.setdefault(ticker, Position())
    if side == "BUY":
        cost = qty * price + fee
        if cost > acct.cash + EPS:
            raise OrderRejected(f"Insufficient {acct.currency} cash: need {cost:,.2f}, have {acct.cash:,.2f}.")
        new_qty = pos.quantity + qty
        pos.avg_cost = (pos.quantity * pos.avg_cost + qty * price + fee) / new_qty
        pos.quantity = new_qty
        acct.cash -= cost
    elif side == "SELL":
        if qty > pos.quantity + EPS:
            raise OrderRejected(f"Cannot sell {qty:g} {ticker}: only {pos.quantity:g} held (short selling is disabled).")
        proceeds = qty * price - fee
        pos.realised_pnl += proceeds - qty * pos.avg_cost
        pos.quantity -= qty
        if pos.quantity < EPS:
            pos.quantity, pos.avg_cost = 0.0, 0.0
        acct.cash += proceeds
    else:
        raise OrderRejected("Side must be BUY or SELL.")
    acct.fees_paid += fee


def replay(starting_cash: dict[str, float], trades: list[tuple]) -> dict[str, Account]:
    """Rebuild accounts from ``(ticker, side, qty, price, fee, currency)`` rows in time order."""
    accts = {c: Account(c, float(v)) for c, v in starting_cash.items()}
    for ticker, side, qty, price, fee, ccy in trades:
        apply_trade(accts.setdefault(ccy, Account(ccy, 0.0)), ticker, side, qty, price, fee)
    return accts


def positions_frame(accts: dict[str, Account], prices: dict[str, float] | None = None) -> pd.DataFrame:
    rows = []
    for a in accts.values():
        for t, p in a.positions.items():
            if p.quantity > EPS or abs(p.realised_pnl) > EPS:
                last = (prices or {}).get(t)
                rows.append(
                    {
                        "Ticker": t,
                        "Currency": a.currency,
                        "Quantity": p.quantity,
                        "Avg cost": p.avg_cost,
                        "Last price": last,
                        "Unrealised P&L": (last - p.avg_cost) * p.quantity if last is not None else None,
                        "Realised P&L": p.realised_pnl,
                    }
                )
    return pd.DataFrame(rows)
