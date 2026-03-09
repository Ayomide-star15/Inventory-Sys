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
    items: List[SaleItemCreate] = Field(..., min_length=1)
    payment_method: PaymentMethod
    till_number: Optional[str] = None
    notes: Optional[str] = None


class SaleCancelRequest(BaseModel):
    """Cancel/void a sale"""
    cancellation_reason: str = Field(..., min_length=5)


# ==========================================
# QUOTE SCHEMAS (new)
# ==========================================

class QuoteItemInput(BaseModel):
    """Single item in a quote request"""
    product_id: UUID
    quantity: int = Field(..., gt=0)


class QuoteRequest(BaseModel):
    """
    What the frontend sends to get a price preview.
    No sale is created. Safe to call as many times as needed.
    """
    items: List[QuoteItemInput] = Field(..., min_length=1)
    discount: float = Field(default=0.0, ge=0)


class QuoteItemResponse(BaseModel):
    """One item in the quote response"""
    product_id: str
    product_name: str
    sku: str
    quantity: int
    unit_price: float
    line_total: float
    available_quantity: int  # so frontend can show stock warning


class QuoteResponse(BaseModel):
    """
    Full price breakdown returned to the cashier screen.
    Frontend displays this — staff never calculates anything.
    """
    items: List[QuoteItemResponse]
    subtotal: float
    discount: float
    discounted_subtotal: float
    tax: float
    tax_rate: str               # e.g. "7.5%" — display on receipt
    total_amount: float
    currency_symbol: str
    items_count: int
    payment_methods: List[str]  # dropdown options for frontend


# ==========================================
# RESPONSE SCHEMAS
# ==========================================

class SaleItemResponse(BaseModel):
    product_id: UUID
    product_name: str
    sku: str
    barcode: str
    quantity_sold: int
    unit_price: float
    line_total: float


class SaleResponse(BaseModel):
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
    sale_id: UUID
    sale_number: str
    total_amount: float
    items_count: int
    payment_method: str
    status: str
    created_at: datetime


class ProductInventoryResponse(BaseModel):
    product_id: UUID
    name: str
    sku: str
    barcode: str
    price: float
    category_name: str
    available_quantity: int
    image_url: Optional[str]

    class Config:
        from_attributes = True