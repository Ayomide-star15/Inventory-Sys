
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from datetime import datetime

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.inventory import Inventory, AdjustmentLog
from app.schemas.inventory import StockAdjustmentSchema

router = APIRouter(tags=["Inventory Management"])

@router.post("/adjust", status_code=200)
async def adjust_stock(
    data: StockAdjustmentSchema,
    current_user: User = Depends(get_current_user)
):
    """
    Adjust stock levels (remove stock for damage, theft, etc.)
    Only Store Managers can perform this action.
    """
    
    # 1. Role Check
    if current_user.role != "Store Manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Store Managers can adjust stock"
        )
    
    # 2. Get user's branch
    user_branch_id = current_user.branch_id
    if not user_branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no branch assigned"
        )
    
    # 3. Convert IDs to strings for consistent comparison
    user_branch_str = str(user_branch_id)
    product_id_str = str(data.product_id)
    
    # 4. Find inventory record for this product at this branch
    inventory = await Inventory.find_one({
        "product_id": product_id_str,
        "branch_id": user_branch_str
    })
    
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product not found in inventory for your branch"
        )
    
    # 5. Check sufficient stock
    if inventory.quantity < data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Available: {inventory.quantity}, Requested: {data.quantity}"
        )
    
    # 6. Update inventory
    inventory.quantity -= data.quantity
    inventory.updated_at = datetime.utcnow()
    await inventory.save()
    
    # 7. Create adjustment log
    log = AdjustmentLog(
        branch_id=UUID(user_branch_str),
        product_id=UUID(product_id_str),
        user_id=current_user.user_id,
        quantity_removed=data.quantity,
        reason=data.reason,
        note=data.note,
        date=datetime.utcnow()
    )
    await log.save()
    
    return {
        "message": "Stock adjusted successfully",
        "product_id": product_id_str,
        "quantity_removed": data.quantity,
        "new_quantity": inventory.quantity,
        "reason": data.reason
    }


@router.get("/history/{branch_id}", response_model=list)
async def get_adjustment_history(
    branch_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Get adjustment history for a specific branch.
    Store Managers can only see their own branch.
    Admins can see any branch.
    """
    
    # Role-based access control
    if current_user.role == "Store Manager":
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view adjustments for your assigned branch"
            )
    elif current_user.role not in ["System Administrator", "Finance Manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Fetch adjustment logs
    logs = await AdjustmentLog.find(
        AdjustmentLog.branch_id == branch_id
    ).sort(-AdjustmentLog.date).to_list()
    
    return logs