from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Any
from app.models.user import UserRole
from datetime import datetime
from uuid import UUID

# --- 1. TOKEN SCHEMAS (These were missing) ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

# Incoming data - No password required
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole = UserRole.STORE_STAFF
    branch_id: Optional[UUID] = None

   # Used when Admin sends the invite. NO password required here
class UserInvite(UserBase):
    pass



# ---  PASSWORD SETUP SCHEMA (New!) ---
# Used when the User clicks the email link to set their password.
class PasswordSetup(BaseModel):
    token: str
    new_password: str

class UserCreate(UserBase):
    password: str

# Properties to return to client
class UserResponse(UserBase): 
    
    # Keep the rest as is
    user_id: UUID
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    branch_id: Optional[str] = None
    
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    
class UserProfile(BaseModel):
    user_id: str
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole
    branch_name: Optional[str] = "Headquarters" # Friendly name!

@field_validator('user_id', mode='before')
@classmethod
def convert_id(cls, v: Any):
        return str(v)

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[UserRole] = None
    branch_id: Optional[str] = None
    is_active: Optional[bool] = None
    
class Config:
        from_attributes = True