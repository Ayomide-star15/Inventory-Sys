from beanie import Document
from pydantic import Field
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum


class TransferStatus(str, Enum):
    PENDING = "Pending"              # Just created, awaiting approval
    APPROVED = "Approved"            # Manager approved, ready to ship
    IN_TRANSIT = "In Transit"        # Items picked up, on the way
    COMPLETED = "Completed"          # Received at destination
    CANCELLED = "Cancelled"          # Transfer cancelled
    REJECTED = "Rejected"            # Destination rejected


class TransferItem(dict):
    """Individual item in a transfer"""
    product_id: UUID
    product_name: str
    quantity_requested: int
    quantity_approved: int = 0       # May approve less than requested
    quantity_sent: int = 0           # Actual quantity sent
    quantity_received: int = 0       # Actual quantity received


class StockTransfer(Document):
    """
    Stock transfer between branches.
    Workflow: Request → Approve → Ship → Receive
    """
    id: UUID = Field(default_factory=uuid4)
    
    # Transfer Details
    from_branch_id: UUID
    to_branch_id: UUID
    items: List[dict]  # List of TransferItem
    
    # Status & Workflow
    status: TransferStatus = TransferStatus.PENDING
    priority: str = "Normal"  # Low, Normal, High, Urgent
    
    # People involved
    requested_by: UUID           # Store Manager who requested
    approved_by: Optional[UUID] = None
    shipped_by: Optional[UUID] = None    # Store Staff who packed/sent
    received_by: Optional[UUID] = None   # Store Staff who received
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    
    # Notes
    reason: str  # "Low stock at destination", "Overstocked at source", etc.
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    shipping_notes: Optional[str] = None
    receiving_notes: Optional[str] = None
    
    class Settings:
        name = "stock_transfers"
