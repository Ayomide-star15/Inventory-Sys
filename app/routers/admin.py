from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.models.user import User, UserRole
from app.models.branch import Branch
from app.models.sale import Sale, SaleStatus
from app.models.inventory import Inventory
from app.models.purchase_order import PurchaseOrder, POStatus
from app.models.stock_transfer import StockTransfer, TransferStatus
from app.models.audit_log import AuditLog, AuditAction, AuditModule
from app.models.system_settings import SystemSettings
from app.dependencies.auth import get_admin_user, get_current_active_user
from app.utils.audit import log_action
from app.utils.security import extract_ip

router = APIRouter(prefix="/admin", tags=["Admin"])


# ==========================================
# SCHEMAS
# ==========================================

class SystemSettingsUpdate(BaseModel):
    vat_rate: Optional[float] = None
    po_approval_threshold: Optional[float] = None
    currency_symbol: Optional[str] = None
    default_low_stock_threshold: Optional[int] = None
    critical_stock_threshold: Optional[int] = None
    max_discount_percentage: Optional[float] = None
    allow_negative_stock: Optional[bool] = None
    require_till_number: Optional[bool] = None
    system_name: Optional[str] = None


# ==========================================
# 1. ADMIN DASHBOARD
# ==========================================

@router.get("/dashboard", response_model=dict)
async def get_admin_dashboard(
    admin: User = Depends(get_admin_user)
):
    """
    Complete system-wide overview for Admin.
    
    Returns:
    - System health (branches, staff, active users)
    - Revenue summary (today, week, month)
    - Underperforming branches
    - Critical stock alerts
    - User activity (who hasn't logged in 30 days)
    - Pending actions requiring attention
    """

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    # ─── SYSTEM HEALTH ───────────────────────────────────────
    all_branches = await Branch.find_all().to_list()
    all_users = await User.find_all().to_list()

    total_branches = len(all_branches)
    active_branches = len([b for b in all_branches if b.is_active])
    total_staff = len(all_users)
    active_users = len([u for u in all_users if u.is_active])
    inactive_users = total_staff - active_users

    # ─── REVENUE ─────────────────────────────────────────────
    today_sales = await Sale.find({
        "created_at": {"$gte": today_start},
        "status": SaleStatus.COMPLETED
    }).to_list()

    week_sales = await Sale.find({
        "created_at": {"$gte": week_start},
        "status": SaleStatus.COMPLETED
    }).to_list()

    month_sales = await Sale.find({
        "created_at": {"$gte": month_start},
        "status": SaleStatus.COMPLETED
    }).to_list()

    today_revenue = sum(s.total_amount for s in today_sales)
    week_revenue = sum(s.total_amount for s in week_sales)
    month_revenue = sum(s.total_amount for s in month_sales)

    # ─── BRANCH PERFORMANCE ──────────────────────────────────
    branch_revenue = {}
    for sale in month_sales:
        bid = str(sale.branch_id)
        branch_revenue[bid] = branch_revenue.get(bid, 0) + sale.total_amount

    branch_performance = []
    for branch in all_branches:
        if not branch.is_active:
            continue
        revenue = branch_revenue.get(str(branch.id), 0)
        branch_performance.append({
            "branch_id": str(branch.id),
            "branch_name": branch.name,
            "monthly_revenue": round(revenue, 2)
        })

    branch_performance.sort(key=lambda x: x["monthly_revenue"], reverse=True)

    avg_revenue = (
        sum(b["monthly_revenue"] for b in branch_performance) / len(branch_performance)
        if branch_performance else 0
    )

    underperforming = [
        b for b in branch_performance
        if b["monthly_revenue"] < (avg_revenue * 0.5)  # Below 50% of average
    ]

    top_branch = branch_performance[0] if branch_performance else None

    # ─── CRITICAL STOCK ALERTS ───────────────────────────────
    sys_settings = await SystemSettings.find_one({}) or SystemSettings()
    critical_threshold = sys_settings.critical_stock_threshold

    critical_stock_branches = []
    for branch in all_branches:
        if not branch.is_active:
            continue
        branch_str = str(branch.id)
        out_of_stock = await Inventory.find({
            "branch_id": branch_str,
            "quantity": 0
        }).count()
        critical_stock = await Inventory.find({
            "branch_id": branch_str,
            "quantity": {"$gt": 0, "$lte": critical_threshold}
        }).count()

        if out_of_stock > 0 or critical_stock > 0:
            critical_stock_branches.append({
                "branch_id": branch_str,
                "branch_name": branch.name,
                "out_of_stock_count": out_of_stock,
                "critical_stock_count": critical_stock
            })

    # ─── USER ACTIVITY ────────────────────────────────────────
    users_not_logged_in = []
    recent_logins = []

    for u in all_users:
        if not u.is_active:
            continue
        if u.last_login is None or u.last_login < thirty_days_ago:
            users_not_logged_in.append({
                "user_id": str(u.user_id),
                "name": f"{u.first_name} {u.last_name}",
                "email": u.email,
                "role": u.role.value,
                "last_login": u.last_login.isoformat() if u.last_login else "Never"
            })
        else:
            recent_logins.append({
                "name": f"{u.first_name} {u.last_name}",
                "role": u.role.value,
                "last_login": u.last_login.isoformat() if u.last_login else None
            })

    recent_logins.sort(
        key=lambda x: x["last_login"] or "",
        reverse=True
    )

    # ─── PENDING ACTIONS ─────────────────────────────────────
    pending_po_approvals = await PurchaseOrder.find(
        PurchaseOrder.status == POStatus.PENDING_APPROVAL
    ).count()

    pending_transfers = await StockTransfer.find(
        StockTransfer.status == TransferStatus.PENDING
    ).count()

    return {
        # System Health
        "system_health": {
            "total_branches": total_branches,
            "active_branches": active_branches,
            "inactive_branches": total_branches - active_branches,
            "total_staff": total_staff,
            "active_users": active_users,
            "inactive_users": inactive_users
        },

        # Revenue
        "revenue": {
            "today": round(today_revenue, 2),
            "this_week": round(week_revenue, 2),
            "this_month": round(month_revenue, 2),
            "today_transactions": len(today_sales),
            "month_transactions": len(month_sales)
        },

        # Branch Performance
        "branch_performance": {
            "top_branch": top_branch,
            "average_monthly_revenue": round(avg_revenue, 2),
            "all_branches": branch_performance,
            "underperforming_branches": underperforming
        },

        # Stock Alerts
        "stock_alerts": {
            "branches_with_critical_stock": len(critical_stock_branches),
            "details": critical_stock_branches
        },

        # User Activity
        "user_activity": {
            "not_logged_in_30_days": users_not_logged_in,
            "recent_logins": recent_logins[:10]
        },

        # Pending Actions
        "pending_actions": {
            "po_approvals_needed": pending_po_approvals,
            "transfers_pending": pending_transfers
        }
    }


# ==========================================
# 2. AUDIT LOGS
# ==========================================

@router.get("/audit-logs", response_model=List[dict])
async def get_audit_logs(
    user_id: Optional[UUID] = None,
    module: Optional[AuditModule] = None,
    action: Optional[AuditAction] = None,
    branch_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=200),
    admin: User = Depends(get_admin_user)
):
    """
    Query audit logs with filters.
    
    Examples:
    - ?user_id=xxx              → What did this person do?
    - ?module=sales             → All sales actions
    - ?action=LOGIN_FAILED      → Security: failed logins
    - ?branch_id=xxx            → Everything at this branch
    - ?start_date=...&end_date  → Date range
    """

    query = {}

    if user_id:
        query["user_id"] = user_id
    if module:
        query["module"] = module
    if action:
        query["action"] = action
    if branch_id:
        query["branch_id"] = branch_id
    if start_date:
        query["timestamp"] = {"$gte": start_date}
    if end_date:
        query.setdefault("timestamp", {})["$lte"] = end_date

    skip = (page - 1) * limit
    logs = await AuditLog.find(query).sort(-AuditLog.timestamp).skip(skip).limit(limit).to_list()  # type: ignore

    return [
        {
            "id": str(log.id),
            "user_name": log.user_name,
            "user_role": log.user_role,
            "user_email": log.user_email,
            "branch_name": log.branch_name,
            "action": log.action,
            "module": log.module,
            "description": log.description,
            "target_id": log.target_id,
            "target_type": log.target_type,
            "metadata": log.metadata,
            "timestamp": log.timestamp,
            "ip_address": log.ip_address
        }
        for log in logs
    ]


@router.get("/audit-logs/user/{user_id}", response_model=List[dict])
async def get_user_audit_trail(
    user_id: UUID,
    page: int = 1,
    limit: int = 50,
    admin: User = Depends(get_admin_user)
):
    """Get complete action history for a specific user."""

    user = await User.find_one(User.user_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    skip = (page - 1) * limit
    logs = await AuditLog.find(
        AuditLog.user_id == user_id
    ).sort(-AuditLog.timestamp).skip(skip).limit(limit).to_list()  # type: ignore

    return {
        "user": {
            "name": f"{user.first_name} {user.last_name}",
            "email": user.email,
            "role": user.role.value
        },
        "total_actions": len(logs),
        "logs": [
            {
                "action": log.action,
                "module": log.module,
                "description": log.description,
                "timestamp": log.timestamp,
                "ip_address": log.ip_address,
                "metadata": log.metadata
            }
            for log in logs
        ]
    }


@router.get("/audit-logs/security/failed-logins", response_model=dict)
async def get_failed_logins(
    hours: int = 24,
    admin: User = Depends(get_admin_user)
):
    """
    Security report: Failed login attempts in last N hours.
    Useful for detecting brute-force attacks.
    """

    since = datetime.utcnow() - timedelta(hours=hours)

    logs = await AuditLog.find({
        "action": AuditAction.LOGIN_FAILED,
        "timestamp": {"$gte": since}
    }).sort(-AuditLog.timestamp).to_list()  # type: ignore

    # Group by email
    by_email = {}
    for log in logs:
        email = log.user_email
        if email not in by_email:
            by_email[email] = {"count": 0, "ips": set(), "last_attempt": None}
        by_email[email]["count"] += 1
        if log.ip_address:
            by_email[email]["ips"].add(log.ip_address)
        if not by_email[email]["last_attempt"] or log.timestamp > by_email[email]["last_attempt"]:
            by_email[email]["last_attempt"] = log.timestamp

    suspicious = [
        {
            "email": email,
            "attempts": data["count"],
            "unique_ips": list(data["ips"]),
            "last_attempt": data["last_attempt"]
        }
        for email, data in by_email.items()
        if data["count"] >= 3  # 3+ failures = suspicious
    ]
    suspicious.sort(key=lambda x: x["attempts"], reverse=True)

    return {
        "period_hours": hours,
        "total_failed_attempts": len(logs),
        "suspicious_accounts": suspicious
    }


# ==========================================
# 3. SYSTEM SETTINGS
# ==========================================

@router.get("/settings", response_model=dict)
async def get_system_settings(admin: User = Depends(get_admin_user)):
    """View current system settings."""
    settings = await SystemSettings.find_one({})
    if not settings:
        settings = SystemSettings()
        await settings.insert()

    return {
        "vat_rate": settings.vat_rate,
        "vat_percentage": f"{settings.vat_rate * 100:.1f}%",
        "po_approval_threshold": settings.po_approval_threshold,
        "currency_symbol": settings.currency_symbol,
        "currency_code": settings.currency_code,
        "default_low_stock_threshold": settings.default_low_stock_threshold,
        "critical_stock_threshold": settings.critical_stock_threshold,
        "max_discount_percentage": settings.max_discount_percentage,
        "allow_negative_stock": settings.allow_negative_stock,
        "require_till_number": settings.require_till_number,
        "system_name": settings.system_name,
        "timezone": settings.timezone,
        "last_updated_at": settings.last_updated_at,
        "last_updated_by": str(settings.last_updated_by) if settings.last_updated_by else None
    }


@router.put("/settings", response_model=dict)
async def update_system_settings(
    update_data: SystemSettingsUpdate,
    request: Request,
    admin: User = Depends(get_admin_user)
):
    """
    Update system settings.
    
    Changes take effect immediately across the entire system.
    Example: Changing vat_rate will affect all future sales instantly.
    """

    settings = await SystemSettings.find_one({})
    if not settings:
        settings = SystemSettings()
        await settings.insert()

    changes = {}
    old_values = {}

    update_dict = update_data.dict(exclude_unset=True)
    for key, value in update_dict.items():
        old_val = getattr(settings, key, None)
        if old_val != value:
            old_values[key] = old_val
            changes[key] = value
            setattr(settings, key, value)

    if not changes:
        return {"message": "No changes made", "settings": update_dict}

    settings.last_updated_by = admin.user_id
    settings.last_updated_at = datetime.utcnow()
    await settings.save()

    await log_action(
        user=admin,
        action=AuditAction.SETTINGS_UPDATED,
        module=AuditModule.SYSTEM,
        description=f"Admin updated system settings: {', '.join(changes.keys())}",
        metadata={"changes": changes, "previous": old_values},
        ip_address=extract_ip(request)
    )

    return {
        "message": "System settings updated successfully",
        "changes_applied": changes,
        "effective_immediately": True
    }


# ==========================================
# 4. INVENTORY OVERSIGHT
# ==========================================

@router.get("/inventory/overview", response_model=dict)
async def get_inventory_overview(admin: User = Depends(get_admin_user)):
    """
    System-wide inventory overview.
    Total stock value, out of stock items, low stock items across all branches.
    """

    all_inventory = await Inventory.find_all().to_list()
    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    sys_settings = await SystemSettings.find_one({}) or SystemSettings()

    total_units = sum(i.quantity for i in all_inventory)
    total_value = sum(i.quantity * i.selling_price for i in all_inventory)
    out_of_stock = [i for i in all_inventory if i.quantity == 0]
    low_stock = [i for i in all_inventory if 0 < i.quantity <= i.reorder_point]
    critical_stock = [i for i in all_inventory if 0 < i.quantity <= sys_settings.critical_stock_threshold]

    # Dead stock: items that haven't been sold recently
    # (simplified: quantity > 50 and updated_at more than 30 days ago)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    dead_stock = [
        i for i in all_inventory
        if i.quantity > 0 and i.updated_at and i.updated_at < thirty_days_ago
    ]

    return {
        "summary": {
            "total_products_tracked": len(all_inventory),
            "total_units_in_stock": total_units,
            "total_stock_value": round(total_value, 2),
            "out_of_stock_count": len(out_of_stock),
            "low_stock_count": len(low_stock),
            "critical_stock_count": len(critical_stock),
            "dead_stock_count": len(dead_stock)
        },
        "out_of_stock": [
            {
                "product_name": i.product_name,
                "product_id": i.product_id,
                "branch": branch_map.get(i.branch_id, "Unknown")
            }
            for i in out_of_stock[:20]
        ],
        "critical_stock": [
            {
                "product_name": i.product_name,
                "quantity": i.quantity,
                "branch": branch_map.get(i.branch_id, "Unknown")
            }
            for i in critical_stock[:20]
        ],
        "dead_stock": [
            {
                "product_name": i.product_name,
                "quantity": i.quantity,
                "value": round(i.quantity * i.selling_price, 2),
                "branch": branch_map.get(i.branch_id, "Unknown"),
                "last_updated": i.updated_at
            }
            for i in dead_stock[:20]
        ]
    }


@router.get("/inventory/product/{product_id}/all-branches", response_model=dict)
async def get_product_across_branches(
    product_id: UUID,
    admin: User = Depends(get_admin_user)
):
    """
    See how much of a product exists across all branches.
    Useful when deciding where to transfer stock from.
    """

    inventory_records = await Inventory.find({
        "product_id": str(product_id)
    }).to_list()

    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    return {
        "product_id": str(product_id),
        "total_units_system_wide": sum(i.quantity for i in inventory_records),
        "branches": [
            {
                "branch_name": branch_map.get(i.branch_id, "Unknown"),
                "branch_id": i.branch_id,
                "quantity": i.quantity,
                "selling_price": i.selling_price,
                "reorder_point": i.reorder_point,
                "status": "Out of Stock" if i.quantity == 0
                else "Low Stock" if i.quantity <= i.reorder_point
                else "In Stock"
            }
            for i in inventory_records
        ]
    }


# ==========================================
# 5. BRANCH PERFORMANCE
# ==========================================

@router.get("/branches/performance", response_model=dict)
async def get_branch_performance(
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(get_admin_user)
):
    """
    Side-by-side branch performance comparison.
    Revenue, sales count, staff count, stock value.
    """

    since = datetime.utcnow() - timedelta(days=days)
    branches = await Branch.find(Branch.is_active == True).to_list()

    result = []
    for branch in branches:
        # Sales in period
        branch_sales = await Sale.find({
            "branch_id": branch.id,
            "created_at": {"$gte": since},
            "status": SaleStatus.COMPLETED
        }).to_list()

        revenue = sum(s.total_amount for s in branch_sales)
        cancelled = await Sale.find({
            "branch_id": branch.id,
            "created_at": {"$gte": since},
            "status": SaleStatus.CANCELLED
        }).count()

        # Staff count
        staff_count = await User.find(User.branch_id == branch.id).count()

        # Inventory value
        inventory = await Inventory.find({"branch_id": str(branch.id)}).to_list()
        stock_value = sum(i.quantity * i.selling_price for i in inventory)
        out_of_stock = len([i for i in inventory if i.quantity == 0])

        result.append({
            "branch_id": str(branch.id),
            "branch_name": branch.name,
            "branch_code": branch.code,
            "revenue": round(revenue, 2),
            "total_sales": len(branch_sales),
            "cancelled_sales": cancelled,
            "staff_count": staff_count,
            "stock_value": round(stock_value, 2),
            "out_of_stock_items": out_of_stock,
            "avg_sale_value": round(revenue / len(branch_sales), 2) if branch_sales else 0
        })

    result.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "period_days": days,
        "branches": result,
        "system_total_revenue": round(sum(b["revenue"] for b in result), 2),
        "system_total_sales": sum(b["total_sales"] for b in result)
    }


# ==========================================
# 6. USER MANAGEMENT EXTRAS
# ==========================================

@router.get("/users/inactive", response_model=List[dict])
async def get_inactive_users(
    days: int = 30,
    admin: User = Depends(get_admin_user)
):
    """Users who haven't logged in for N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    users = await User.find(User.is_active == True).to_list()

    inactive = [
        u for u in users
        if u.last_login is None or u.last_login < cutoff
    ]

    branches = await Branch.find_all().to_list()
    branch_map = {b.id: b.name for b in branches}

    return [
        {
            "user_id": str(u.user_id),
            "name": f"{u.first_name} {u.last_name}",
            "email": u.email,
            "role": u.role.value,
            "branch": branch_map.get(u.branch_id, "HQ") if u.branch_id else "HQ",
            "last_login": u.last_login.isoformat() if u.last_login else "Never",
            "days_inactive": (datetime.utcnow() - u.last_login).days if u.last_login else None
        }
        for u in inactive
    ]

@router.get("/roles", response_model=list)
async def get_roles(
    admin: User = Depends(get_admin_user)
):
    """
    Returns all available user roles in the system.
    Admin only.
    """
    return [role.value for role in UserRole]