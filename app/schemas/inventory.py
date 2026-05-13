from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import UUID


class StockAdjustmentSchema(BaseModel):
    """
    Request body for POST /inventory/adjust.

    Fields
    ------
    product_id  : The product whose stock is being reduced.
    quantity    : How many units to remove. Must be a positive integer.
    reason      : One of the accepted loss-reason codes.
    note        : Optional free-text detail (e.g. "3 boxes crushed on arrival").
    branch_id   : **Required for Admin only.**  Admin accounts have no assigned
                  branch, so they must explicitly state which branch to adjust.
                  Store Managers leave this blank — their branch is read from
                  their account automatically.
    """

    product_id: str
    quantity: int = Field(..., gt=0, description="Units to remove. Must be greater than zero.")
    reason: Literal["damaged", "expired", "theft", "internal_use", "other"]
    note: Optional[str] = Field(default=None, description="Optional detail about the loss.")
    branch_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Target branch UUID. Required when the caller is an Admin. "
            "Store Managers omit this — their own branch is used automatically."
        ),
    )