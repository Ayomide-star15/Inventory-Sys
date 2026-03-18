from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List
import logging                          # ✅ ADDED
from app.models.user import User
from app.models.branch import Branch
from app.schemas.user import (
    UserInvite, UserResponse, PasswordSetup, UserProfile,
    UserUpdate, ForgotPasswordRequest, ResetPasswordRequest
)
from app.core.security import get_password_hash, create_invite_token, create_access_token
from app.dependencies.auth import get_admin_user, get_current_active_user
from app.core.config import settings
from app.core.email import send_invite_email, send_reset_password_email
from app.core.rate_limit import limiter
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip
from datetime import timedelta
from jose import jwt, JWTError
from uuid import UUID

router = APIRouter()
logger = logging.getLogger(__name__)    # ✅ ADDED


# ---------------------------------------------------------
# 1. INVITE NEW USER (Admin Only)
# ---------------------------------------------------------
@router.post("/admin/create-user", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_user(
    request: Request,
    invite_data: UserInvite,
    admin: User = Depends(get_admin_user)
):
    if await User.find_one(User.email == invite_data.email):
        raise HTTPException(400, detail=f"User with email {invite_data.email} already exists.")

    if invite_data.branch_id:
        branch = await Branch.get(invite_data.branch_id)
        if not branch:
            raise HTTPException(404, detail=f"Branch ID {invite_data.branch_id} not found.")

    new_user = User(
        email=invite_data.email,
        first_name=invite_data.first_name,
        last_name=invite_data.last_name,
        role=invite_data.role,
        branch_id=invite_data.branch_id,
        hashed_password=None,
        is_active=False
    )
    await new_user.insert()

    # ✅ FIXED — no longer deletes user if email fails
    try:
        token = create_invite_token(invite_data.email)
        await send_invite_email(invite_data.email, token)
    except Exception as e:
        logger.error(f"Invite email failed for {invite_data.email}: {e}")
        await log_action(
            user=admin,
            action=AuditAction.USER_INVITED,
            module=AuditModule.USERS,
            description=f"Admin invited {invite_data.email} as {invite_data.role.value} (email failed)",
            target_id=str(new_user.user_id),
            target_type="user",
            metadata={
                "email": invite_data.email,
                "role": invite_data.role.value,
                "branch_id": str(invite_data.branch_id) if invite_data.branch_id else None
            },
            ip_address=extract_ip(request)
        )
        return {
            "message": f"User {invite_data.email} created but invite email failed. Please resend manually.",
            "user_id": str(new_user.user_id),
            "email_sent": False
        }

    await log_action(
        user=admin,
        action=AuditAction.USER_INVITED,
        module=AuditModule.USERS,
        description=f"Admin invited {invite_data.email} as {invite_data.role.value}",
        target_id=str(new_user.user_id),
        target_type="user",
        metadata={
            "email": invite_data.email,
            "role": invite_data.role.value,
            "branch_id": str(invite_data.branch_id) if invite_data.branch_id else None
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": f"Invite sent successfully to {invite_data.email}",
        "user_id": str(new_user.user_id),
        "email_sent": True                  # ✅ ADDED
    }


# ---------------------------------------------------------
# 2. SETUP PASSWORD
# ---------------------------------------------------------
@router.post("/setup-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def setup_password(request: Request, data: PasswordSetup):
    try:
        payload = jwt.decode(data.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        if token_type != "invite":
            raise HTTPException(status_code=400, detail="Invalid token type.")
    except JWTError:
        raise HTTPException(status_code=400, detail="Token is invalid or expired.")

    user = await User.find_one(User.email == email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_active:
        raise HTTPException(status_code=400, detail="Account is already active. Please login.")

    user.hashed_password = get_password_hash(data.new_password)
    user.is_active = True
    await user.save()

    await log_action(
        user=user,
        action=AuditAction.PASSWORD_SETUP,
        module=AuditModule.AUTH,
        description=f"{user.first_name} {user.last_name} completed account setup",
        target_id=str(user.user_id),
        target_type="user",
        ip_address=extract_ip(request)
    )

    return {"message": "Account activated successfully! You can now login."}


# ---------------------------------------------------------
# 3. LIST ALL USERS (Admin Only)
# ---------------------------------------------------------
@router.get("/", response_model=List[dict])
async def list_users(admin: User = Depends(get_admin_user)):
    users = await User.find_all().to_list()
    return [
        {
            "user_id": str(u.user_id),
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "role": u.role,
            "is_active": u.is_active,
            "branch_id": str(u.branch_id) if u.branch_id else None,
            "last_login": u.last_login
        }
        for u in users
    ]


# ---------------------------------------------------------
# 4. GET MY PROFILE
# ---------------------------------------------------------
@router.get("/me", response_model=UserProfile)
async def get_my_profile(current_user: User = Depends(get_current_active_user)):
    branch_name = "Headquarters"
    if current_user.branch_id:
        branch = await Branch.get(current_user.branch_id)
        if branch:
            branch_name = branch.name

    return {
        "user_id": str(current_user.user_id),
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "branch_name": branch_name
    }


# ---------------------------------------------------------
# 5. FORGOT PASSWORD
# ---------------------------------------------------------
@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, req: ForgotPasswordRequest):
    user = await User.find_one(User.email == req.email)
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}

    access_token_expires = timedelta(minutes=15)
    reset_token = create_access_token(
        data={"sub": str(user.user_id), "type": "reset"},
        expires_delta=access_token_expires
    )

    # ✅ FIXED — no longer raises error when email fails
    try:
        await send_reset_password_email(user.email, reset_token, user.first_name)
    except Exception as e:
        logger.error(f"Reset email failed for {user.email}: {e}")

    return {"message": "If that email exists, a reset link has been sent."}


# ---------------------------------------------------------
# 6. RESET PASSWORD
# ---------------------------------------------------------
@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, req: ResetPasswordRequest):
    try:
        payload = jwt.decode(req.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if not user_id or token_type != "reset":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await User.find_one(User.user_id == UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(req.new_password)
    await user.save()

    await log_action(
        user=user,
        action=AuditAction.PASSWORD_RESET,
        module=AuditModule.AUTH,
        description=f"{user.first_name} {user.last_name} reset their password",
        target_id=str(user.user_id),
        target_type="user",
        ip_address=extract_ip(request)
    )

    return {"message": "Password updated successfully"}


# ---------------------------------------------------------
# 7. UPDATE USER (Admin Only)
# ---------------------------------------------------------
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    update_data: UserUpdate,
    request: Request,
    admin: User = Depends(get_admin_user)
):
    user = await User.find_one(User.user_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes = {}
    old_values = {}

    if update_data.first_name is not None:
        old_values["first_name"] = user.first_name
        user.first_name = update_data.first_name
        changes["first_name"] = update_data.first_name

    if update_data.last_name is not None:
        old_values["last_name"] = user.last_name
        user.last_name = update_data.last_name
        changes["last_name"] = update_data.last_name

    if update_data.role is not None:
        old_values["role"] = user.role.value
        user.role = update_data.role
        changes["role"] = update_data.role.value

    if update_data.is_active is not None:
        old_values["is_active"] = user.is_active
        user.is_active = update_data.is_active
        changes["is_active"] = update_data.is_active

    if update_data.branch_id is not None:
        if update_data.branch_id == "":
            old_values["branch_id"] = str(user.branch_id) if user.branch_id else None
            user.branch_id = None
            changes["branch_id"] = None
        else:
            branch = await Branch.get(update_data.branch_id)
            if not branch:
                raise HTTPException(status_code=404, detail=f"Branch {update_data.branch_id} not found")
            old_values["branch_id"] = str(user.branch_id) if user.branch_id else None
            user.branch_id = branch.id
            changes["branch_id"] = str(branch.id)

    await user.save()

    if "role" in changes:
        action = AuditAction.USER_ROLE_CHANGED
        description = f"Changed {user.first_name}'s role from {old_values['role']} to {changes['role']}"
    elif "branch_id" in changes:
        action = AuditAction.USER_BRANCH_CHANGED
        description = f"Changed {user.first_name}'s branch assignment"
    else:
        action = AuditAction.USER_UPDATED
        description = f"Updated user profile for {user.first_name} {user.last_name}"

    await log_action(
        user=admin,
        action=action,
        module=AuditModule.USERS,
        description=description,
        target_id=str(user_id),
        target_type="user",
        metadata={"changes": changes, "previous": old_values},
        ip_address=extract_ip(request)
    )

    return {
        "user_id": user.user_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "is_active": user.is_active,
        "branch_id": str(user.branch_id) if user.branch_id else None
    }


# ---------------------------------------------------------
# 8. CHANGE USER STATUS
# ---------------------------------------------------------
@router.patch("/{user_id}/status", response_model=dict)
async def change_user_status(
    user_id: UUID,
    active: bool,
    request: Request,
    admin: User = Depends(get_admin_user)
):
    user = await User.find_one(User.user_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    user.is_active = active
    await user.save()

    action = AuditAction.USER_ACTIVATED if active else AuditAction.USER_DEACTIVATED
    status_msg = "activated" if active else "deactivated"

    await log_action(
        user=admin,
        action=action,
        module=AuditModule.USERS,
        description=f"Admin {status_msg} user: {user.first_name} {user.last_name} ({user.role.value})",
        target_id=str(user_id),
        target_type="user",
        metadata={"is_active": active, "user_email": user.email},
        ip_address=extract_ip(request)
    )

    return {
        "message": f"User {user.first_name} has been {status_msg} successfully.",
        "user_id": str(user.user_id),
        "is_active": user.is_active
    }