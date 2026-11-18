"""Per-user export/restore (ZIP of CSVs) and whole-database backups."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import __version__
from .portfolio import DEFAULT_PAPER_CASH, PAPER_CURRENCIES, OrderRejected, replay

APP = "MarketMind AI"
MAX_IMPORT_BYTES = 20 * 1024 * 1024

# Every user-owned table and the columns that belong to the user (ids are regenerated on restore).
TABLES: dict[str, tuple[str, ...]] = {
    "holdings": ("ticker", "quantity", "avg_cost", "currency"),
    "watchlist": ("ticker",),
    "calendar_events": ("event_date", "event", "region", "impact", "notes"),
    "theses": (
        "ticker",
        "thesis",
        "invalidation",
        "review_date",
        "status",
        "created_at",
        "entry_price",
        "stop_below",
        "stop_above",
    ),
    "prediction_log": (
        "ticker",
        "prediction",
        "score",
        "reference_price",
        "created_at",
        "outcome",
        "notes",
        "as_of",
        "horizon_bars",
        "threshold_pct",
        "realised_return",
        "evaluated_at",
        "ret20_at_entry",
        "rsi_at_entry",
        "mode",
        "patterns_at_entry",
    ),  # fmt: skip
    "paper_trades": ("ticker", "side", "quantity", "price", "fee", "currency", "created_at"),
    "paper_accounts": ("currency", "starting_cash"),
}


class ImportErrorMM(ValueError):
    pass


def export_user_data(con: sqlite3.Connection, user_id: int, username: str) -> bytes:
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table, cols in TABLES.items():
            rows = con.execute(f"SELECT {','.join(cols)} FROM {table} WHERE user_id=? ORDER BY rowid", (user_id,)).fetchall()  # noqa: S608 - fixed identifiers
            counts[table] = len(rows)
            z.writestr(f"{table}.csv", pd.DataFrame(rows, columns=list(cols)).to_csv(index=False))
        manifest = {
            "app": APP,
            "version": __version__,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "username": username,
            "tables": counts,
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def read_export(data: bytes) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Parse and validate an export ZIP without touching the database."""
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportErrorMM("File is too large to be a MarketMind export.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ImportErrorMM("Not a ZIP file.") from e
    with z:
        names = set(z.namelist())
        if "manifest.json" not in names:
            raise ImportErrorMM("Missing manifest.json — is this a MarketMind export?")
        if sum(i.file_size for i in z.infolist()) > 10 * MAX_IMPORT_BYTES:  # zip-bomb guard
            raise ImportErrorMM("Export expands to an implausible size.")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != APP:
            raise ImportErrorMM("This file was not exported by MarketMind AI.")
        frames = {}
        for table, cols in TABLES.items():
            if f"{table}.csv" not in names:
                frames[table] = pd.DataFrame(columns=list(cols))
                continue
            df = pd.read_csv(io.BytesIO(z.read(f"{table}.csv")), dtype=object, keep_default_na=False, na_values=[""])
            unknown = set(df.columns) - set(cols)
            if unknown:
                raise ImportErrorMM(f"{table}.csv has unexpected columns: {', '.join(sorted(unknown))}")
            frames[table] = df.reindex(columns=[c for c in cols if c in df.columns])
    return manifest, frames


def import_user_data(con: sqlite3.Connection, user_id: int, data: bytes) -> dict[str, int]:
    """Replace this user's records with the export's. Call inside ``db.connect()`` so any error rolls back everything."""
    _, frames = read_export(data)
    counts = {}
    for table, df in frames.items():
        con.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))  # noqa: S608 - fixed identifiers
        if df.empty:
            counts[table] = 0
            continue
        cols = list(df.columns)
        rows = [tuple(None if pd.isna(v) else v for v in r) for r in df.itertuples(index=False)]
        con.executemany(
            f"INSERT INTO {table}(user_id,{','.join(cols)}) VALUES(?{',?' * len(cols)})",  # noqa: S608 - fixed identifiers
            [(user_id, *r) for r in rows],
        )
        counts[table] = len(rows)
    # The paper ledger must still obey cash/position rules after restore.
    cash = dict(con.execute("SELECT currency,starting_cash FROM paper_accounts WHERE user_id=?", (user_id,)).fetchall())
    trades = con.execute(
        "SELECT ticker,side,quantity,price,fee,currency FROM paper_trades WHERE user_id=? ORDER BY created_at,id", (user_id,)
    ).fetchall()
    for c in PAPER_CURRENCIES:
        cash.setdefault(c, DEFAULT_PAPER_CASH)
    try:
        replay(cash, trades)
    except OrderRejected as e:
        raise ImportErrorMM(f"Paper trades in the export break cash/position rules: {e}") from e
    return counts


def backup_database(src: sqlite3.Connection, dest: Path | str) -> Path:
    """Consistent online copy of the whole database (safe while the app is running)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
    return dest


def delete_account(con: sqlite3.Connection, user_id: int, username: str) -> None:
    """Remove the user and (via ON DELETE CASCADE) every record they own, plus their login history."""
    con.execute("DELETE FROM users WHERE id=?", (user_id,))
    con.execute("DELETE FROM login_attempts WHERE username=?", (username,))
