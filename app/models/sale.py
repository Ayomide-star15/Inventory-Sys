from beanie import Document
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum


class PaymentMethod(str, Enum):
    CASH = "Cash"
    CARD = "Card"
    TRANSFER = "Bank Transfer"
    MOBILE_MONEY = "Mobile Money"


class SaleStatus(str, Enum):
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    REFUNDED = "Refunded"


class SaleItem(BaseModel):
    """Individual item in a sale - embedded in Sale document"""
    product_id: UUID
    product_name: str
    sku: str
    barcode: str
    quantity_sold: int
    unit_price: float  # Price at time of sale (snapshot)
    line_total: float  # quantity_sold × unit_price


class Sale(Document):
    """
    Main sales transaction record.
    Created when a customer completes purchase at checkout.
    """
    id: UUID = Field(default_factory=uuid4)
    
    # Sale Identification
    sale_number: str  # e.g., "SALE-2025-00001" - human-readable
    
    # Location & Staff
    branch_id: UUID  # Which branch this sale occurred at
    sold_by: UUID    # User ID of cashier/sales staff
    
    # Items Sold
    items: List[SaleItem]
    
    # Financial Details
    subtotal: float       # Sum of all line_totals
    tax: float = 0.0      # VAT or sales tax if applicable
    discount: float = 0.0 # Any discounts applied
    total_amount: float   # subtotal + tax - discount
    
    # Payment
    payment_method: PaymentMethod
    amount_paid: float = 0.0      # How much customer gave
    change_given: float = 0.0     # Change returned to customer
    
    # Status & Tracking
    status: SaleStatus = SaleStatus.COMPLETED
    
    # Optional Fields
    till_number: Optional[str] = None  # Which checkout counter
    notes: Optional[str] = None        # Special notes (refunds, issues)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    cancelled_at: Optional[datetime] = None
    
    # Cancellation tracking
    cancelled_by: Optional[UUID] = None
    cancellation_reason: Optional[str] = None

    class Settings:
        name = "sales"
        indexes = [
            "sale_number",
            "branch_id",
            "sold_by",
            "created_at",
            "status"
        ]