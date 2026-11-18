"""Rule-based chart-pattern detection with no look-ahead, plus each pattern's historical track record.

How it stays honest
-------------------
* **Pivots are only "known" k bars after they happen.** A swing high at bar *i* needs *k* lower highs after it,
  so the engine learns about it at bar *i + k*, exactly as a person watching live would.
* **The engine walks forward one bar at a time** and only ever sees bars up to the current one. A pattern's
  ``confirmed_at`` bar is the first bar on which a live observer could have known it. A test checks that cutting
  the history short never changes any pattern confirmed before the cut.
* **Track records are compared with a base rate**: how often *any* bar was followed by the same move. A pattern
  that "works" 55% of the time on a stock that rose 54% of all 20-day windows adds almost nothing.

Patterns are defined by fixed geometric rules (tolerances below). Real chartists disagree about borderline cases;
these rules are a consistent, testable definition, not the only possible one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .engine import rsi, wilder_smooth

PIVOT_K = 5  # bars each side that must be lower (for a high) / higher (for a low)
MIN_SWING_ATR = 1.5  # a swing must move at least this many ATRs from the previous opposite pivot
PEAK_TOL = 0.03  # double tops/bottoms: the two peaks within 3%
SHOULDER_TOL = 0.05  # head & shoulders: shoulders within 5% of each other
HEAD_MIN = 0.02  # head at least 2% beyond both shoulders
DEPTH_MIN = 0.03  # trough between double-top peaks at least 3% below them
MIN_GAP = 10  # bars between the two peaks of a double top/bottom
FLAT_SLOPE = 0.0003  # |slope| below 0.03% of price per bar counts as flat
LEVEL_TOL = 0.015  # pivots within 1.5% form one support/resistance level
BREAK_MARGIN = 0.005  # a breakout must close 0.5% beyond the level
BREAK_VOLUME = 1.3  # …on at least 1.3× the 20-bar average volume
LEVEL_LOOKBACK = 250  # only pivots from the last 250 bars form levels
DIV_RSI_GAP = 3.0  # RSI must differ by 3+ points between the two pivots for a divergence

DESCRIPTIONS = {
    "Double top": "Two similar highs with a dip between; confirmed when price closes below the dip (the neckline).",
    "Double bottom": "Two similar lows with a bounce between; confirmed when price closes above the bounce high.",
    "Head and shoulders": "Three highs, the middle one highest; confirmed on a close below the line joining the two dips.",
    "Inverse head and shoulders": "Three lows, the middle one lowest; confirmed on a close above the line joining the two bounces.",
    "Ascending triangle": "Flat highs and rising lows; the event is the first close outside the triangle.",
    "Descending triangle": "Falling highs and flat lows; the event is the first close outside the triangle.",
    "Symmetrical triangle": "Falling highs and rising lows converging; the event is the first close outside.",
    "Resistance breakout": "A close 0.5%+ above a level touched 2+ times, on 1.3×+ average volume.",
    "Support breakdown": "A close 0.5%+ below a level touched 2+ times, on 1.3×+ average volume.",
    "Bullish RSI divergence": "Price makes a lower low but RSI makes a higher low (momentum fading on the way down).",
    "Bearish RSI divergence": "Price makes a higher high but RSI makes a lower high (momentum fading on the way up).",
}


@dataclass(frozen=True)
class Pivot:
    idx: int
    price: float
    kind: str  # "H" | "L"
    known_at: int
    date: pd.Timestamp


@dataclass
class Event:
    name: str
    direction: int  # +1 bullish, −1 bearish
    confirmed_at: int
    date: pd.Timestamp
    price: float  # close on the confirmation bar
    level: float | None  # neckline / breakout level at confirmation
    points: list[tuple[int, float]] = field(default_factory=list)  # pivots that define the shape

    @property
    def direction_word(self) -> str:
        return "Bullish" if self.direction > 0 else "Bearish"


@dataclass
class _Candidate:
    name: str
    direction: int
    points: list[tuple[int, float]]
    line: tuple[float, float, float, float]  # (x0, y0, x1, y1): the trigger line through two pivots
    invalid_above: float | None
    invalid_below: float | None
    expires: int
    upper: tuple[float, float, float, float] | None = None  # triangles: both bounding lines
    lower: tuple[float, float, float, float] | None = None
    key: tuple = ()

    def line_at(self, t: int, line=None) -> float:
        x0, y0, x1, y1 = line or self.line
        return y0 if x1 == x0 else y0 + (y1 - y0) * (t - x0) / (x1 - x0)


def _atr(df: pd.DataFrame) -> np.ndarray:
    h, low, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1)
    return wilder_smooth(tr.where(c.shift().notna()), 14).to_numpy()


def _raw_pivots(df: pd.DataFrame, k: int) -> list[tuple[int, str]]:
    """Centred swing points. Each is only usable from bar idx + k (see ``scan``)."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    out = []
    for i in range(k, len(df) - k):
        if hi[i] >= hi[i - k : i].max() and hi[i] > hi[i + 1 : i + k + 1].max():
            out.append((i, "H"))
        if lo[i] <= lo[i - k : i].min() and lo[i] < lo[i + 1 : i + k + 1].min():
            out.append((i, "L"))
    return out


@dataclass
class ScanResult:
    events: list[Event]
    pivots: list[Pivot]  # the alternating swing list known at the last bar
    forming: list[_Candidate]  # patterns in place but not yet confirmed at the last bar


def scan(df: pd.DataFrame, k: int = PIVOT_K) -> ScanResult:
    """Walk forward bar by bar and emit every pattern at the first bar it could have been confirmed."""
    d = df.reset_index(drop=True)
    n = len(d)
    close, vol = d["close"].to_numpy(), d["volume"].to_numpy()
    dates = d["date"]
    atr = _atr(d)
    rsi14 = rsi(d["close"], 14).to_numpy()
    vol_avg = d["volume"].rolling(20).mean().shift(1).to_numpy()  # average of the 20 bars BEFORE t
    by_known: dict[int, list[tuple[int, str]]] = {}
    for i, kind in _raw_pivots(d, k):
        by_known.setdefault(i + k, []).append((i, kind))

    piv: list[Pivot] = []
    cands: list[_Candidate] = []
    seen: set[tuple] = set()
    events: list[Event] = []
    level_hit: set[tuple] = set()

    def add_pivot(i: int, kind: str, t: int) -> bool:
        price = float(d.at[i, "high"] if kind == "H" else d.at[i, "low"])
        p = Pivot(i, price, kind, t, dates.iloc[i])
        if piv and piv[-1].kind == kind:  # same side twice: keep the more extreme one
            if (kind == "H" and price > piv[-1].price) or (kind == "L" and price < piv[-1].price):
                piv[-1] = p
                return True
            return False
        if piv and not np.isnan(atr[i]) and abs(price - piv[-1].price) < MIN_SWING_ATR * atr[i]:
            return False  # too small a swing to count
        piv.append(p)
        return True

    def new_candidates(t: int) -> None:
        if len(piv) >= 3:
            a, b, c = piv[-3], piv[-2], piv[-1]
            span = c.idx - a.idx
            if a.kind == "H" and c.idx - a.idx >= MIN_GAP:
                top = max(a.price, c.price)
                if abs(c.price - a.price) / top <= PEAK_TOL and b.price <= min(a.price, c.price) * (1 - DEPTH_MIN):
                    _add(_Candidate("Double top", -1, [(a.idx, a.price), (b.idx, b.price), (c.idx, c.price)],
                                    (b.idx, b.price, b.idx + 1, b.price), top * (1 + PEAK_TOL), None, t + 2 * span,
                                    key=("DT", a.idx, c.idx)))  # fmt: skip
            if a.kind == "L" and c.idx - a.idx >= MIN_GAP:
                bot = min(a.price, c.price)
                if abs(c.price - a.price) / bot <= PEAK_TOL and b.price >= max(a.price, c.price) * (1 + DEPTH_MIN):
                    _add(_Candidate("Double bottom", 1, [(a.idx, a.price), (b.idx, b.price), (c.idx, c.price)],
                                    (b.idx, b.price, b.idx + 1, b.price), None, bot * (1 - PEAK_TOL), t + 2 * span,
                                    key=("DB", a.idx, c.idx)))  # fmt: skip
        if len(piv) >= 5:
            s1, n1, h, n2, s2 = piv[-5:]
            span = s2.idx - s1.idx
            if s1.kind == "H":
                if (
                    h.price >= max(s1.price, s2.price) * (1 + HEAD_MIN)
                    and abs(s1.price - s2.price) / max(s1.price, s2.price) <= SHOULDER_TOL
                ):
                    _add(_Candidate("Head and shoulders", -1, [(p.idx, p.price) for p in piv[-5:]],
                                    (n1.idx, n1.price, n2.idx, n2.price), h.price, None, t + span, key=("HS", s1.idx, s2.idx)))  # fmt: skip
            else:
                if (
                    h.price <= min(s1.price, s2.price) * (1 - HEAD_MIN)
                    and abs(s1.price - s2.price) / min(s1.price, s2.price) <= SHOULDER_TOL
                ):
                    _add(_Candidate("Inverse head and shoulders", 1, [(p.idx, p.price) for p in piv[-5:]],
                                    (n1.idx, n1.price, n2.idx, n2.price), None, h.price, t + span, key=("IHS", s1.idx, s2.idx)))  # fmt: skip
        if len(piv) >= 4:
            last4 = piv[-4:]
            highs = [p for p in last4 if p.kind == "H"]
            lows = [p for p in last4 if p.kind == "L"]
            if len(highs) == 2 and len(lows) == 2:
                ha, hb = highs
                la, lb = lows
                ref = float(np.mean([p.price for p in last4]))
                su = (hb.price - ha.price) / (hb.idx - ha.idx) / ref
                sl = (lb.price - la.price) / (lb.idx - la.idx) / ref
                flat_u, flat_l = abs(su) < FLAT_SLOPE, abs(sl) < FLAT_SLOPE
                kind = None
                if flat_u and sl > FLAT_SLOPE:
                    kind = "Ascending triangle"
                elif flat_l and su < -FLAT_SLOPE:
                    kind = "Descending triangle"
                elif su < -FLAT_SLOPE and sl > FLAT_SLOPE:
                    kind = "Symmetrical triangle"
                if kind:
                    up = (ha.idx, ha.price, hb.idx, hb.price)
                    lo_ = (la.idx, la.price, lb.idx, lb.price)
                    span = last4[-1].idx - last4[0].idx
                    c_ = _Candidate(kind, 0, [(p.idx, p.price) for p in last4], up, None, None, t + span,
                                    upper=up, lower=lo_, key=("TRI", last4[0].idx, last4[-1].idx))  # fmt: skip
                    if c_.line_at(t, up) > c_.line_at(t, lo_):  # still open at the time it is recognised
                        _add(c_)

    def _add(c: _Candidate) -> None:
        if c.key not in seen:
            seen.add(c.key)
            cands.append(c)

    def divergences(t: int, p: Pivot) -> None:
        same = [q for q in piv[:-1] if q.kind == p.kind]
        if not same:
            return
        q = same[-1]
        r_now, r_prev = rsi14[p.idx], rsi14[q.idx]
        if np.isnan(r_now) or np.isnan(r_prev) or p.idx - q.idx > 60:
            return
        if p.kind == "L" and p.price < q.price and r_now >= r_prev + DIV_RSI_GAP and r_prev < 40:
            events.append(
                Event("Bullish RSI divergence", 1, t, dates.iloc[t], float(close[t]), None, [(q.idx, q.price), (p.idx, p.price)])
            )
        if p.kind == "H" and p.price > q.price and r_now <= r_prev - DIV_RSI_GAP and r_prev > 60:
            events.append(
                Event("Bearish RSI divergence", -1, t, dates.iloc[t], float(close[t]), None, [(q.idx, q.price), (p.idx, p.price)])
            )

    for t in range(n):
        for i, kind in by_known.get(t, []):
            if add_pivot(i, kind, t):
                divergences(t, piv[-1])
                new_candidates(t)

        # Pattern candidates: confirm, invalidate or expire using bar t only.
        alive = []
        for c in cands:
            ct = float(close[t])
            if c.name.endswith("triangle"):
                upv, lov = c.line_at(t, c.upper), c.line_at(t, c.lower)
                if upv <= lov or t > c.expires:
                    continue
                if ct > upv * (1 + BREAK_MARGIN) or ct < lov * (1 - BREAK_MARGIN):
                    up = ct > upv
                    events.append(Event(f"{c.name}", 1 if up else -1, t, dates.iloc[t], ct, upv if up else lov, c.points))
                    continue
                alive.append(c)
                continue
            if (
                (c.invalid_above is not None and ct > c.invalid_above)
                or (c.invalid_below is not None and ct < c.invalid_below)
                or t > c.expires
            ):
                continue
            neck = c.line_at(t)
            if (c.direction < 0 and ct < neck) or (c.direction > 0 and ct > neck):
                events.append(Event(c.name, c.direction, t, dates.iloc[t], ct, neck, c.points))
                continue
            alive.append(c)
        cands = alive

        # Horizontal support / resistance breaks against levels known so far.
        if t >= 1 and not np.isnan(vol_avg[t]) and vol[t] >= BREAK_VOLUME * vol_avg[t]:
            recent = [p for p in piv if t - p.idx <= LEVEL_LOOKBACK]
            for lv_price, members in _levels(recent):
                key = (round(lv_price, 6), members)
                if key in level_hit:
                    continue
                up_line, down_line = lv_price * (1 + BREAK_MARGIN), lv_price * (1 - BREAK_MARGIN)
                if close[t - 1] < up_line <= close[t]:  # first close beyond the margin above the level
                    level_hit.add(key)
                    events.append(Event("Resistance breakout", 1, t, dates.iloc[t], float(close[t]), lv_price, []))
                elif close[t - 1] > down_line >= close[t]:
                    level_hit.add(key)
                    events.append(Event("Support breakdown", -1, t, dates.iloc[t], float(close[t]), lv_price, []))

    events.sort(key=lambda e: (e.confirmed_at, e.name))
    return ScanResult(events, list(piv), cands)


def _levels(pivots: list[Pivot]) -> list[tuple[float, tuple]]:
    pts = sorted(pivots, key=lambda p: p.price)
    groups: list[list[Pivot]] = []
    for p in pts:
        if groups and abs(p.price - np.mean([q.price for q in groups[-1]])) / p.price <= LEVEL_TOL:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [(float(np.mean([q.price for q in g])), tuple(sorted(q.idx for q in g))) for g in groups if len(g) >= 2]


# --------------------------------------------------------------------------- #
# Track record
# --------------------------------------------------------------------------- #
MIN_EVENTS = 10
Z_SIGNIFICANT = 1.96  # roughly 95% confidence that the difference from the base rate isn't luck


def edge_z(hit: float, base: float, n: int) -> float:
    """One-sample z statistic of the pattern's hit rate against the asset's base rate (normal approximation)."""
    if n == 0 or not 0 < base < 1:
        return float("nan")
    return float((hit - base) / np.sqrt(base * (1 - base) / n))


def verdict(hit: float, base: float, n: int) -> str:
    if n < MIN_EVENTS:
        return "Too few to judge"
    z = edge_z(hit, base, n)
    if z >= Z_SIGNIFICANT:
        return "Better than base rate"
    if z <= -Z_SIGNIFICANT:
        return "Worse than base rate"
    return "No clear edge"


def track_record(df: pd.DataFrame, events: list[Event], horizon: int = 20, threshold_pct: float = 2.0) -> pd.DataFrame:
    """Per pattern & direction: how often price moved past the threshold in the pattern's direction within
    ``horizon`` bars of confirmation, versus the base rate for any bar on the same asset."""
    close = df["close"].to_numpy()
    n = len(close)
    thr = threshold_pct / 100
    fwd = np.full(n, np.nan)
    if n > horizon:
        fwd[: n - horizon] = close[horizon:] / close[: n - horizon] - 1
    valid = fwd[~np.isnan(fwd)]
    base_up = float((valid > thr).mean()) if len(valid) else float("nan")
    base_down = float((valid < -thr).mean()) if len(valid) else float("nan")
    rows = []
    groups: dict[tuple[str, int], list[float]] = {}
    for e in events:
        if not np.isnan(fwd[e.confirmed_at]):
            groups.setdefault((e.name, e.direction), []).append(float(fwd[e.confirmed_at]))
    for (name, direction), rets in sorted(groups.items()):
        r = np.array(rets)
        hit = float((r > thr).mean()) if direction > 0 else float((r < -thr).mean())
        base = base_up if direction > 0 else base_down
        rows.append(
            {
                "Pattern": name,
                "Direction": "Bullish" if direction > 0 else "Bearish",
                "Occurrences": len(r),
                "Worked": hit,
                "Base rate": base,
                "Edge (pts)": (hit - base) * 100,
                "z": edge_z(hit, base, len(r)),
                "Avg move after": float(r.mean()),
                "Verdict": verdict(hit, base, len(r)),
            }
        )
    cols = ["Pattern", "Direction", "Occurrences", "Worked", "Base rate", "Edge (pts)", "z", "Avg move after", "Verdict"]
    return pd.DataFrame(rows, columns=cols)


def tags_at_end(result: ScanResult, df: pd.DataFrame, recent_bars: int = 10) -> list[tuple[str, int, str]]:
    """(name, direction, status) for patterns confirmed in the last ``recent_bars`` bars or still forming.
    Forming triangles have direction 0 (the breakout side is unknown)."""
    n = len(df)
    tags = [(e.name, e.direction, "confirmed") for e in result.events if e.confirmed_at >= n - recent_bars]
    tags += [(c.name, c.direction, "forming") for c in result.forming]
    return tags


def encode_tags(tags: list[tuple[str, int, str]]) -> str:
    return ";".join(f"{n}|{d}|{s}" for n, d, s in tags)


def decode_tags(text: str | None) -> list[tuple[str, int, str]]:
    if not text or text != text:
        return []
    out = []
    for part in str(text).split(";"):
        bits = part.split("|")
        if len(bits) == 3:
            out.append((bits[0], int(bits[1]), bits[2]))
    return out


def describe_tags(tags: list[tuple[str, int, str]]) -> list[str]:
    word = {1: "bullish", -1: "bearish", 0: "direction open"}
    return [f"{n} ({word[d]}, {s})" for n, d, s in tags]
