from datetime import datetime

from pydantic import BaseModel, Field


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
