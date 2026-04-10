from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

class RefreshToken(Document):
    """
    Persisted refresh token record.
 
    One user can have multiple active sessions (mobile + desktop, etc.).
    Revocation is done by deleting or marking this record — no need to
    wait for the token to expire.
    """
    id: UUID = Field(default_Factory = uuid4) # type: ignore
    user_id: UUID = Field(index = True)  #type: ignore
    token_hash: str = Field(index = True, unique = True) #type: ignore

    expires_at: datetime
    is_revoked: bool = False
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    created_at: datetime = Field(default_factory = datetime.utcnow)    
    revoked_at: Optional[datetime] = None

    class Settings:
        name = "refresh_tokens"
        indexes = [
            [("user_id", 1)],
            [("token_hash", 1)],
            [("expires_at", 1)],
        ]