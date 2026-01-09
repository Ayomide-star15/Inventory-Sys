from typing import List, Optional
from uuid import UUID, uuid4
from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime

class Branch(Document):
    id: UUID = Field(default_factory=uuid4)
    
    # We use Indexed(unique=True) to prevent duplicate branch codes
    name: str = Indexed(unique=True)
    code: str = Indexed(unique=True)
    address: str
    phone: str
    
    zones: List[str] = ["Receiving", "Back Store", "Sales Floor", "Checkout"]
    
    # NOTICE: We use UUID, not the 'User' class here. 
    # This prevents the circular import error.
    manager_id: Optional[UUID] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "branches"