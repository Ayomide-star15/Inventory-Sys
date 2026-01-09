from beanie import Document
from pydantic import Field, EmailStr
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

class Supplier(Document):
    id: UUID = Field(default_factory=uuid4)
    
    # Company Details
    name: str = Field(..., unique=True) # e.g. "Dangote Flour Mills"
    contact_person: Optional[str] = None # e.g. "Mr. Ahmed"
    
    # Contact Info
    email: Optional[EmailStr] = None
    phone: str = Field(...) # Mandatory: You must be able to call them
    address: Optional[str] = None
    
    # Status
    is_active: bool = True # Set to False if you stop trading with them
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "suppliers"