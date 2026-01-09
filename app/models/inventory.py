from typing import Optional
from beanie import Document, PydanticObjectId, Indexed
from uuid import UUID, uuid4

class Inventory(Document):
    """
    Tracks how much of a product exists at a SPECIFIC branch.
    """
    product_id: UUID
    branch_name: UUID    # e.g., "Lekki", "Ikeja"

    quantity: int = 0
    reorder_point: int = 10 
    bin_location: Optional[str] = None # e.g., "Aisle 4, Shelf B"

    class Settings:
        name = "inventory"
        # Unique Constraint: A product can only appear once per branch
        indexes = [
            [("product_id", 1), ("branch_name", 1)]
        ]