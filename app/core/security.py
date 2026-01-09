from datetime import datetime, timedelta
from typing import Optional, Union, Any
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

# 1. Password Hashing Setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# 2. UNIVERSAL TOKEN CREATOR (Updated)
# 👇 This function now accepts 'data: dict' instead of just 'subject'
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Add expiration time
    to_encode.update({"exp": expire})
    
    # If no type is specified, default to "access" (for login)
    if "type" not in to_encode:
        to_encode["type"] = "access"
        
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

# 3. INVITE TOKEN
def create_invite_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode = {
        "exp": expire, 
        "sub": email, 
        "type": "invite"
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt