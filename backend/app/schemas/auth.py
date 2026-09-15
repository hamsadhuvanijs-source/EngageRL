import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Deliberately loose — just enough to reject obvious non-addresses without pulling in the
# optional email-validator dependency.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _EmailIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("invalid email address")
        return value


class RegisterIn(_EmailIn):
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class LoginIn(_EmailIn):
    password: str


class UserOut(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthOut(BaseModel):
    token: str
    user: UserOut
