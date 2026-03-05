from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime

# === FOR CREATING PRODUCTS (Admin/PM only) ===
class ProductCreate(BaseModel):
    """Only Admin/Purchase Manager can create with both prices"""
    name: str
    sku: str
    barcode: str
    description: Optional[str] = None
    price: float  # Selling price
    cost_price: float  # Cost price
    low_stock_threshold: int = 10
    category_id: UUID
    image_url: Optional[str] = None
    
    @field_validator('price', 'cost_price')
    def validate_prices(cls, v):
        if v <= 0:
            raise ValueError('Price must be positive')
        return v

# === FOR UPDATING PRICES (Admin/PM only) ===
class ProductPriceUpdate(BaseModel):
    """Only Admin/PM can update prices"""
    price: Optional[float] = None
    cost_price: Optional[float] = None
    reason: Optional[str] = None
    
    @field_validator('price', 'cost_price')
    def validate_prices(cls, v):
        if v is not None and v <= 0:
            raise ValueError('Price must be positive')
        return v

# === RESPONSE FOR REGULAR STAFF (NO cost_price) ===
class ProductResponseForStaff(BaseModel):
    """Regular staff see selling price, NOT cost price"""
    id: UUID
    name: str
    sku: str
    barcode: str
    description: Optional[str]
    price: float  # Visible to staff
    category_id: UUID
    image_url: Optional[str]
    low_stock_threshold: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# === RESPONSE FOR ADMIN/FINANCE (WITH cost_price + margin) ===
class ProductResponseForAdmin(BaseModel):
    """Admin sees both selling price AND cost price"""
    id: UUID
    name: str
    sku: str
    barcode: str
    description: Optional[str]
    price: float
    cost_price: float  # Admin only
    margin_percentage: float  # Calculated
    category_id: UUID
    image_url: Optional[str]
    low_stock_threshold: int
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: Optional[UUID]
    last_price_change: Optional[datetime]
    last_price_changed_by: Optional[UUID]
    
    class Config:
        from_attributes = True

# === PRICE HISTORY RESPONSE ===
class PriceHistoryItem(BaseModel):
    """Single price change record"""
    change_date: datetime
    change_type: str
    old_price: Optional[float]
    new_price: float
    old_cost_price: Optional[float]
    new_cost_price: Optional[float]
    old_margin: Optional[float]
    new_margin: Optional[float]
    changed_by: str
    changed_by_role: str
    reason: Optional[str]
    effective_date: datetime

class PriceHistoryResponse(BaseModel):
    """Complete price history for a product"""
    product_id: UUID
    product_name: str
    sku: str
    current_price: float
    current_cost_price: float
    total_changes: int
    history: List[PriceHistoryItem]