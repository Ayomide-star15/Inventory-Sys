# app/routers/auth.py

import logging
from datetime import datetime
from typing import cast
from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.results import UpdateResult

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.core.security import (
    verify_password,
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.schemas.auth import (
    RefreshRequest,
    LogoutRequest,
    TokenResponse,
    LogoutResponse,
    LogoutAllResponse,
)
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip, mask_email
from app.core.rate_limit import limiter
from app.dependencies.auth import get_current_active_user

router = APIRouter()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────────────────────

async def _issue_tokens(user: User, request: Request) -> dict:
    """
    Mint a fresh access + refresh token pair for the given user.
    Persists the hashed refresh token to MongoDB.
    """
    access_token = create_access_token(data={"sub": user.email, "type": "access"})

    raw_refresh = generate_refresh_token()
    token_record = RefreshToken(
        user_id=user.user_id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=refresh_token_expiry(),
        user_agent=request.headers.get("user-agent"),
        ip_address=extract_ip(request),
    )
    await token_record.insert()  # type: ignore[misc]

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": 1800,
        "refresh_expires_in": 7 * 24 * 3600,
        "role": user.role,
        "name": f"{user.first_name} {user.last_name}",
        "user_id": str(user.user_id),
        "branch_id": str(user.branch_id) if user.branch_id else None,
    }


# ──────────────────────────────────────────────────────────────
# 1. LOGIN
# ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> dict:
    """
    Authenticate with email + password.
    Returns an access token (30 min) and a refresh token (7 days).
    """
    ip = extract_ip(request)
    user = await User.find_one(User.email == form_data.username)

    if not user:
        logger.warning(f"Failed login for {mask_email(form_data.username)} from {ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account setup incomplete. Check your invite email to set your password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form_data.password, user.hashed_password):
        await log_action(  # type: ignore[func-returns-value]
            user=user,
            action=AuditAction.LOGIN_FAILED,
            module=AuditModule.AUTH,
            description=f"Failed login attempt for {user.email}",
            ip_address=ip,
            metadata={"email": user.email},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active. Please contact your administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.last_login = datetime.utcnow()
    await user.save()  # type: ignore[misc]

    response = await _issue_tokens(user, request)

    await log_action(  # type: ignore[func-returns-value]
        user=user,
        action=AuditAction.LOGIN,
        module=AuditModule.AUTH,
        description=f"{user.first_name} {user.last_name} logged in as {user.role.value}",
        ip_address=ip,
        metadata={"role": user.role.value},
    )

    return response


# ──────────────────────────────────────────────────────────────
# 2. REFRESH
# ──────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_access_token(
    request: Request,
    body: RefreshRequest,
) -> dict:
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    The old refresh token is revoked immediately (rotation).
    """
    token_hash = hash_refresh_token(body.refresh_token)
    record = await RefreshToken.find_one(RefreshToken.token_hash == token_hash)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    if record.is_revoked:
        # Token reuse detected — possible theft, kill all sessions
        await RefreshToken.find(  # type: ignore[misc]
            RefreshToken.user_id == record.user_id,
            RefreshToken.is_revoked == False,  # noqa: E712
        ).update_many({"$set": {
            "is_revoked": True,
            "revoked_at": datetime.utcnow()
        }})

        logger.warning(
            f"Revoked refresh token reuse detected for user_id={record.user_id}. "
            f"All sessions invalidated."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used. All sessions invalidated. Please log in again.",
        )

    if datetime.utcnow() > record.expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please log in again.",
        )

    # Rotate: revoke old, issue new
    record.is_revoked = True
    record.revoked_at = datetime.utcnow()
    await record.save()  # type: ignore[misc]

    user = await User.find_one(User.user_id == record.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or no longer exists.",
        )

    return await _issue_tokens(user, request)


# ──────────────────────────────────────────────────────────────
# 3. LOGOUT
# ──────────────────────────────────────────────────────────────

@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    body: LogoutRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Revoke the supplied refresh token for the current session.
    The client should also discard its access token locally.
    """
    token_hash = hash_refresh_token(body.refresh_token)
    record = await RefreshToken.find_one(RefreshToken.token_hash == token_hash)

    if record and not record.is_revoked:
        if record.user_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot revoke another user's session.",
            )
        record.is_revoked = True
        record.revoked_at = datetime.utcnow()
        await record.save()  # type: ignore[misc]

    await log_action(  # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.LOGOUT,
        module=AuditModule.AUTH,
        description=f"{current_user.first_name} {current_user.last_name} logged out",
        ip_address=extract_ip(request),
    )

    return {"message": "Logged out successfully."}


# ──────────────────────────────────────────────────────────────
# 4. LOGOUT ALL SESSIONS
# ──────────────────────────────────────────────────────────────

@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all_sessions(
    request: Request,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Revoke all active refresh tokens for the current user.
    Useful after a password change or suspected account compromise.
    """
    raw_result = await RefreshToken.find(  # type: ignore[misc]
        RefreshToken.user_id == current_user.user_id,
        RefreshToken.is_revoked == False,  # noqa: E712
    ).update_many({"$set": {
        "is_revoked": True,
        "revoked_at": datetime.utcnow()
    }})

    update_result = cast(UpdateResult, raw_result)
    sessions_revoked: int = update_result.modified_count if update_result else 0

    await log_action(  # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.LOGOUT,
        module=AuditModule.AUTH,
        description=f"{current_user.first_name} {current_user.last_name} logged out of all sessions",
        ip_address=extract_ip(request),
        metadata={"sessions_revoked": sessions_revoked},
    )

    return {
        "message": "All sessions have been revoked. Please log in again.",
        "sessions_revoked": sessions_revoked,
    }