from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.core.config import settings
from app.models.user import User, UserRole # <--- Added UserRole import
from app.schemas.user import TokenData

# 1. SETUP OAUTH2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# 2. GET CURRENT USER (Base Dependency)
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
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
        
    user = await User.find_one(User.email == token_data.email)
    if user is None:
        raise credentials_exception
        
    return user

# 3. GET ACTIVE USER (Used by Staff)
async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# 4. GET ADMIN USER (Used by Admin Routes) ⚠️ THIS WAS MISSING
async def get_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Blocks anyone who is not an Admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="⚠️ Access Denied: Only System Administrators can perform this action."
        )
    return current_user

# 🟢 THIS IS THE KEY FUNCTION FOR PRODUCTS
async def get_product_manager(current_user: User = Depends(get_current_active_user)) -> User:
    allowed_roles = [UserRole.ADMIN, UserRole.PURCHASE]
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, 
            detail="Access Denied: Requires Admin or Purchase Manager permissions."
        )

    return current_user

