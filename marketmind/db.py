"""SQLite storage with versioned schema migrations.

Every call site uses ``with connect() as con:`` so connections are always closed
and each block commits atomically (or rolls back on error).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "marketmind.db"

MIGRATIONS: list[str] = [
    # v1 — original 0.2.0 tables
    """
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL,
        password_hash BLOB NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS holdings(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL,
        quantity REAL NOT NULL, avg_cost REAL NOT NULL, currency TEXT DEFAULT 'USD', UNIQUE(user_id,ticker),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL,
        UNIQUE(user_id,ticker), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS calendar_events(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, event_date TEXT NOT NULL,
        event TEXT NOT NULL, region TEXT DEFAULT '', impact TEXT DEFAULT 'Medium', notes TEXT DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS theses(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL,
        thesis TEXT NOT NULL, invalidation TEXT DEFAULT '', review_date TEXT DEFAULT '', status TEXT DEFAULT 'Active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS prediction_log(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL,
        prediction TEXT NOT NULL, score INTEGER NOT NULL, reference_price REAL NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, outcome TEXT DEFAULT 'Pending', notes TEXT DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS paper_trades(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL,
        side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL DEFAULT 0,
        currency TEXT DEFAULT 'USD', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    """,
    # v2 — roles, login throttling, objective prediction scoring, paper-trading cash accounts
    """
    ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';
    CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY, username TEXT NOT NULL, success INTEGER NOT NULL,
        attempted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
    CREATE INDEX IF NOT EXISTS ix_login_attempts ON login_attempts(username, attempted_at);
    ALTER TABLE prediction_log ADD COLUMN as_of TEXT;
    ALTER TABLE prediction_log ADD COLUMN horizon_bars INTEGER NOT NULL DEFAULT 20;
    ALTER TABLE prediction_log ADD COLUMN threshold_pct REAL NOT NULL DEFAULT 2.0;
    ALTER TABLE prediction_log ADD COLUMN realised_return REAL;
    ALTER TABLE prediction_log ADD COLUMN evaluated_at TEXT;
    CREATE TABLE IF NOT EXISTS paper_accounts(user_id INTEGER NOT NULL, currency TEXT NOT NULL, starting_cash REAL NOT NULL,
        PRIMARY KEY(user_id, currency), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    """,
    # v3 — report card context and structured thesis triggers
    """
    ALTER TABLE prediction_log ADD COLUMN ret20_at_entry REAL;
    ALTER TABLE prediction_log ADD COLUMN rsi_at_entry REAL;
    ALTER TABLE theses ADD COLUMN entry_price REAL;
    ALTER TABLE theses ADD COLUMN stop_below REAL;
    ALTER TABLE theses ADD COLUMN stop_above REAL;
    """,
    # v4 — practice-mode predictions are stored alongside live ones but kept separate in every statistic
    """
    ALTER TABLE prediction_log ADD COLUMN mode TEXT NOT NULL DEFAULT 'live';
    CREATE INDEX IF NOT EXISTS ix_prediction_mode ON prediction_log(user_id, mode);
    CREATE TABLE IF NOT EXISTS ai_usage(user_id INTEGER NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(user_id, day), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    """,
    # v5 — chart patterns present when a prediction was made ("name|direction|status;…")
    """
    ALTER TABLE prediction_log ADD COLUMN patterns_at_entry TEXT;
    """,
]


def db_path() -> Path:
    return Path(os.getenv("MARKETMIND_DB_PATH", str(DEFAULT_PATH)))


def migrate(con: sqlite3.Connection) -> int:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    # A 0.2.0 database already has v1 tables but user_version 0; v1 uses IF NOT EXISTS so re-running is safe.
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        for stmt in (s.strip() for s in script.split(";")):
            if not stmt:
                continue
            try:
                con.execute(stmt)
            except sqlite3.OperationalError as e:  # column already added by a partial earlier run
                if "duplicate column" not in str(e):
                    raise
        con.execute(f"PRAGMA user_version={i}")
    con.commit()
    return len(MIGRATIONS)


@contextmanager
def connect(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(path or db_path())
    try:
        con.execute("PRAGMA foreign_keys=ON")
        migrate(con)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
