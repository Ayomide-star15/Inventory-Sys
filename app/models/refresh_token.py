# app/models/refresh_token.py

from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime


class RefreshToken(Document):
    """
    Persisted refresh token record.

    One user can have multiple active sessions (mobile + desktop, etc.).
    Revocation is done by marking is_revoked = True — the raw token
    is never stored, only its SHA-256 hash.
    """
    id: UUID = Field(default_factory=uuid4)     # UUID, not ObjectId

    # Ownership
    user_id: UUID

    # The raw token is NEVER stored — only its SHA-256 hash
    token_hash: str

    # Lifecycle
    expires_at: datetime
    is_revoked: bool = False

    # Optional device/session tracking
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None

    class Settings:
        name = "refresh_tokens"
        use_state_management = True             # needed for .save() to work correctly
        indexes = [
            [("user_id", 1)],
            [("token_hash", 1)],
            [("expires_at", 1)],
        ]