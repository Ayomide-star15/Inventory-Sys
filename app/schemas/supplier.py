from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime

# 1. Base Schema (Shared properties)
class SupplierBase(BaseModel):
    name: str
    contact_person: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: str
    address: Optional[str] = None
    is_active: bool = True

# 2. Create Schema (What the frontend sends to add a supplier)
class SupplierCreate(SupplierBase):
    pass

# 3. Update Schema (What the frontend sends to edit)
class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None

# 4. Response Schema (What the backend sends back)
class SupplierResponse(SupplierBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True