from pydantic import BaseModel, Field
from typing import List, Literal, Optional

# --- 1. ADJUSTMENT SCHEMA (For the "Trash Can" / Damage Control) ---
# Used by: POST /inventory/adjust
class StockAdjustmentSchema(BaseModel):
    product_id: str
    quantity: int = Field(..., gt=0, description="Amount to remove. Must be positive.")
    reason: Literal["damaged", "expired", "theft", "internal_use", "other"]
    note: Optional[str] = None