from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from app.models.user import User
from app.core.security import verify_password, create_access_token

router = APIRouter()


@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Login with email + password.
    Returns a JWT bearer token.
    """

    # 1. Find user by email (form username field = email)
    user = await User.find_one(User.email == form_data.username)

    # 2. Check user exists and password matches
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ✅ Guard: account was invited but password never set yet
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account setup incomplete. Please check your invite email to set your password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Check account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active. Please contact your administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. ✅ sub = email (MUST match what get_current_user() expects to decode)
    access_token = create_access_token(data={"sub": user.email, "type": "access"})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "name": f"{user.first_name} {user.last_name}",
        "user_id": str(user.user_id),
        "branch_id": str(user.branch_id) if user.branch_id else None
    }