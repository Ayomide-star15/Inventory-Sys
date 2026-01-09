from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

# Shared properties
class BranchBase(BaseModel):
    name: str
    code: str              # e.g., "LOS-001"
    address: str
    phone: str
    zones: List[str] = ["Receiving", "Back Store", "Sales Floor", "Checkout"]

# Input data when creating a branch
class BranchCreate(BranchBase):
    pass

# Output data when reading a branch (includes the ID)
class BranchResponse(BranchBase):
    id: UUID
    manager_id: Optional[UUID] = None
    
    class Config:
        from_attributes = True