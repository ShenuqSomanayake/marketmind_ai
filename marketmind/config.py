"""Deployment-wide settings, read from environment variables on every call (so tests and hosts can change them)."""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}


def factual_mode() -> bool:
    """Server-wide switch for public deployments.

    When on, MarketMind shows only factual readings: no "bullish/bearish" labels, and AI text that
    describes indicators without expressing a view on whether an asset will rise, fall or is attractive.
    Users' own predictions, theses and report cards are unaffected, because they're the user's views.
    Set by the operator (``MARKETMIND_FACTUAL_MODE=1``), never by individual users.
    """
    return os.getenv("MARKETMIND_FACTUAL_MODE", "").strip().lower() in _TRUE


def ai_daily_limit() -> int:
    """Maximum AI generations per user per UTC day. 0 = unlimited (default for personal use)."""
    try:
        return max(0, int(os.getenv("MARKETMIND_AI_DAILY_LIMIT", "0")))
    except ValueError:
        return 0
