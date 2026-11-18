"""Behavioural insights from the user's own records: the "report card".

Everything here describes the user's past decisions using their own data. It does
not recommend any financial product. Every finding carries its sample size, and
nothing is reported for groups smaller than ``MIN_N``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

MIN_N = 5
BIG_RISE = 0.10  # 20-bar return above +10% counts as "after a big rise"
NEAR_TRIGGER = 0.05  # within 5% of an invalidation price


@dataclass(frozen=True)
class Finding:
    title: str
    detail: str
    n: int
    tone: str  # "good" | "warn" | "info"


def _rate(s: pd.Series) -> float:
    return float((s == "Correct").mean()) if len(s) else float("nan")


# --------------------------------------------------------------------------- #
# Prediction report card
# --------------------------------------------------------------------------- #
def prediction_report(df: pd.DataFrame) -> dict:
    """``df`` columns: view, outcome, realised_return, threshold_pct, score, ret20_at_entry, horizon_bars."""
    out: dict = {"n": 0, "findings": [], "by_view": pd.DataFrame(), "by_pattern": pd.DataFrame(), "hit_rate": None}
    if df.empty:
        return out
    scored = df[df["outcome"].isin(["Correct", "Incorrect"])].copy()
    n = out["n"] = len(scored)
    if n == 0:
        return out
    out["hit_rate"] = _rate(scored["outcome"])
    out["by_view"] = (
        scored.groupby("view")
        .agg(calls=("outcome", "size"), hit_rate=("outcome", _rate), avg_move=("realised_return", "mean"))
        .reset_index()
    )
    if n < MIN_N:
        out["findings"].append(
            Finding("Not enough history yet", f"Patterns appear after {MIN_N}+ scored predictions.", n, "info")
        )
        return out

    f: list[Finding] = []
    thr = scored["threshold_pct"] / 100
    r = scored["realised_return"]

    # 1. Versus a naive "always bullish" baseline over the same periods and thresholds.
    baseline = float((r > thr).mean())
    you = out["hit_rate"]
    if you > baseline + 0.05:
        f.append(
            Finding(
                "You beat the lazy baseline",
                f"Your hit rate {you:.0%} vs {baseline:.0%} if you had just said 'Bullish' every time.",
                n,
                "good",
            )
        )
    elif you < baseline - 0.05:
        f.append(
            Finding(
                "A lazy baseline beat you",
                f"Saying 'Bullish' every time would have scored {baseline:.0%}; you scored {you:.0%}.",
                n,
                "warn",
            )
        )
    else:
        f.append(Finding("Level with the lazy baseline", f"You {you:.0%} vs always-Bullish {baseline:.0%}.", n, "info"))

    # 2. Optimism / pessimism: how often you call "up" vs how often it went up.
    bull_share = float((scored["view"] == "Bullish").mean())
    up_share = float((r > thr).mean())
    if bull_share - up_share > 0.15:
        f.append(
            Finding(
                "Optimism bias",
                f"{bull_share:.0%} of your calls were Bullish, but prices cleared your threshold only {up_share:.0%} of the time.",
                n,
                "warn",
            )
        )
    elif up_share - bull_share > 0.15:
        f.append(
            Finding(
                "Pessimism bias",
                f"Only {bull_share:.0%} of your calls were Bullish, yet prices rose past your threshold {up_share:.0%} of the time.",
                n,
                "warn",
            )
        )

    # 3. Bullish calls after a big run-up (chasing).
    bull = scored[(scored["view"] == "Bullish") & scored["ret20_at_entry"].notna()]
    hot, calm = bull[bull["ret20_at_entry"] > BIG_RISE], bull[bull["ret20_at_entry"] <= BIG_RISE]
    if len(hot) >= MIN_N and len(calm) >= MIN_N:
        h, c = _rate(hot["outcome"]), _rate(calm["outcome"])
        if h + 0.10 < c:
            f.append(
                Finding(
                    "Chasing after big rises",
                    f"Bullish calls after a 20-bar rise over {BIG_RISE:.0%} hit {h:.0%}, vs {c:.0%} otherwise.",
                    len(hot) + len(calm),
                    "warn",
                )
            )
        elif h > c + 0.10:
            f.append(
                Finding(
                    "Momentum works for you",
                    f"Bullish calls after a {BIG_RISE:.0%}+ run hit {h:.0%}, vs {c:.0%} otherwise.",
                    len(hot) + len(calm),
                    "good",
                )
            )

    # 4. Agreeing vs disagreeing with MarketMind's technical score.
    def score_dir(s: int) -> str:
        return "Bullish" if s >= 56 else "Bearish" if s <= 44 else "Neutral"

    agree = scored["view"] == scored["score"].map(score_dir)
    a, d = scored[agree], scored[~agree]
    if len(a) >= MIN_N and len(d) >= MIN_N:
        ra, rd = _rate(a["outcome"]), _rate(d["outcome"])
        if abs(ra - rd) >= 0.10:
            better = "with" if ra > rd else "against"
            f.append(
                Finding(
                    f"You do better going {better} the technical score",
                    f"Agreeing with the score: {ra:.0%} ({len(a)} calls). Disagreeing: {rd:.0%} ({len(d)} calls).",
                    len(a) + len(d),
                    "info",
                )
            )

    # 5. Short vs long horizons.
    short, long_ = scored[scored["horizon_bars"] <= 10], scored[scored["horizon_bars"] > 10]
    if len(short) >= MIN_N and len(long_) >= MIN_N:
        rs, rl = _rate(short["outcome"]), _rate(long_["outcome"])
        if abs(rs - rl) >= 0.10:
            f.append(
                Finding(
                    "Your best timeframe",
                    f"Short calls (≤10 days): {rs:.0%}. Longer calls: {rl:.0%}.",
                    len(short) + len(long_),
                    "good" if max(rs, rl) > 0.5 else "info",
                )
            )
    f += _pattern_findings(scored, out)
    out["findings"] = f
    return out


def _pattern_findings(scored: pd.DataFrame, out: dict) -> list[Finding]:
    """How the user's calls went on charts that contained chart patterns (needs the ``patterns_at_entry`` column)."""
    from .patterns import decode_tags

    if "patterns_at_entry" not in scored.columns:
        return []
    found: list[Finding] = []
    rows, align = [], []
    view_dir = {"Bullish": 1, "Bearish": -1, "Neutral": 0}
    for r in scored.itertuples(index=False):
        tags = decode_tags(r.patterns_at_entry)
        for name in sorted({t[0] for t in tags}):
            rows.append({"pattern": name, "outcome": r.outcome})
        dirs = {t[1] for t in tags if t[2] == "confirmed" and t[1] != 0}
        if len(dirs) == 1:  # one unambiguous confirmed signal on the chart
            align.append({"with": view_dir[r.view] == dirs.pop(), "outcome": r.outcome})
    if rows:
        bp = pd.DataFrame(rows).groupby("pattern").agg(calls=("outcome", "size"), hit_rate=("outcome", _rate)).reset_index()
        out["by_pattern"] = bp.sort_values("calls", ascending=False)
        enough = bp[bp["calls"] >= MIN_N]
        if len(enough) >= 2:
            best, worst = enough.loc[enough.hit_rate.idxmax()], enough.loc[enough.hit_rate.idxmin()]
            if best.hit_rate - worst.hit_rate >= 0.15:
                found.append(
                    Finding(
                        "Patterns you read best and worst",
                        f"On charts with a {best.pattern} you hit {best.hit_rate:.0%} ({best.calls} calls); "
                        f"with a {worst.pattern}, {worst.hit_rate:.0%} ({worst.calls} calls).",
                        int(best.calls + worst.calls),
                        "info",
                    )
                )
    if align:
        a = pd.DataFrame(align)
        w, g = a[a["with"]], a[~a["with"]]
        if len(w) >= MIN_N and len(g) >= MIN_N:
            rw, rg = _rate(w["outcome"]), _rate(g["outcome"])
            if abs(rw - rg) >= 0.10:
                better = "with" if rw > rg else "against"
                found.append(
                    Finding(
                        f"You do better going {better} confirmed patterns",
                        f"Calls in the pattern's direction: {rw:.0%} ({len(w)}). Against it: {rg:.0%} ({len(g)}).",
                        len(w) + len(g),
                        "info",
                    )
                )
    return found


# --------------------------------------------------------------------------- #
# Trading habits (paper trades)
# --------------------------------------------------------------------------- #
def closed_sells(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per SELL with return vs average cost and days since the position was opened.

    ``trades`` columns: created_at, ticker, side, quantity, price, fee, currency (time-ordered)."""
    state: dict[tuple[str, str], dict] = {}
    rows = []
    for t in trades.sort_values("created_at", kind="stable").itertuples(index=False):
        key = (t.ticker, t.currency)
        s = state.setdefault(key, {"qty": 0.0, "avg": 0.0, "opened": None})
        ts = pd.Timestamp(t.created_at)
        if t.side == "BUY":
            if s["qty"] <= 1e-9:
                s["opened"] = ts
            s["avg"] = (s["qty"] * s["avg"] + t.quantity * t.price + t.fee) / (s["qty"] + t.quantity)
            s["qty"] += t.quantity
        elif s["qty"] > 1e-9:
            ret = (t.quantity * t.price - t.fee) / (t.quantity * s["avg"]) - 1
            rows.append({"ticker": t.ticker, "return": ret, "days_held": (ts - s["opened"]).total_seconds() / 86400})
            s["qty"] -= t.quantity
            if s["qty"] <= 1e-9:
                s["qty"], s["avg"], s["opened"] = 0.0, 0.0, None
    return pd.DataFrame(rows, columns=["ticker", "return", "days_held"])


def trading_report(trades: pd.DataFrame) -> dict:
    sells = closed_sells(trades) if len(trades) else pd.DataFrame(columns=["ticker", "return", "days_held"])
    n = len(sells)
    out: dict = {"n": n, "findings": [], "sells": sells}
    if n < MIN_N:
        out["findings"].append(Finding("Not enough closed trades yet", f"Habits appear after {MIN_N}+ sells.", n, "info"))
        return out
    wins, losses = sells[sells["return"] > 0], sells[sells["return"] <= 0]
    f = [Finding("Win rate", f"{len(wins) / n:.0%} of your sells were profitable.", n, "info")]
    if len(wins) and len(losses):
        aw, al = wins["return"].mean(), losses["return"].mean()
        tone = "good" if aw >= abs(al) else "warn"
        f.append(Finding("Size of wins vs losses", f"Average win {aw:+.1%}, average loss {al:+.1%}.", n, tone))
        hw, hl = wins["days_held"].median(), losses["days_held"].median()
        if hl > 1.5 * hw and hl - hw >= 1:
            f.append(
                Finding(
                    "Holding losers longer than winners",
                    f"You held losing positions for a median {hl:.0f} days and winners {hw:.0f} days. "
                    "This pattern is known as the disposition effect.",
                    n,
                    "warn",
                )
            )
        elif hw > 1.5 * hl and hw - hl >= 1:
            f.append(Finding("Letting winners run", f"Median hold: winners {hw:.0f} days, losers {hl:.0f} days.", n, "good"))
    out["findings"] = f
    return out


# --------------------------------------------------------------------------- #
# Thesis checks
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ThesisStatus:
    status: str  # "Triggered" | "Near trigger" | "Review due" | "On track" | "No trigger set"
    detail: str
    tone: str


def check_thesis(
    close: float | None,
    stop_below: float | None,
    stop_above: float | None,
    review_date: str | None,
    today: date | None = None,
) -> ThesisStatus:
    """Compare the latest close with the user's own invalidation prices and review date."""
    today = today or date.today()
    due = bool(review_date) and str(review_date) <= today.isoformat()
    if close is None:
        return ThesisStatus("No price", "Latest price unavailable.", "info")
    if stop_below and close <= stop_below:
        return ThesisStatus("Triggered", f"Close {close:,.2f} is at or below your invalidation price {stop_below:,.2f}.", "warn")
    if stop_above and close >= stop_above:
        return ThesisStatus("Triggered", f"Close {close:,.2f} is at or above your invalidation price {stop_above:,.2f}.", "warn")
    near = []
    if stop_below and (close - stop_below) / close <= NEAR_TRIGGER:
        near.append(f"{(close - stop_below) / close:.1%} above your {stop_below:,.2f} level")
    if stop_above and (stop_above - close) / close <= NEAR_TRIGGER:
        near.append(f"{(stop_above - close) / close:.1%} below your {stop_above:,.2f} level")
    if near:
        return ThesisStatus("Near trigger", f"Close {close:,.2f} is " + " and ".join(near) + ".", "warn")
    if due:
        return ThesisStatus("Review due", f"You planned to review this by {review_date}.", "info")
    if not stop_below and not stop_above:
        return ThesisStatus("No trigger set", "Add an invalidation price to get automatic alerts.", "info")
    gaps = []
    if stop_below:
        gaps.append(f"{(close - stop_below) / close:.1%} above {stop_below:,.2f}")
    if stop_above:
        gaps.append(f"{(stop_above - close) / close:.1%} below {stop_above:,.2f}")
    return ThesisStatus("On track", "Close is " + " and ".join(gaps) + ".", "good")
