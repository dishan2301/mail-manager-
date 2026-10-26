"""Reset an existing OEIS login password in the configured database."""

import argparse
from getpass import getpass

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password, revoke_user_sessions
from app.models.entities import LoginThrottle, User


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=get_settings().bootstrap_admin_email)
    args = parser.parse_args()
    password = getpass("New password (at least 6 characters): ")
    if len(password) < 6:
        parser.error("password must contain at least 6 characters")
    if password != getpass("Confirm new password: "):
        parser.error("passwords do not match")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            parser.error(f"account {args.email!r} does not exist in this database")
        if not user.active:
            parser.error(f"account {args.email!r} is inactive")
        user.password_hash = hash_password(password)
        revoke_user_sessions(db, user.id, "password_reset")
        # Both account and source-address throttles can block the next login.
        db.execute(delete(LoginThrottle))
        db.commit()
    print(f"Password reset for {args.email}. Sign in again.")


if __name__ == "__main__":
    main()
