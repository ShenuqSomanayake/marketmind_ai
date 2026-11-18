"""Input-based fundamental ratios. Negative profit, cash flow and equity are valid inputs."""

from __future__ import annotations


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def ratios(revenue: float, prior_revenue: float, net_profit: float, operating_cf: float, debt: float, equity: float) -> dict:
    out = {
        "revenue_growth": _div(revenue - prior_revenue, prior_revenue) if prior_revenue > 0 else None,
        "net_margin": _div(net_profit, revenue) if revenue > 0 else None,
        "debt_to_equity": _div(debt, equity) if equity > 0 else None,
        "cash_conversion": _div(operating_cf, net_profit) if net_profit > 0 else None,
    }
    flags = []
    if net_profit < 0:
        flags.append("Loss-making in the latest period.")
    if operating_cf < 0:
        flags.append("Negative operating cash flow: the business is consuming cash; check funding runway.")
    if equity <= 0:
        flags.append("Shareholders' equity is zero or negative (liabilities exceed assets); debt/equity is not meaningful.")
    elif out["debt_to_equity"] is not None and out["debt_to_equity"] > 1:
        flags.append("Debt exceeds shareholders' equity. Review sector norms, maturity profile and interest coverage.")
    if out["cash_conversion"] is not None and out["cash_conversion"] < 0.8:
        flags.append("Operating cash flow is below 80% of net profit; earnings quality deserves a closer look.")
    if out["revenue_growth"] is not None and out["revenue_growth"] < 0:
        flags.append("Revenue declined versus the prior comparable period.")
    out["flags"] = flags
    return out
