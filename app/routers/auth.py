from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime
from app.models.user import User
from app.core.security import verify_password, create_access_token
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip, mask_email
from app.core.rate_limit import limiter  # <--- NEW

router = APIRouter()


@router.post("/login")
@limiter.limit("5/minute")  # <--- NEW: Limit to 5 login attempts per minute per IP
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    Login with email + password.
    Returns a JWT bearer token.
    Records login attempt in audit log.
    """
    ip = extract_ip(request)

    # 1. Find user by email
    user = await User.find_one(User.email == form_data.username)

    # 2. User not found
    if not user:
        # Log failed attempt without exposing user existence
        print(f"⚠️ Failed login attempt for {mask_email(form_data.username)} from {ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Account invited but password never set
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account setup incomplete. Please check your invite email to set your password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Wrong password
    if not verify_password(form_data.password, user.hashed_password):
        # ✅ Log failed login
        await log_action(
            user=user,
            action=AuditAction.LOGIN_FAILED,
            module=AuditModule.AUTH,
            description=f"Failed login attempt for {user.email}",
            ip_address=ip,
            metadata={"email": user.email}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 5. Inactive account
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active. Please contact your administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 6.Update last_login timestamp
    user.last_login = datetime.utcnow()
    await user.save()

    # 7. Generate token
    access_token = create_access_token(data={"sub": user.email, "type": "access"})

    # 8. Log successful login
    await log_action(
        user=user,
        action=AuditAction.LOGIN,
        module=AuditModule.AUTH,
        description=f"{user.first_name} {user.last_name} logged in as {user.role.value}",
        ip_address=ip,
        metadata={"role": user.role.value}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "name": f"{user.first_name} {user.last_name}",
        "user_id": str(user.user_id),
        "branch_id": str(user.branch_id) if user.branch_id else None
    }