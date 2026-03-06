from typing import List, Optional
from uuid import UUID, uuid4
from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime

class Branch(Document):
    id: UUID = Field(default_factory=uuid4)
    
    name: str = Indexed(unique=True)
    code: str = Indexed(unique=True)
    address: str
    phone: str
    
    zones: List[str] = ["Receiving", "Back Store", "Sales Floor", "Checkout"]
    
    manager_id: Optional[UUID] = None
    
    # ADDED: Soft-delete support — never hard-delete a branch
    is_active: bool = True
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # FIXED: Was Optional[datetime] = None — now has a proper default
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "branches"