import sqlite3
from datetime import timedelta

import pytest

from marketmind import auth
from marketmind.db import MIGRATIONS, connect


def test_migrations_idempotent_and_upgrade_from_020(tmp_db):
    con = sqlite3.connect(tmp_db)
    con.executescript(MIGRATIONS[0])  # simulate a 0.2.0 database (user_version 0)
    con.execute("INSERT INTO users(username,salt,password_hash) VALUES('old',x'00',x'00')")
    con.commit()
    con.close()
    for _ in range(2):
        with connect() as c:
            assert c.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
            assert c.execute("SELECT role FROM users WHERE username='old'").fetchone()[0] == "user"


def test_connection_closed_and_rollback(tmp_db):
    with pytest.raises(RuntimeError), connect() as con:
        con.execute("INSERT INTO users(username,salt,password_hash) VALUES('x',x'00',x'00')")
        raise RuntimeError
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")


def test_create_and_authenticate(tmp_db):
    with connect() as con:
        u = auth.create_user(con, "  Alice ", "correct horse battery")
        assert u.username == "alice" and u.role == "user" and not u.is_admin
        assert auth.authenticate(con, "ALICE", "correct horse battery").id == u.id
        with pytest.raises(auth.AuthError, match="Incorrect"):
            auth.authenticate(con, "alice", "wrong password!!")
        with pytest.raises(auth.AuthError, match="Incorrect"):  # same message for unknown user
            auth.authenticate(con, "nobody", "whatever whatever")
        with pytest.raises(auth.AuthError, match="taken"):
            auth.create_user(con, "alice", "another long password")


@pytest.mark.parametrize(
    "u,p,c,msg",
    [
        ("ab", "x" * 12, None, "3–32"),
        ("bob", "short", None, "12"),
        ("bob", "bob-is-my-password", None, "username"),
        ("bob", "x" * 12, "y" * 12, "match"),
    ],
)
def test_account_validation(tmp_db, u, p, c, msg):
    with connect() as con, pytest.raises(auth.AuthError, match=msg):
        auth.create_user(con, u, p, c)


def test_lockout_after_failures_and_expiry(tmp_db):
    with connect() as con:
        auth.create_user(con, "carol", "a very good password")
        t0 = auth._now()
        for i in range(auth.MAX_FAILURES):
            with pytest.raises(auth.AuthError, match="Incorrect"):
                auth.authenticate(con, "carol", "nope nope nope", now=t0 + timedelta(seconds=i))
        with pytest.raises(auth.AuthError, match="Too many"):  # even the right password is refused
            auth.authenticate(con, "carol", "a very good password", now=t0 + timedelta(seconds=10))
        later = t0 + auth.LOCKOUT + timedelta(seconds=30)
        assert auth.authenticate(con, "carol", "a very good password", now=later).username == "carol"


def test_success_resets_failure_count(tmp_db):
    with connect() as con:
        auth.create_user(con, "dave", "a very good password")
        t0 = auth._now()
        for i in range(auth.MAX_FAILURES - 1):
            with pytest.raises(auth.AuthError):
                auth.authenticate(con, "dave", "bad bad bad bad", now=t0 + timedelta(seconds=i))
        auth.authenticate(con, "dave", "a very good password", now=t0 + timedelta(seconds=10))
        with pytest.raises(auth.AuthError, match="Incorrect"):
            auth.authenticate(con, "dave", "bad bad bad bad", now=t0 + timedelta(seconds=11))


def test_admin_only_via_role_not_username(tmp_db, monkeypatch):
    monkeypatch.setenv("MARKETMIND_ADMIN_USERNAME", "sshenuq")  # legacy env var must have no effect
    with connect() as con:
        u = auth.create_user(con, "sshenuq", "squatter password 1")
        assert not auth.get_user(con, u.id).is_admin
        auth.set_role(con, "sshenuq", "admin")
        assert auth.get_user(con, u.id).is_admin
        with pytest.raises(ValueError):
            auth.set_role(con, "sshenuq", "root")


def test_manage_cli(tmp_db, capsys):
    from marketmind.manage import main

    with connect() as con:
        auth.create_user(con, "erin", "a very good password")
    assert main(["grant-admin", "erin"]) == 0
    assert main(["grant-admin", "ghost"]) == 1
    capsys.readouterr()
    main(["list-users"])
    out = capsys.readouterr().out
    assert "erin" in out and "admin" in out
    with connect() as con:
        assert con.execute("SELECT role FROM users WHERE username='erin'").fetchone()[0] == "admin"


def test_change_password(tmp_db):
    with connect() as con:
        u = auth.create_user(con, "fay", "first long password")
        with pytest.raises(auth.AuthError):
            auth.change_password(con, u, "wrong current pw", "second long password", "second long password")
        auth.change_password(con, u, "first long password", "second long password", "second long password")
        assert auth.authenticate(con, "fay", "second long password").id == u.id
