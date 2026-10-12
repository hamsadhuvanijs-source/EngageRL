from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import service
from app.db import get_db
from app.deps import bearer_token, get_current_user
from app.models.user import User
from app.schemas.auth import AuthOut, LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> AuthOut:
    user = service.register_user(db, body.email, body.password, body.display_name)
    token = service.issue_token(db, user)
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    user = service.authenticate(db, body.email, body.password)
    token = service.issue_token(db, user)
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(token: str = Depends(bearer_token), db: Session = Depends(get_db)) -> None:
    service.revoke_token(db, token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
