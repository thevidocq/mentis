"""Operator commands, run inside the API container.

    docker compose exec api python -m app.cli reset-2fa user@example.com
    docker compose exec api python -m app.cli unlock user@example.com
"""

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset-2fa", help="Remove a user's authenticator; they enroll again at next login").add_argument("email")
    sub.add_parser("unlock", help="Clear a login lockout").add_argument("email")
    args = parser.parse_args()

    db = next(get_db())
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
