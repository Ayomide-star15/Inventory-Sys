# app/models/price_history.py - FIXED VERSION

from beanie import Document
from pydantic import Field
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum
from typing import Optional

class PriceChangeType(str, Enum):
    CREATED = "Product Created"
    PRICE_INCREASE = "Price Increase"
    PRICE_DECREASE = "Price Decrease"
    COST_ADJUSTMENT = "Cost Adjustment"
    PROMOTIONAL = "Promotional Price"
    SEASONAL = "Seasonal Adjustment"

class PriceHistory(Document):
    """
    PRICE CHANGE AUDIT TRAIL
    Complete history of all price changes for compliance
    """
    id: UUID = Field(default_factory=uuid4)
    
    # === PRODUCT REFERENCE ===
    product_id: UUID = Field(index=True) # type: ignore
    product_name: str  # Snapshot
    sku: str
    
    # === PRICE CHANGES ===
    # ✓ FIXED: Changed from Field(...) to allow None/Optional
    old_price: Optional[float] = None
    new_price: float
    old_cost_price: Optional[float] = None
    new_cost_price: Optional[float] = None
    
    # === MARGIN INFO ===
    old_margin: Optional[float] = None
    new_margin: Optional[float] = None
    
    # === CHANGE DETAILS ===
    change_type: PriceChangeType
    change_reason: Optional[str] = None
    
    # === WHO & WHEN ===
    changed_by: UUID
    changed_by_name: str
    changed_by_role: str
    
    # === TIMESTAMPS ===
    effective_date: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # === IMPACT ===
    applied_branches: int = 0

    class Settings:
        name = "price_history"
        indexes = [
            [("product_id", 1), ("created_at", -1)],
            [("sku", 1)],
            [("change_type", 1)],
            [("changed_by", 1)],
            [("effective_date", -1)],
            [("created_at", -1)]
        ]