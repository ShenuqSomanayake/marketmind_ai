"""Practice mode, factual mode, AI quota, backup/restore and account deletion."""

import io
import json
import sqlite3
import zipfile

import numpy as np
import pandas as pd
import pytest
from conftest import make_ohlcv
from test_domain import FakeClient

from marketmind import auth, backup, practice, research, usage
from marketmind.db import connect
from marketmind.engine import analyse, normalize_ohlcv


# ---------------- practice ----------------
@pytest.fixture
def df():
    return normalize_ohlcv(make_ohlcv(400, seed=11))


def test_round_has_no_lookahead(df):
    r = practice.pick_round(df, "X", 20, np.random.default_rng(1), blind=False)
    assert len(r.future) == 20
    assert r.visible["date"].iloc[-1] < r.future["date"].iloc[0]
    assert r.visible["date"].iloc[-1] == df["date"].iloc[r.cut]
    # The snapshot must equal an analysis of the truncated history (nothing after the cut leaks in).
    snap = practice.snapshot(r)
    trunc = analyse(df.iloc[max(0, r.cut + 1 - 180) : r.cut + 1].reset_index(drop=True))
    assert snap["score"] == trunc["score"] and snap["close"] == pytest.approx(trunc["close"])


def test_blind_mode_disguises_prices_and_dates(df):
    r = practice.pick_round(df, "NVDA", 10, np.random.default_rng(2), blind=True)
    assert r.visible["close"].iloc[0] == pytest.approx(100)
    assert r.visible["date"].iloc[0] == pd.Timestamp("2000-01-03", tz="UTC")
    assert r.future["date"].iloc[0] > r.visible["date"].iloc[-1]
    assert r.real_reference_price == pytest.approx(df["close"].iloc[r.cut])
    # Scaling doesn't change the realised return.
    ev = practice.score(r, "Bullish", 2)
    real = df["close"].iloc[r.cut + 10] / df["close"].iloc[r.cut] - 1
    assert ev.realised_return == pytest.approx(real) and ev.outcome in ("Correct", "Incorrect")


def test_round_bounds_and_errors():
    short = normalize_ohlcv(make_ohlcv(65))
    with pytest.raises(ValueError, match="Need at least"):
        practice.pick_round(short, "X", 20, np.random.default_rng(0))
    d = normalize_ohlcv(make_ohlcv(81))  # exactly MIN_VISIBLE + 20 + 1 bars: one valid cut
    cuts = {practice.pick_round(d, "X", 20, np.random.default_rng(s), blind=False).cut for s in range(20)}
    assert cuts <= {59, 60}


# ---------------- factual mode ----------------
def test_factual_mode_changes_wording_not_numbers(monkeypatch):
    d = normalize_ohlcv(make_ohlcv())
    rep = analyse(d)
    assert "rules met" in rep["rules_summary"]
    monkeypatch.delenv("MARKETMIND_FACTUAL_MODE", raising=False)
    normal = research.build_facts("T", rep)
    assert normal["technical_label"] == rep["label"]
    assert "### Bull case" in research.rules_brief(normal).markdown
    monkeypatch.setenv("MARKETMIND_FACTUAL_MODE", "1")
    facts = research.build_facts("T", rep)
    assert facts["technical_label"] == rep["rules_summary"] and facts["close"] == normal["close"]
    md = research.rules_brief(facts).markdown
    assert "### Rules currently met" in md and "Bull" not in md and "Bear" not in md
    c = FakeClient("### Rules currently met\n- ok")
    research.llm_brief(facts, client=c)
    assert "Do NOT say or imply whether the asset will rise or fall" in c.calls[0]["system"]


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("on", True), ("0", False), ("", False)])
def test_factual_flag_parsing(monkeypatch, val, expected):
    from marketmind.config import factual_mode

    monkeypatch.setenv("MARKETMIND_FACTUAL_MODE", val)
    assert factual_mode() is expected


# ---------------- AI quota ----------------
def test_ai_quota(tmp_db, monkeypatch):
    with connect() as con:
        u = auth.create_user(con, "quota", "a long enough password")
        monkeypatch.setenv("MARKETMIND_AI_DAILY_LIMIT", "0")
        assert usage.remaining(con, u.id) is None
        monkeypatch.setenv("MARKETMIND_AI_DAILY_LIMIT", "2")
        assert usage.remaining(con, u.id) == 2
        usage.record(con, u.id)
        usage.record(con, u.id)
        assert usage.remaining(con, u.id) == 0
        assert usage.remaining(con, u.id, day="2000-01-01") == 2  # resets daily
        monkeypatch.setenv("MARKETMIND_AI_DAILY_LIMIT", "junk")
        assert usage.remaining(con, u.id) is None


# ---------------- backup / restore / delete ----------------
def _seed(con, uid):
    con.execute("INSERT INTO holdings(user_id,ticker,quantity,avg_cost,currency) VALUES(?,?,?,?,?)", (uid, "A", 10, 5.5, "AUD"))
    con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (uid, "B"))
    con.execute(
        "INSERT INTO theses(user_id,ticker,thesis,invalidation,stop_below) VALUES(?,?,?,?,?)",
        (uid, "A", "t, with comma\nand newline", "x", 4.0),
    )
    con.execute(
        "INSERT INTO prediction_log(user_id,ticker,prediction,score,reference_price,mode) VALUES(?,?,?,?,?,?)",
        (uid, "A", "Bullish", 60, 5.0, "practice"),
    )
    con.execute(
        "INSERT INTO paper_trades(user_id,ticker,side,quantity,price,fee,currency) VALUES(?,?,?,?,?,?,?)",
        (uid, "A", "BUY", 1, 10, 0, "USD"),
    )
    con.execute("INSERT INTO paper_accounts(user_id,currency,starting_cash) VALUES(?,?,?)", (uid, "USD", 500))


def test_export_restore_roundtrip(tmp_db):
    with connect() as con:
        a = auth.create_user(con, "alice", "a long enough password")
        b = auth.create_user(con, "bob", "another long password")
        _seed(con, a.id)
        con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (b.id, "BOBS"))
        blob = backup.export_user_data(con, a.id, a.username)
    manifest, frames = backup.read_export(blob)
    assert manifest["tables"]["holdings"] == 1 and "BOBS" not in frames["watchlist"].ticker.tolist()
    with connect() as con:
        con.execute("DELETE FROM holdings WHERE user_id=?", (a.id,))
        con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (a.id, "STALE"))
        counts = backup.import_user_data(con, a.id, blob)
    assert counts["holdings"] == 1
    with connect() as con:
        assert con.execute("SELECT ticker,quantity,avg_cost FROM holdings WHERE user_id=?", (a.id,)).fetchall() == [
            ("A", 10.0, 5.5)
        ]
        assert [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE user_id=?", (a.id,))] == ["B"]
        assert con.execute("SELECT thesis, stop_below FROM theses WHERE user_id=?", (a.id,)).fetchone() == (
            "t, with comma\nand newline",
            4.0,
        )
        assert con.execute("SELECT mode FROM prediction_log WHERE user_id=?", (a.id,)).fetchone()[0] == "practice"
        assert [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE user_id=?", (b.id,))] == ["BOBS"]  # untouched


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


@pytest.mark.parametrize(
    "data,msg",
    [
        (b"not a zip", "Not a ZIP"),
        (_zip({"holdings.csv": "ticker\nA"}), "manifest"),
        (_zip({"manifest.json": json.dumps({"app": "Other"})}), "not exported by MarketMind"),
        (
            _zip({"manifest.json": json.dumps({"app": "MarketMind AI"}), "holdings.csv": "ticker,user_id\nA,1"}),
            "unexpected columns",
        ),
    ],
)
def test_bad_imports_rejected(data, msg):
    with pytest.raises(backup.ImportErrorMM, match=msg):
        backup.read_export(data)


def test_restore_rolls_back_on_invalid_ledger(tmp_db):
    with connect() as con:
        u = auth.create_user(con, "carl", "a long enough password")
        con.execute("INSERT INTO watchlist(user_id,ticker) VALUES(?,?)", (u.id, "KEEP"))
    bad = _zip(
        {
            "manifest.json": json.dumps({"app": "MarketMind AI"}),
            "paper_trades.csv": "ticker,side,quantity,price,fee,currency,created_at\nA,SELL,5,10,0,USD,2026-01-01",
        }
    )
    with pytest.raises(backup.ImportErrorMM, match="cash/position"), connect() as con:
        backup.import_user_data(con, u.id, bad)
    with connect() as con:  # whole restore rolled back, including the watchlist delete
        assert [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE user_id=?", (u.id,))] == ["KEEP"]


def test_delete_account_cascades(tmp_db):
    with connect() as con:
        u = auth.create_user(con, "dora", "a long enough password")
        _seed(con, u.id)
        with pytest.raises(auth.AuthError):
            auth.authenticate(con, "dora", "wrong password here")
        backup.delete_account(con, u.id, u.username)
        for t in [*backup.TABLES, "login_attempts"]:
            col = "username" if t == "login_attempts" else "user_id"
            val = "dora" if t == "login_attempts" else u.id
            assert con.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (val,)).fetchone()[0] == 0  # noqa: S608


def test_cli_backup_and_reset(tmp_db, tmp_path, capsys):
    from marketmind.manage import main

    with connect() as con:
        auth.create_user(con, "erin", "a long enough password")
        for _ in range(auth.MAX_FAILURES):
            with pytest.raises(auth.AuthError):
                auth.authenticate(con, "erin", "wrong password here")
    dest = tmp_path / "b" / "copy.db"
    assert main(["backup", str(dest)]) == 0
    assert sqlite3.connect(dest).execute("SELECT username FROM users").fetchone()[0] == "erin"
    capsys.readouterr()
    assert main(["reset-password", "erin"]) == 0
    temp = capsys.readouterr().out.split(": ", 1)[1].split()[0]
    with connect() as con:
        assert auth.authenticate(con, "erin", temp).username == "erin"  # lockout cleared too
    assert main(["reset-password", "ghost"]) == 1
