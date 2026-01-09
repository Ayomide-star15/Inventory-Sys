from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.core.security import get_password_hash, verify_password, create_access_token
from pymongo.errors import DuplicateKeyError

router = APIRouter()


# ---------------------------------------------------------
# 2. LOGIN ENDPOINT (Get Token)
# ---------------------------------------------------------
@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Find user by email
    user = await User.find_one(User.email == form_data.username)
    
    # Verify User and Password
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 👇 CRITICAL FIX: Change 'user.id' to 'user.email'
    access_token = create_access_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "name": f"{user.first_name} {user.last_name}"
    }