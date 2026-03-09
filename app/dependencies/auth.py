from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.core.config import settings
from app.models.user import User, UserRole
from app.schemas.user import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        sub: str = payload.get("sub")
        token_type: str = payload.get("type", "access")

        if sub is None:
            raise credentials_exception

        # ✅ FIXED: login tokens use email as sub, reset tokens use user_id as sub
        # We must handle both cases gracefully
        if token_type == "reset":
            raise credentials_exception  # reset tokens are NOT valid for auth

    except JWTError:
        raise credentials_exception

    # sub is always email for access tokens (set in auth.py login endpoint)
    user = await User.find_one(User.email == sub)
    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account. Please contact your administrator."
        )
    return current_user


async def get_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only System Administrators can perform this action."
        )
    return current_user


async def get_product_manager(
    current_user: User = Depends(get_current_active_user)
) -> User:
    allowed_roles = [UserRole.ADMIN, UserRole.PURCHASE]
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Requires Admin or Purchase Manager permissions."
        )
    return current_user