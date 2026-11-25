"""Operator commands, run inside the API container.

    docker compose exec api python -m app.cli create-admin
    docker compose exec api python -m app.cli reset-2fa user@example.com
    docker compose exec api python -m app.cli unlock user@example.com
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.db import get_db
from app.models import User
from app.services.logs import log_event
from app.services.sessions import revoke_all_sessions


def _user(db, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        sys.exit(f"No user with email {email}")
    return user


def create_admin(db, email: str | None, name: str | None) -> None:
    from app.services import setup

    if not setup.needs_setup(db):
        sys.exit("A user already exists. Add more super-admins from Users in the web interface.")
    email = email or input("Email: ").strip()
    name = name or input("Full name: ").strip()
    password = getpass.getpass("Password (12+ chars, upper and lower case, a digit): ")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match.")
    try:
        admin = setup.create_first_admin(db, email, name, password)
    except setup.SetupError as e:
        sys.exit(str(e))
    log_event(db, "setup.completed", actor=admin, detail={"via": "cli"})
    print(f"Super-admin {admin.email} created. Sign in: two-factor enrollment starts at the first login.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    ca = sub.add_parser("create-admin", help="Create the first super-admin (only when no user exists yet)")
    ca.add_argument("--email")
    ca.add_argument("--name")
    sub.add_parser("reset-2fa", help="Remove a user's authenticator; they enroll again at next login").add_argument("email")
    sub.add_parser("unlock", help="Clear a login lockout").add_argument("email")
    args = parser.parse_args()

    db = next(get_db())
    if args.command == "create-admin":
        create_admin(db, args.email, args.name)
        return
    user = _user(db, args.email)
    if args.command == "reset-2fa":
        user.totp_secret_enc = None
        user.totp_enabled = False
        db.commit()
        revoke_all_sessions(db, user)
        log_event(db, "auth.mfa.reset_by_operator", actor=user, target=user.email)
        print(f"2FA reset for {user.email}. Sessions revoked; the user enrolls again at next login.")
    elif args.command == "unlock":
        user.locked_until = None
        user.failed_logins = 0
        db.commit()
        log_event(db, "auth.unlocked_by_operator", actor=user, target=user.email)
        print(f"{user.email} unlocked.")


if __name__ == "__main__":
    main()
