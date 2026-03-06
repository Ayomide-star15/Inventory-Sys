from beanie import Document, Indexed
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4


class UserRole(str, Enum):
    ADMIN = "System Administrator"
    FINANCE = "Finance Manager"
    PURCHASE = "Purchase Manager"
    STORE_MANAGER = "Store Manager"
    STORE_STAFF = "Store Staff"
    SALES_STAFF = "Sales Staff"


class User(Document):
    user_id: UUID = Field(default_factory=uuid4)
    email: EmailStr = Indexed(unique=True)
    first_name: str
    last_name: str
    hashed_password: Optional[str] = None
    branch_id: Optional[UUID] = None
    role: UserRole
    is_active: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Settings:
        name = "users"  # ✅ FIXED: Was outside User class, so MongoDB collection name was never set


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[UserRole] = None
    branch_id: Optional[UUID] = None
    is_active: Optional[bool] = None