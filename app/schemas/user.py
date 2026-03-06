from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Any
from app.models.user import UserRole
from datetime import datetime
from uuid import UUID


# --- TOKEN SCHEMAS ---
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole = UserRole.STORE_STAFF
    branch_id: Optional[UUID] = None


class UserInvite(UserBase):
    pass


class PasswordSetup(BaseModel):
    token: str
    new_password: str


class UserCreate(UserBase):
    password: str


class UserResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    branch_id: Optional[str] = None

    class Config:
        from_attributes = True


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
    branch_name: Optional[str] = "Headquarters"

    # ✅ FIXED: field_validator is now correctly INSIDE the class
    @field_validator('user_id', mode='before')
    @classmethod
    def convert_id(cls, v: Any) -> str:
        return str(v)

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[UserRole] = None
    branch_id: Optional[str] = None
    is_active: Optional[bool] = None