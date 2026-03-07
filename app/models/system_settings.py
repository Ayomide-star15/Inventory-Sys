from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime


class SystemSettings(Document):
    """
    Global system configuration.
    Admin can change these without touching code.
    Only ONE document should exist in this collection.
    """
    id: UUID = Field(default_factory=uuid4)

    # === FINANCIAL SETTINGS ===
    vat_rate: float = 0.075                  # 7.5% VAT — was hardcoded in sale.py
    po_approval_threshold: float = 5000.0    # POs above this need Finance approval
    currency_symbol: str = "₦"
    currency_code: str = "NGN"

    # === INVENTORY SETTINGS ===
    default_low_stock_threshold: int = 10    # Default reorder point for new products
    critical_stock_threshold: int = 5        # Below this = CRITICAL alert

    # === SYSTEM SETTINGS ===
    timezone: str = "Africa/Lagos"
    system_name: str = "Multi-Branch Supermarket System"
    max_discount_percentage: float = 20.0    # Sales staff can't give more than 20% off
    
    # === SALE SETTINGS ===
    allow_negative_stock: bool = False       # Can sales go below 0?
    require_till_number: bool = False        # Must cashier enter till number?

    # === METADATA ===
    last_updated_by: Optional[UUID] = None
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "system_settings"


# Default settings — used when no settings doc exists yet
DEFAULT_SETTINGS = {
    "vat_rate": 0.075,
    "po_approval_threshold": 5000.0,
    "currency_symbol": "₦",
    "currency_code": "NGN",
    "default_low_stock_threshold": 10,
    "critical_stock_threshold": 5,
    "timezone": "Africa/Lagos",
    "max_discount_percentage": 20.0,
    "allow_negative_stock": False,
    "require_till_number": False
}