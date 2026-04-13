# app/schemas/product.py

from pydantic import BaseModel, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime


# ==========================================
# ADMIN: CREATE PRODUCT (no price)
# ==========================================
class ProductCreate(BaseModel):
    """
    Admin only — catalog entry with no price.
    Finance Manager sets selling price separately.
    Cost price lives on each Purchase Order.
    """
    name: str
    sku: str
    barcode: str
    description: Optional[str] = None
    low_stock_threshold: int = 10
    category_id: UUID
    image_url: Optional[str] = None
    # price and cost_price intentionally removed


# ==========================================
# FINANCE MANAGER: SET / UPDATE SELLING PRICE
# ==========================================
class ProductPriceUpdate(BaseModel):
    """
    Finance Manager only.
    Sets or updates the global selling price for a product.
    Cost price is referenced from the latest PO — not stored here.
    """
    price: float
    reference_cost: Optional[float] = None   # from latest PO, used to calculate margin
    reason: Optional[str] = None

    @field_validator('price')
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError('Selling price must be greater than zero')
        return v

    @field_validator('reference_cost')
    def validate_cost(cls, v):
        if v is not None and v <= 0:
            raise ValueError('Reference cost must be greater than zero')
        return v


# ==========================================
# RESPONSE FOR REGULAR STAFF (no cost_price)
# ==========================================
class ProductResponseForStaff(BaseModel):
    id: UUID
    name: str
    sku: str
    barcode: str
    description: Optional[str]
    price: Optional[float]          # None until Finance Manager sets it
    category_id: UUID
    image_url: Optional[str]
    low_stock_threshold: int
    is_priced: bool                 # convenience flag for frontend
    created_at: datetime

    class Config:
        from_attributes = True


# ==========================================
# RESPONSE FOR ADMIN / FINANCE (with margin)
# ==========================================
class ProductResponseForAdmin(BaseModel):
    id: UUID
    name: str
    sku: str
    barcode: str
    description: Optional[str]
    price: Optional[float]
    cost_price: Optional[float]
    margin_percentage: Optional[float]
    category_id: UUID
    image_url: Optional[str]
    low_stock_threshold: int
    is_priced: bool
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: Optional[UUID]
    last_price_change: Optional[datetime]
    last_price_changed_by: Optional[UUID]

    class Config:
        from_attributes = True


# ==========================================
# PRICE HISTORY RESPONSE
# ==========================================
class PriceHistoryItem(BaseModel):
    change_date: datetime
    change_type: str
    old_price: Optional[float]
    new_price: float
    reference_cost: Optional[float]
    old_margin: Optional[float]
    new_margin: Optional[float]
    changed_by: str
    changed_by_role: str
    reason: Optional[str]
    effective_date: datetime


class PriceHistoryResponse(BaseModel):
    product_id: UUID
    product_name: str
    sku: str
    current_price: Optional[float]
    total_changes: int
    history: List[PriceHistoryItem]