# app/schemas/auth.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ──────────────────────────────────────────────────────────────
# REQUEST SCHEMAS (what the client sends)
# ──────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    """Sent by the client to get a new access token."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Sent by the client to revoke a specific session."""
    refresh_token: str


# ──────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS (what the server sends back)
# ──────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """
    Returned by both /auth/login and /auth/refresh.
    Contains everything the frontend needs to manage the session.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int                  # access token lifetime in seconds (1800 = 30 min)
    refresh_expires_in: int          # refresh token lifetime in seconds (604800 = 7 days)
    role: str
    name: str
    user_id: str
    branch_id: Optional[str] = None


class RefreshTokenRecord(BaseModel):
    """
    Represents one active session.
    Returned when listing a user's active sessions.
    """
    session_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    is_revoked: bool

    class Config:
        from_attributes = True


class LogoutResponse(BaseModel):
    """Returned after a successful logout."""
    message: str


class LogoutAllResponse(BaseModel):
    """Returned after revoking all sessions."""
    message: str
    sessions_revoked: int