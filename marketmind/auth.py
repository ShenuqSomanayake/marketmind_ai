"""Local account management: PBKDF2 hashing, login throttling and DB-stored roles.

Admin rights are a ``role`` column on the user row. They can only be granted from
a shell on the server (``python -m marketmind.manage grant-admin <username>``),
never by registering a particular username.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ITERATIONS = 310_000
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
USERNAME_RE = re.compile(r"[a-z0-9_.-]{3,32}")
_DUMMY_SALT = secrets.token_bytes(16)


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthError(Exception):
    pass


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)


def clean_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_new_account(username: str, password: str, confirm: str) -> str:
    u = clean_username(username)
    if not USERNAME_RE.fullmatch(u):
        raise AuthError("Username must be 3–32 characters: letters, numbers, _, . or -.")
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Use a password with at least {MIN_PASSWORD} characters.")
    if password.lower() == u or u in password.lower():
        raise AuthError("Password must not contain your username.")
    if password != confirm:
        raise AuthError("Passwords do not match.")
    return u


def create_user(con: sqlite3.Connection, username: str, password: str, confirm: str | None = None) -> User:
    u = validate_new_account(username, password, password if confirm is None else confirm)
    salt = secrets.token_bytes(16)
    try:
        cur = con.execute(
            "INSERT INTO users(username,salt,password_hash) VALUES(?,?,?)", (u, salt, password_hash(password, salt))
        )
    except sqlite3.IntegrityError as e:
        raise AuthError("That username is already taken.") from e
    return User(cur.lastrowid, u, "user")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def recent_failures(con: sqlite3.Connection, username: str, now: datetime | None = None) -> int:
    since = _iso((now or _now()) - LOCKOUT)
    last_ok = con.execute("SELECT MAX(attempted_at) FROM login_attempts WHERE username=? AND success=1", (username,)).fetchone()[
        0
    ]
    floor = max(since, last_ok) if last_ok else since
    return con.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE username=? AND success=0 AND attempted_at>?", (username, floor)
    ).fetchone()[0]


def authenticate(con: sqlite3.Connection, username: str, password: str, now: datetime | None = None) -> User:
    """Return the user or raise ``AuthError``. Uses one generic message to avoid username enumeration."""
    u = clean_username(username)
    t = now or _now()
    if recent_failures(con, u, t) >= MAX_FAILURES:
        raise AuthError(f"Too many failed attempts. Try again in {int(LOCKOUT.total_seconds() // 60)} minutes.")
    row = con.execute("SELECT id,salt,password_hash,role FROM users WHERE username=?", (u,)).fetchone()
    # Always run the hash so response time does not reveal whether the username exists.
    candidate = password_hash(password, row[1] if row else _DUMMY_SALT)
    ok = bool(row) and hmac.compare_digest(candidate, row[2])
    con.execute("INSERT INTO login_attempts(username,success,attempted_at) VALUES(?,?,?)", (u, int(ok), _iso(t)))
    con.commit()
    if not ok:
        raise AuthError("Incorrect username or password.")
    return User(row[0], u, row[3])


def get_user(con: sqlite3.Connection, user_id: int) -> User | None:
    row = con.execute("SELECT id,username,role FROM users WHERE id=?", (user_id,)).fetchone()
    return User(*row) if row else None


def change_password(con: sqlite3.Connection, user: User, current: str, new: str, confirm: str) -> None:
    authenticate(con, user.username, current)
    validate_new_account(user.username, new, confirm)
    salt = secrets.token_bytes(16)
    con.execute("UPDATE users SET salt=?, password_hash=? WHERE id=?", (salt, password_hash(new, salt), user.id))


def set_role(con: sqlite3.Connection, username: str, role: str) -> None:
    if role not in ("user", "admin"):
        raise ValueError("Role must be 'user' or 'admin'.")
    cur = con.execute("UPDATE users SET role=? WHERE username=?", (role, clean_username(username)))
    if cur.rowcount == 0:
        raise AuthError(f"No such user: {username}")


def reset_password(con: sqlite3.Connection, username: str) -> str:
    """Admin/operator reset: set a random temporary password and return it. Clears the lockout."""
    u = clean_username(username)
    temp = secrets.token_urlsafe(12)
    salt = secrets.token_bytes(16)
    cur = con.execute("UPDATE users SET salt=?, password_hash=? WHERE username=?", (salt, password_hash(temp, salt), u))
    if cur.rowcount == 0:
        raise AuthError(f"No such user: {username}")
    con.execute("DELETE FROM login_attempts WHERE username=? AND success=0", (u,))
    return temp
