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
    # 1. Email is now the unique identifier (Username is removed)
    email: EmailStr = Indexed(unique=True)
    
    # 2. Split Name Fields
    first_name: str
    last_name: str
# Password is None until they accept their invite and set it
    hashed_password: Optional[str] = None
    branch_id: Optional[str] = None
    role: UserRole
    #Account is inactive until [password is set / invite accepted]
    is_active: bool = False
    

    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Settings:
        name = "users"