from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta
from uuid import UUID

from app.models.user import User, UserRole
from app.models.sale import Sale, SaleStatus
from app.models.inventory import Inventory
from app.models.purchase_order import PurchaseOrder, POStatus
from app.models.stock_transfer import StockTransfer, TransferStatus
from app.models.branch import Branch
from app.dependencies.auth import get_current_active_user

router = APIRouter()


# ==========================================
# 1. FINANCE MANAGER DASHBOARD
# ==========================================

@router.get("/finance", response_model=dict)
async def get_finance_dashboard(
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access Denied")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    # Revenue
    month_sales = await Sale.find({
        "created_at": {"$gte": month_start},
        "status": SaleStatus.COMPLETED
    }).to_list()

    last_month_sales = await Sale.find({
        "created_at": {"$gte": last_month_start, "$lt": month_start},
        "status": SaleStatus.COMPLETED
    }).to_list()

    month_revenue = sum(s.total_amount for s in month_sales)
    last_month_revenue = sum(s.total_amount for s in last_month_sales)
    month_tax = sum(s.tax for s in month_sales)
    month_discount = sum(s.discount for s in month_sales)

    # Revenue change percentage
    revenue_change = 0
    if last_month_revenue > 0:
        revenue_change = round(((month_revenue - last_month_revenue) / last_month_revenue) * 100, 1)

    # Payment breakdown
    payment_breakdown = {}
    for sale in month_sales:
        method = sale.payment_method
        payment_breakdown[method] = payment_breakdown.get(method, 0) + sale.total_amount

    # Pending approvals
    pending_pos = await PurchaseOrder.find(
        PurchaseOrder.status == POStatus.PENDING_APPROVAL
    ).to_list()

    pending_value = sum(po.total_amount for po in pending_pos)

    # Cancelled sales
    cancelled = await Sale.find({
        "created_at": {"$gte": month_start},
        "status": SaleStatus.CANCELLED
    }).to_list()
    cancelled_value = sum(s.total_amount for s in cancelled)

    return {
        "revenue": {
            "this_month": round(month_revenue, 2),
            "last_month": round(last_month_revenue, 2),
            "change_percentage": revenue_change,
            "trend": "up" if revenue_change > 0 else "down" if revenue_change < 0 else "flat"
        },
        "tax_collected": round(month_tax, 2),
        "discounts_given": round(month_discount, 2),
        "cancelled_revenue_lost": round(cancelled_value, 2),
        "payment_breakdown": {
            method: round(amount, 2)
            for method, amount in payment_breakdown.items()
        },
        "pending_po_approvals": {
            "count": len(pending_pos),
            "total_value": round(pending_value, 2),
            "orders": [
                {
                    "po_id": str(po.id),
                    "total_amount": po.total_amount,
                    "created_at": po.created_at
                }
                for po in pending_pos[:5]
            ]
        }
    }


# ==========================================
# 2. PURCHASE MANAGER DASHBOARD
# ==========================================

@router.get("/purchase-manager", response_model=dict)
async def get_purchase_manager_dashboard(
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role not in [UserRole.PURCHASE, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access Denied")

    # My POs
    my_pos = await PurchaseOrder.find(
        PurchaseOrder.created_by == current_user.user_id
    ).sort(-PurchaseOrder.created_at).limit(10).to_list()  # type: ignore

    pending_approval_count = await PurchaseOrder.find(
        PurchaseOrder.status == POStatus.PENDING_APPROVAL
    ).count()

    # Low stock across all branches
    low_stock_items = await Inventory.find({
        "quantity": {"$gt": 0, "$lte": 10}
    }).to_list()

    out_of_stock = await Inventory.find({"quantity": 0}).count()

    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    # Active suppliers
    from app.models.supplier import Supplier
    active_suppliers = await Supplier.find(Supplier.is_active == True).count()

    return {
        "pos_summary": {
            "pending_approval": pending_approval_count,
            "my_recent_pos": [
                {
                    "po_id": str(po.id),
                    "total_amount": po.total_amount,
                    "status": po.status,
                    "created_at": po.created_at
                }
                for po in my_pos
            ]
        },
        "stock_alerts": {
            "low_stock_count": len(low_stock_items),
            "out_of_stock_count": out_of_stock,
            "low_stock_items": [
                {
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "branch": branch_map.get(i.branch_id, "Unknown")
                }
                for i in low_stock_items[:10]
            ]
        },
        "active_suppliers": active_suppliers
    }


# ==========================================
# 3. STORE MANAGER DASHBOARD
# ==========================================

@router.get("/store-manager", response_model=dict)
async def get_store_manager_dashboard(
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(status_code=403, detail="Access Denied: Store Managers only")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned")

    branch_id = current_user.branch_id
    branch_id_str = str(branch_id)
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Today's sales at my branch
    today_sales = await Sale.find({
        "branch_id": branch_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
        "status": SaleStatus.COMPLETED
    }).to_list()

    today_revenue = sum(s.total_amount for s in today_sales)

    # My branch inventory status
    inventory = await Inventory.find({"branch_id": branch_id_str}).to_list()
    low_stock = [i for i in inventory if 0 < i.quantity <= i.reorder_point]
    out_of_stock = [i for i in inventory if i.quantity == 0]

    # Staff performance today
    staff_sales = {}
    for sale in today_sales:
        uid = str(sale.sold_by)
        if uid not in staff_sales:
            staff_sales[uid] = {"count": 0, "revenue": 0}
        staff_sales[uid]["count"] += 1
        staff_sales[uid]["revenue"] += sale.total_amount

    staff_performance = []
    for uid, data in staff_sales.items():
        staff_user = await User.find_one(User.user_id == UUID(uid))
        if staff_user:
            staff_performance.append({
                "name": f"{staff_user.first_name} {staff_user.last_name}",
                "sales_count": data["count"],
                "revenue": round(data["revenue"], 2)
            })
    staff_performance.sort(key=lambda x: x["revenue"], reverse=True)

    # Pending transfers
    pending_transfers = await StockTransfer.find({
        "from_branch_id": branch_id,
        "status": TransferStatus.PENDING
    }).count()

    incoming_transfers = await StockTransfer.find({
        "to_branch_id": branch_id,
        "status": TransferStatus.IN_TRANSIT
    }).count()

    # POs arriving at my branch
    incoming_pos = await PurchaseOrder.find({
        "target_branch": branch_id,
        "status": {"$in": [POStatus.SENT, POStatus.APPROVED]}
    }).count()

    branch = await Branch.get(branch_id)

    return {
        "branch_name": branch.name if branch else "Unknown",
        "today_summary": {
            "total_sales": len(today_sales),
            "total_revenue": round(today_revenue, 2),
            "avg_transaction": round(today_revenue / len(today_sales), 2) if today_sales else 0
        },
        "inventory_status": {
            "total_products": len(inventory),
            "low_stock_count": len(low_stock),
            "out_of_stock_count": len(out_of_stock),
            "low_stock_items": [
                {
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "reorder_point": i.reorder_point
                }
                for i in low_stock[:5]
            ]
        },
        "staff_performance_today": staff_performance,
        "pending_actions": {
            "transfers_to_approve": pending_transfers,
            "incoming_transfers": incoming_transfers,
            "incoming_purchase_orders": incoming_pos
        }
    }


# ==========================================
# 4. SALES STAFF DASHBOARD
# ==========================================

@router.get("/sales-staff", response_model=dict)
async def get_sales_staff_dashboard(
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role != UserRole.SALES_STAFF:
        raise HTTPException(status_code=403, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # My sales today
    my_today_sales = await Sale.find({
        "sold_by": current_user.user_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
        "status": SaleStatus.COMPLETED
    }).to_list()

    my_revenue = sum(s.total_amount for s in my_today_sales)
    my_items = sum(sum(i.quantity_sold for i in s.items) for s in my_today_sales)

    # All branch sales today (to calculate rank)
    branch_today_sales = await Sale.find({
        "branch_id": current_user.branch_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
        "status": SaleStatus.COMPLETED
    }).to_list()

    # Staff ranking
    staff_revenue = {}
    for sale in branch_today_sales:
        uid = str(sale.sold_by)
        staff_revenue[uid] = staff_revenue.get(uid, 0) + sale.total_amount

    sorted_staff = sorted(staff_revenue.items(), key=lambda x: x[1], reverse=True)
    my_rank = next(
        (i + 1 for i, (uid, _) in enumerate(sorted_staff) if uid == str(current_user.user_id)),
        None
    )

    # Recent sales
    recent_sales = sorted(my_today_sales, key=lambda s: s.created_at, reverse=True)[:5]

    return {
        "my_name": f"{current_user.first_name} {current_user.last_name}",
        "today": {
            "sales_count": len(my_today_sales),
            "revenue_generated": round(my_revenue, 2),
            "items_sold": my_items,
            "avg_transaction": round(my_revenue / len(my_today_sales), 2) if my_today_sales else 0
        },
        "branch_rank": {
            "my_rank": my_rank,
            "total_staff_selling": len(sorted_staff)
        },
        "recent_sales": [
            {
                "sale_number": s.sale_number,
                "total_amount": s.total_amount,
                "items_count": len(s.items),
                "payment_method": s.payment_method,
                "created_at": s.created_at
            }
            for s in recent_sales
        ]
    }


# ==========================================
# 5. STORE STAFF DASHBOARD (Task List)
# ==========================================

@router.get("/store-staff", response_model=dict)
async def get_store_staff_dashboard(
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role != UserRole.STORE_STAFF:
        raise HTTPException(status_code=403, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned")

    branch_id = current_user.branch_id

    # POs ready to receive at my branch
    pos_to_receive = await PurchaseOrder.find({
        "target_branch": branch_id,
        "status": {"$in": [POStatus.SENT, POStatus.APPROVED]}
    }).to_list()

    # Transfers to ship (approved, from my branch)
    transfers_to_ship = await StockTransfer.find({
        "from_branch_id": branch_id,
        "status": TransferStatus.APPROVED
    }).to_list()

    # Transfers to receive (in transit, to my branch)
    transfers_to_receive = await StockTransfer.find({
        "to_branch_id": branch_id,
        "status": TransferStatus.IN_TRANSIT
    }).to_list()

    branches = await Branch.find_all().to_list()
    branch_map = {b.id: b.name for b in branches}

    return {
        "tasks": {
            "pos_to_receive": len(pos_to_receive),
            "transfers_to_ship": len(transfers_to_ship),
            "transfers_to_receive": len(transfers_to_receive),
            "total_pending_tasks": len(pos_to_receive) + len(transfers_to_ship) + len(transfers_to_receive)
        },
        "purchase_orders_ready": [
            {
                "po_id": str(po.id),
                "total_amount": po.total_amount,
                "items_count": len(po.items),
                "created_at": po.created_at
            }
            for po in pos_to_receive
        ],
        "transfers_to_ship": [
            {
                "transfer_id": str(t.id),
                "to_branch": branch_map.get(t.to_branch_id, "Unknown"),
                "items_count": len(t.items),
                "priority": t.priority
            }
            for t in transfers_to_ship
        ],
        "transfers_to_receive": [
            {
                "transfer_id": str(t.id),
                "from_branch": branch_map.get(t.from_branch_id, "Unknown"),
                "items_count": len(t.items),
                "priority": t.priority
            }
            for t in transfers_to_receive
        ]
    }