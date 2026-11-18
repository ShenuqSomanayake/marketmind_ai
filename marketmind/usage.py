"""Per-user daily quota for language-model calls (protects the operator's API bill)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .config import ai_daily_limit


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def used_today(con: sqlite3.Connection, user_id: int, day: str | None = None) -> int:
    row = con.execute("SELECT calls FROM ai_usage WHERE user_id=? AND day=?", (user_id, day or _today())).fetchone()
    return row[0] if row else 0


def remaining(con: sqlite3.Connection, user_id: int, day: str | None = None) -> int | None:
    """Calls left today, or None when there is no limit."""
    limit = ai_daily_limit()
    return None if limit == 0 else max(0, limit - used_today(con, user_id, day))


def record(con: sqlite3.Connection, user_id: int, day: str | None = None) -> None:
    con.execute(
        "INSERT INTO ai_usage(user_id,day,calls) VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET calls=calls+1",
        (user_id, day or _today()),
    )
