"""Registration, login, and bearer-token lifecycle. Kept separate from the router so the
logic is unit-testable without HTTP.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.security import generate_token, hash_password, hash_token, verify_password
from app.config import get_settings
from app.models.auth_token import AuthToken
from app.models.user import User


def register_user(db: Session, email: str, password: str, display_name: str | None) -> User:
    email = email.strip().lower()
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return user


def issue_token(db: Session, user: User) -> str:
    raw = generate_token()
    ttl_days = get_settings().auth_token_ttl_days
    expires_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=ttl_days)
        if ttl_days
        else None
    )
    db.add(AuthToken(user_id=user.id, token_hash=hash_token(raw), expires_at=expires_at))
    db.commit()
    return raw


def resolve_token(db: Session, raw_token: str) -> User | None:
    row = db.query(AuthToken).filter(AuthToken.token_hash == hash_token(raw_token)).one_or_none()
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        db.delete(row)
        db.commit()
        return None
    row.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return db.get(User, row.user_id)


def revoke_token(db: Session, raw_token: str) -> None:
    row = db.query(AuthToken).filter(AuthToken.token_hash == hash_token(raw_token)).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
