import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from uuid import UUID
from datetime import datetime
from app.core.rate_limit import limiter
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole
from app.models.inventory import Inventory, AdjustmentLog
from app.models.system_settings import SystemSettings
from app.schemas.inventory import StockAdjustmentSchema
from app.models.branch import Branch
from app.models.product import Product
from app.utils.stock_alerts import check_and_send_stock_alerts  # ✅ UPDATED

router = APIRouter(tags=["Inventory Management"])
logger = logging.getLogger(__name__)


async def get_settings() -> SystemSettings:
    s = await SystemSettings.find_one({})
    return s if s else SystemSettings()


@router.post("/adjust", status_code=200)
@limiter.limit("10/minute")
async def adjust_stock(
    request: Request,
    data: StockAdjustmentSchema,
    current_user: User = Depends(get_current_user)
):
    """
    Adjust stock levels (remove stock for damage, theft, etc.)
    Only Store Managers can perform this action.
    Triggers two-tier stock alert emails after deduction.
    """
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Store Managers can adjust stock"
        )

    user_branch_id = current_user.branch_id
    if not user_branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no branch assigned"
        )

    inventory = await Inventory.find_one({
        "product_id": str(data.product_id),
        "branch_id": str(current_user.branch_id)
    })

    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in inventory for your branch"
        )

    if inventory.quantity < data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Available: {inventory.quantity}, Requested: {data.quantity}"
        )

    # Deduct stock
    inventory.quantity -= data.quantity
    inventory.updated_at = datetime.utcnow()
    await inventory.save()

    # Save adjustment log
    log = AdjustmentLog(
        branch_id=UUID(str(user_branch_id)),
        product_id=UUID(str(data.product_id)),
        user_id=current_user.user_id,
        quantity_removed=data.quantity,
        reason=data.reason,
        note=data.note,
        date=datetime.utcnow()
    )
    await log.save()

    # ✅ Two-tier stock alert check
    sys_settings = await get_settings()
    await check_and_send_stock_alerts(inventory, user_branch_id, sys_settings)

    return {
        "message": "Stock adjusted successfully",
        "product_id": str(data.product_id),
        "product_name": inventory.product_name,
        "quantity_removed": data.quantity,
        "new_quantity": inventory.quantity,
        "reason": data.reason,
        "low_stock_alert": inventory.quantity <= inventory.reorder_point,
        "critical_alert": inventory.quantity <= sys_settings.critical_stock_threshold,
    }


@router.get("/history/{branch_id}", response_model=list)
async def get_adjustment_history(
    branch_id: UUID,
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.STORE_MANAGER:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view adjustments for your assigned branch"
            )
    elif current_user.role not in [UserRole.ADMIN, UserRole.FINANCE]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    logs = await AdjustmentLog.find(
        AdjustmentLog.branch_id == branch_id
    ).sort(-AdjustmentLog.date).to_list()  # type: ignore

    return logs


@router.get("/{branch_id}/low-stock", response_model=dict)
async def get_low_stock_items(
    branch_id: str,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get paginated low-stock items for a specific branch."""
    if current_user.role in [UserRole.STORE_MANAGER, UserRole.STORE_STAFF]:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(status_code=403, detail="Access denied")

    query = {"branch_id": branch_id, "quantity": {"$lte": 10}}
    total = await Inventory.find(query).count()
    skip = (page - 1) * limit
    low_stock_items = await Inventory.find(query).skip(skip).limit(limit).to_list()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "data": low_stock_items
    }


@router.get("/{branch_id}", response_model=dict)
async def get_branch_inventory(
    branch_id: str,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """
    Get paginated inventory items for a specific branch.
    Store Managers, Store Staff, and Sales Staff can only view their own branch.
    """
    if current_user.role in [UserRole.STORE_MANAGER, UserRole.STORE_STAFF, UserRole.SALES_STAFF]:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=403,
                detail="You can only view inventory for your assigned branch"
            )

    total = await Inventory.find(Inventory.branch_id == branch_id).count()
    skip = (page - 1) * limit
    inventory_items = await Inventory.find(
        Inventory.branch_id == branch_id
    ).skip(skip).limit(limit).to_list()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "data": inventory_items
    }


@router.get("/adjustments/all", response_model=dict)
async def get_all_adjustment_logs(
    branch_id: UUID = None,
    reason: str = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Admin and Finance only. All stock adjustment logs across branches."""
    if current_user.role not in [UserRole.ADMIN, UserRole.FINANCE]:
        raise HTTPException(status_code=403, detail="Access Denied: Admin and Finance only")

    query_filter = {}
    if branch_id:
        query_filter["branch_id"] = branch_id
    if reason:
        query_filter["reason"] = reason

    skip = (page - 1) * limit
    total = await AdjustmentLog.find(query_filter).count()
    logs = await AdjustmentLog.find(query_filter).sort(
        -AdjustmentLog.date
    ).skip(skip).limit(limit).to_list()

    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    result = []
    for log in logs:
        product = await Product.get(log.product_id)
        user = await User.find_one(User.user_id == log.user_id)
        result.append({
            "id": str(log.id),
            "branch": branch_map.get(str(log.branch_id), "Unknown"),
            "product_id": str(log.product_id),
            "product_name": product.name if product else "Unknown",
            "quantity_removed": log.quantity_removed,
            "reason": log.reason,
            "note": log.note,
            "adjusted_by": f"{user.first_name} {user.last_name}" if user else "Unknown",
            "adjusted_by_role": user.role.value if user else "Unknown",
            "date": log.date
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "data": result
    }