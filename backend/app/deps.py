from sqlalchemy.orm import Session

from app.models.user import User

_SINGLE_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_current_user(db: Session) -> User:
    """v0 has no auth: everything belongs to one implicit local user."""
    user = db.get(User, _SINGLE_USER_ID)
    if user is None:
        user = User(id=_SINGLE_USER_ID)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
