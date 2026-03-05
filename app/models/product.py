# app/models/product.py - FIXED VERSION

from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

class Product(Document):
    """
    GLOBAL PRODUCT MODEL
    Price is global - applies to all branches
    """
    id: UUID = Field(default_factory=uuid4)
    
    # === IDENTIFICATION ===
    name: str = Field(..., unique=True) # type: ignore
    sku: str = Field(..., unique=True) # type: ignore
    barcode: str = Field(..., unique=True) # type: ignore
    description: Optional[str] = None
    
    # === GLOBAL PRICING (applies to ALL branches) ===
    # ✓ FIXED: Changed from Field(..., gt=0) to proper defaults
    price: float  # Selling price - visible to all staff
    cost_price: float  # Cost price - admin only
    
    # === STOCK MANAGEMENT ===
    low_stock_threshold: int = Field(default=10)
    
    # === CATEGORY ===
    category_id: UUID
    image_url: Optional[str] = None
    
    # === PRICING HISTORY ===
    last_price_change: Optional[datetime] = None
    last_price_changed_by: Optional[UUID] = None
    
    # === METADATA ===
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: UUID
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[UUID] = None

    class Settings:
        name = "products"
        indexes = [
            [("sku", 1)],
            [("barcode", 1)],
            [("category_id", 1)],
            [("price", 1)],
            [("created_at", -1)],
            [("updated_at", -1)]
        ]