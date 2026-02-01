from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from app.models.sale import PaymentMethod, SaleStatus


# ==========================================
# REQUEST SCHEMAS (What users send)
# ==========================================

class SaleItemCreate(BaseModel):
    """Item to be sold - sent by cashier"""
    product_id: UUID
    quantity: int = Field(..., gt=0, description="Must be greater than 0")


class SaleCreate(BaseModel):
    """Create a new sale transaction"""
    items: List[SaleItemCreate] = Field(..., min_length=1, description="Must have at least 1 item")
    payment_method: PaymentMethod
    discount: float = Field(default=0.0, ge=0, description="Discount amount (cannot be negative)")
    amount_paid: float = Field(..., gt=0, description="Amount customer paid")
    till_number: Optional[str] = None
    notes: Optional[str] = None


class SaleCancelRequest(BaseModel):
    """Cancel/void a sale"""
    cancellation_reason: str = Field(..., min_length=5, description="Must provide reason for cancellation")


# ==========================================
# RESPONSE SCHEMAS (What API returns)
# ==========================================

class SaleItemResponse(BaseModel):
    """Sale item details in response"""
    product_id: UUID
    product_name: str
    sku: str
    barcode: str
    quantity_sold: int
    unit_price: float
    line_total: float


class SaleResponse(BaseModel):
    """Complete sale details"""
    sale_id: UUID
    sale_number: str
    branch_id: UUID
    sold_by: UUID
    items: List[SaleItemResponse]
    subtotal: float
    tax: float
    discount: float
    total_amount: float
    payment_method: str
    amount_paid: float
    change_given: float
    status: str
    till_number: Optional[str]
    notes: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class SaleSummaryResponse(BaseModel):
    """Quick summary for lists"""
    sale_id: UUID
    sale_number: str
    total_amount: float
    items_count: int
    payment_method: str
    status: str
    created_at: datetime


class ProductInventoryResponse(BaseModel):
    """Product with inventory for sales staff"""
    product_id: UUID
    name: str
    sku: str
    barcode: str
    price: float
    category_name: str
    available_quantity: int  # At their branch
    image_url: Optional[str]
    
    class Config:
        from_attributes = True