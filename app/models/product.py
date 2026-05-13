## app/models/product.py

from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime


class Product(Document):
    """
    GLOBAL PRODUCT MODEL

    Price is optional at creation — Admin creates the catalog entry,
    Finance Manager sets the selling price after the first PO is received.
    Cost price lives on each Purchase Order, not on the product.
    """
    id: UUID = Field(default_factory=uuid4)

    # === IDENTIFICATION ===
    name: str = Field(..., unique=True)     # type: ignore
    sku: str = Field(..., unique=True)      # type: ignore
    barcode: str = Field(..., unique=True)  # type: ignore
    description: Optional[str] = None

    # === PRICING ===
    # price is None until Finance Manager sets it
    # cost_price is stored here as a reference from the latest PO
    # it is updated each time Finance Manager approves a PO and sets a new price
    price: Optional[float] = None
    cost_price: Optional[float] = None      # reference only — actual cost is on Purchase Order

    # === STOCK MANAGEMENT ===
    low_stock_threshold: int = Field(default=10)

    # === CATEGORY ===
    category_id: UUID
    image_url: Optional[str] = None

    # === PRICING METADATA ===
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
        ]