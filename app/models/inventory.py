from typing import Optional, Annotated
from beanie import Document, Indexed
from pydantic import Field
from uuid import UUID, uuid4
from datetime import datetime

class Inventory(Document):
    """
    Tracks how much of a product exists at a SPECIFIC branch.
    """
    id: UUID = Field(default_factory=uuid4, alias="_id")

    # --- FIX 1: Use Annotated + Indexed() for querying ---
    product_id: Annotated[UUID, Indexed()] 
    
    # --- FIX 2: Renamed 'branch_name' to 'branch_id' to match your Router ---
    branch_id: Annotated[UUID, Indexed()] 

    quantity: int = 0
    reorder_point: int = 10 
    bin_location: Optional[str] = None # e.g., "Aisle 4, Shelf B"
    
    product_name: str = "Unknown Product" # Added to store the name snapshot
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "inventory"
        # Unique Constraint: A product can only appear once per branch
        indexes = [
            [("product_id", 1), ("branch_id", 1)]
        ]