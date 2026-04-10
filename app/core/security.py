# app/core/security.py

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# ──────────────────────────────────────────────────────────────
# 1. PASSWORD HASHING
# ──────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ──────────────────────────────────────────────────────────────
# 2. ACCESS TOKEN  (short-lived JWT, default 30 min)
# ──────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    if "type" not in to_encode:
        to_encode["type"] = "access"
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ──────────────────────────────────────────────────────────────
# 3. INVITE TOKEN  (24-hour one-time link)
# ──────────────────────────────────────────────────────────────

def create_invite_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {"exp": expire, "sub": email, "type": "invite"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ──────────────────────────────────────────────────────────────
# 4. REFRESH TOKEN  (long-lived opaque token, stored in DB)
# ──────────────────────────────────────────────────────────────

REFRESH_TOKEN_EXPIRE_DAYS: int = 1


def generate_refresh_token() -> str:
    """
    Returns a cryptographically secure random string (64 hex chars = 256 bits).
    This is the raw value sent to the client — NEVER persisted as-is.
    """
    return secrets.token_hex(32)


def hash_refresh_token(raw_token: str) -> str:
    """
    SHA-256 hash of the raw token — the only form stored in MongoDB.
    Even a full DB dump cannot be replayed without the raw token.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)