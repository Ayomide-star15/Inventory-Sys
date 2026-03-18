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
from app.core.email import send_low_stock_alert_email  # ✅ NEW

router = APIRouter(tags=["Inventory Management"])
logger = logging.getLogger(__name__)  # ✅ NEW


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
    Triggers low stock email to Store Manager + Purchase Managers
    if stock drops to or below critical threshold.
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

    # ✅ Check critical stock and notify Store Manager + Purchase Managers
    sys_settings = await get_settings()
    is_critical = inventory.quantity <= sys_settings.critical_stock_threshold

    if is_critical:
        try:
            branch = await Branch.get(user_branch_id)
            branch_name = branch.name if branch else "Unknown"

            # Notify Store Manager of this branch
            store_managers = await User.find(
                User.role == UserRole.STORE_MANAGER,
                User.branch_id == user_branch_id,
                User.is_active == True
            ).to_list()

            for manager in store_managers:
                await send_low_stock_alert_email(
                    email_to=manager.email,
                    first_name=manager.first_name,
                    product_name=inventory.product_name,
                    branch_name=branch_name,
                    quantity=inventory.quantity,
                    role="Store Manager"
                )
                logger.info(
                    f"Low stock alert sent to Store Manager "
                    f"{manager.email} for {inventory.product_name} "
                    f"at {branch_name} ({inventory.quantity} units left)"
                )

            # Notify ALL Purchase Managers system-wide
            purchase_managers = await User.find(
                User.role == UserRole.PURCHASE,
                User.is_active == True
            ).to_list()

            for pm in purchase_managers:
                await send_low_stock_alert_email(
                    email_to=pm.email,
                    first_name=pm.first_name,
                    product_name=inventory.product_name,
                    branch_name=branch_name,
                    quantity=inventory.quantity,
                    role="Purchase Manager"
                )
                logger.info(
                    f"Low stock alert sent to Purchase Manager "
                    f"{pm.email} for {inventory.product_name} "
                    f"at {branch_name} ({inventory.quantity} units left)"
                )

        except Exception as e:
            logger.error(
                f"Low stock alert email failed after adjustment "
                f"for {inventory.product_name}: {e}"
            )

    return {
        "message": "Stock adjusted successfully",
        "product_id": str(data.product_id),
        "product_name": inventory.product_name,
        "quantity_removed": data.quantity,
        "new_quantity": inventory.quantity,
        "reason": data.reason,
        "low_stock_alert": is_critical,
        "alert_message": (
            f"CRITICAL: Only {inventory.quantity} unit(s) remaining. "
            f"Store Manager and Purchase Managers have been notified."
        ) if is_critical else None
    }

@router.get("/history/{branch_id}", response_model=list)
async def get_adjustment_history(
    branch_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Get adjustment history for a specific branch.
    Store Managers can only view their own branch. Admins and Finance Managers can view all branches.
    """

    #FIXED: Use UserRole enum constants throughout
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
            raise HTTPException(status_code=403, detail="You can only view inventory for your assigned branch")

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

# ==========================================
# GET ADJUSTMENT HISTORY - Single Branch
# (Fixed: now has proper role checks)
# ==========================================
@router.get("/history/{branch_id}", response_model=list)
async def get_adjustment_history(
    branch_id: UUID,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    # Admin and Finance can view any branch
    if current_user.role in [UserRole.ADMIN, UserRole.FINANCE]:
        pass
    # Store Manager can only view their own branch
    elif current_user.role == UserRole.STORE_MANAGER:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(status_code=403, detail="You can only view your own branch adjustment logs")
    else:
        raise HTTPException(status_code=403, detail="Access Denied")

    skip = (page - 1) * limit
    logs = await AdjustmentLog.find(
        AdjustmentLog.branch_id == branch_id
    ).sort(-AdjustmentLog.date).skip(skip).limit(limit).to_list()

    result = []
    for log in logs:
        product = await Product.get(log.product_id)
        user = await User.find_one(User.user_id == log.user_id)
        result.append({
            "id": str(log.id),
            "product_id": str(log.product_id),
            "product_name": product.name if product else "Unknown",
            "quantity_removed": log.quantity_removed,
            "reason": log.reason,
            "note": log.note,
            "adjusted_by": f"{user.first_name} {user.last_name}" if user else "Unknown",
            "date": log.date
        })

    return result


# ==========================================
# GET ALL ADJUSTMENT LOGS - All Branches
# (New: Admin and Finance only)
# ==========================================
@router.get("/adjustments/all", response_model=dict)
async def get_all_adjustment_logs(
    branch_id: UUID = None,   # optional filter by branch
    reason: str = None,       # optional filter by reason e.g. "theft"
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Admin and Finance only.** Retrieves all stock adjustment logs across branches with optional filtering by branch and reason. Provides pagination support. This endpoint is intended for high-level oversight and auditing of stock adjustments across the entire organization."""
    if current_user.role not in [UserRole.ADMIN, UserRole.FINANCE]:
        raise HTTPException(status_code=403, detail="Access Denied: Admin and Finance only")

    query_filter = {}
    if branch_id:
        query_filter["branch_id"] = branch_id
    if reason:
        query_filter["reason"] = reason

    skip = (page - 1) * limit
    total = await AdjustmentLog.find(query_filter).count()
    logs = await AdjustmentLog.find(query_filter).sort(-AdjustmentLog.date).skip(skip).limit(limit).to_list()

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
