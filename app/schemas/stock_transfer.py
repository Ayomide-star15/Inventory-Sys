from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class TransferItemCreate(BaseModel):
    """Schema for creating transfer items"""
    product_id: UUID
    quantity: int = Field(..., gt=0, description="Quantity to transfer")


class ApprovedQuantityItem(BaseModel):
    """Schema for approved quantity items"""
    product_id: UUID
    quantity: int = Field(..., gt=0, description="Approved quantity")


class StockTransferCreate(BaseModel):
    """Schema for creating a new stock transfer"""
    from_branch_id: UUID
    to_branch_id: UUID
    items: List[TransferItemCreate]
    reason: str = Field(..., min_length=10, description="Reason for transfer")
    priority: str = "Normal"
    notes: Optional[str] = None


class StockTransferApprove(BaseModel):
    """Schema for approving a transfer"""
    approved_quantities: Optional[List[ApprovedQuantityItem]] = None
    notes: Optional[str] = None


class ShipQuantityItem(BaseModel):
    """Schema for shipped quantity items"""
    product_id: UUID
    quantity: int = Field(..., gt=0, description="Quantity shipped")


class StockTransferShip(BaseModel):
    """Schema for shipping a transfer"""
    actual_quantities: List[ShipQuantityItem]
    shipping_notes: Optional[str] = None


class ReceiveQuantityItem(BaseModel):
    """Schema for received quantity items"""
    product_id: UUID
    quantity: int = Field(..., gt=0, description="Quantity received")


class StockTransferReceive(BaseModel):
    """Schema for receiving a transfer"""
    received_quantities: List[ReceiveQuantityItem]
    receiving_notes: Optional[str] = None


class StockTransferReject(BaseModel):
    """Schema for rejecting a transfer"""
    rejection_reason: str = Field(..., min_length=10)


class StockTransferResponse(BaseModel):
    """Schema for transfer response"""
    id: str
    from_branch_name: str
    to_branch_name: str
    status: str
    priority: str
    items_count: int
    total_quantity: int
    created_at: datetime
    reason: str
