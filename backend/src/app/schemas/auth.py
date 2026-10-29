from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AdminSessionResponse(BaseModel):
    id: int
    username: str
    is_active: bool
    authenticated: bool = True


class LogoutResponse(BaseModel):
    ok: bool = True
    message: str = "Logged out"


class ChangeCredentialsRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_username: str | None = Field(default=None, min_length=1, max_length=150)
    new_password: str | None = Field(default=None, min_length=8, max_length=200)

    @model_validator(mode="after")
    def _at_least_one_change(self):
        if self.new_username is not None:
            self.new_username = self.new_username.strip()
            if not self.new_username:
                raise ValueError("new_username must not be blank")
        if self.new_username is None and self.new_password is None:
            raise ValueError("Provide new_username and/or new_password")
        return self
