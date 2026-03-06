from typing import Optional
from beanie import Document
from pydantic import Field
from uuid import UUID, uuid4
from datetime import datetime


class Inventory(Document):
    """
    Tracks how much of a product exists at a SPECIFIC branch.
    
    IMPORTANT: product_id and branch_id are stored as STRINGS
    for consistent querying across all routers.
    """
    id: UUID = Field(default_factory=uuid4)

    # ✅ FIXED: Stored as str (not UUID) so find_one() queries using str(...) always match
    product_id: str = Field(..., description="ID of the product (string)")
    branch_id: str = Field(..., description="ID of the branch (string)")

    quantity: int = 0
    reorder_point: int = 10
    bin_location: Optional[str] = None  # e.g., "Aisle 4, Shelf B"

    # ✅ Selling price — automatically copied from Product.price when goods arrive
    # This is what Sales Staff use at checkout. Never read Product.price directly.
    selling_price: float = 0.0

    product_name: str = "Unknown Product"
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "inventory"
        indexes = [
            [("product_id", 1), ("branch_id", 1)]
        ]


class AdjustmentLog(Document):
    """
    Keeps a history of why stock was changed (Theft, Damage, etc.)
    """
    branch_id: UUID
    product_id: UUID
    user_id: UUID
    quantity_removed: int
    reason: str
    note: Optional[str] = None
    date: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "adjustment_logs"