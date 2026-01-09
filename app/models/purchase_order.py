from typing import List, Optional
from datetime import datetime
from enum import Enum
from beanie import Document
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

class POStatus(str, Enum):
    PENDING_APPROVAL = "Pending Approval" # > $5,000
    APPROVED = "Approved"                 # Ready to send
    SENT = "Sent"                         # Emailed to Supplier
    RECEIVED = "Received"                 # Goods arrived
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"

class POItem(BaseModel):
    product_id: UUID
    ordered_quantity: int
    received_quantity: int = 0  # Filled during Receiving
    unit_cost: float
    total_cost: float

class PurchaseOrder(Document):
    id: UUID = Field(default_factory=uuid4)
    supplier_id: UUID
    target_branch: UUID         # Where is this going?
    items: List[POItem]
    
    total_amount: float
    status: POStatus
    
    # Workflow timestamps
    created_by: UUID
    created_at: datetime = datetime.utcnow()
    approved_by: Optional[UUID] = None
    received_at: Optional[datetime] = None
    
    receiving_notes: Optional[str] = None 

    class Settings:
        name = "purchase_orders"