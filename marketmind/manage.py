"""Server-side admin CLI. Requires shell access to the host, which is the authorisation.

python -m marketmind.manage grant-admin <username>
python -m marketmind.manage revoke-admin <username>
python -m marketmind.manage list-users
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .auth import AuthError, reset_password, set_role
from .backup import backup_database
from .db import connect, db_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m marketmind.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("grant-admin", "revoke-admin"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list-users")
    sub.add_parser("reset-password").add_argument("username")
    sub.add_parser("backup").add_argument("dest", nargs="?")
    args = ap.parse_args(argv)
    with connect() as con:
        if args.cmd == "backup":
            dest = args.dest or db_path().parent / "backups" / f"marketmind-{datetime.now():%Y%m%d-%H%M%S}.db"
            print(f"Backup written to {backup_database(con, dest)}")
            return 0
        if args.cmd == "reset-password":
            try:
                temp = reset_password(con, args.username)
            except AuthError as e:
                print(e, file=sys.stderr)
                return 1
            print(f"Temporary password for {args.username}: {temp}\nAsk them to change it in Settings after signing in.")
            return 0
        if args.cmd == "list-users":
            for uid, name, role, created in con.execute("SELECT id,username,role,created_at FROM users ORDER BY id"):
                print(f"{uid:>4}  {name:<32} {role:<6} {created}")
            return 0
        try:
            set_role(con, args.username, "admin" if args.cmd == "grant-admin" else "user")
        except AuthError as e:
            print(e, file=sys.stderr)
            return 1
    print(f"{args.cmd} applied to {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
