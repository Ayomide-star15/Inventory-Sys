from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime


# Shared base properties
class BranchBase(BaseModel):
    name: str
    code: str
    address: str
    phone: str
    zones: List[str] = ["Receiving", "Back Store", "Sales Floor", "Checkout"]


# Input: Creating a new branch (Admin only)
class BranchCreate(BranchBase):
    pass


# Input: Updating branch details (Admin only)
class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    zones: Optional[List[str]] = None


# Input: Assigning a manager to a branch (Admin only)
class BranchAssignManager(BaseModel):
    manager_id: UUID


# Output: Full branch details (for Admin / Finance)
class BranchResponse(BranchBase):
    id: UUID
    manager_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Output: Summary for non-admin staff (hides internal timestamps)
class BranchSummaryResponse(BaseModel):
    id: UUID
    name: str
    code: str
    address: str
    phone: str
    is_active: bool

    class Config:
        from_attributes = True