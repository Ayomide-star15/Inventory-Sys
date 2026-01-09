from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


# Input for Creating PO
class POItemInput(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    unit_cost: float


class POCreateSchema(BaseModel):
    supplier_id: UUID
    target_branch: UUID
    items: List[POItemInput]


# Input for Receiving Goods
class ReceivedItemInput(BaseModel):
    product_id: UUID
    received_qty: int = Field(ge=0)


class ReceiveGoodsSchema(BaseModel):
    items: List[ReceivedItemInput]
    notes: Optional[str] = None


# Response schemas
class POItemResponse(BaseModel):
    product_id: UUID
    ordered_quantity: int
    received_quantity: int
    unit_cost: float
    total_cost: float


class POResponse(BaseModel):
    id: UUID
    supplier_id: UUID
    target_branch: UUID
    items: List[POItemResponse]
    total_amount: float
    status: str
    created_by: UUID
    created_at: datetime
    approved_by: Optional[UUID] = None
    received_at: Optional[datetime] = None
    receiving_notes: Optional[str] = None
