from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta

from app.models.user import User, UserRole
from app.models.sale import Sale, SaleStatus, PaymentMethod
from app.models.purchase_order import PurchaseOrder, POStatus
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.branch import Branch
from app.dependencies.auth import get_current_active_user

router = APIRouter()


def require_finance_or_admin(current_user: User):
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Finance Manager or Admin only"
        )


# ==========================================
# 1. SALES SUMMARY
# ==========================================

@router.get("/sales/summary", response_model=dict)
async def get_sales_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    branch_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Revenue summary across all branches for a date range.
    Finance and Admin only.
    """
    require_finance_or_admin(current_user)

    # Default: last 30 days
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    query = {
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.COMPLETED
    }
    if branch_id:
        query["branch_id"] = branch_id

    sales = await Sale.find(query).to_list()
    cancelled_sales = await Sale.find({
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.CANCELLED,
        **({"branch_id": branch_id} if branch_id else {})
    }).to_list()

    total_revenue = sum(s.total_amount for s in sales)
    total_tax = sum(s.tax for s in sales)
    total_discount = sum(s.discount for s in sales)
    total_subtotal = sum(s.subtotal for s in sales)
    cancelled_revenue = sum(s.total_amount for s in cancelled_sales)

    return {
        "period": {
            "start": start_date,
            "end": end_date,
            "days": (end_date - start_date).days
        },
        "revenue": {
            "gross_revenue": round(total_revenue, 2),
            "subtotal": round(total_subtotal, 2),
            "total_tax_collected": round(total_tax, 2),
            "total_discounts_given": round(total_discount, 2),
            "cancelled_revenue_lost": round(cancelled_revenue, 2)
        },
        "transactions": {
            "completed_sales": len(sales),
            "cancelled_sales": len(cancelled_sales),
            "average_transaction": round(total_revenue / len(sales), 2) if sales else 0
        }
    }


# ==========================================
# 2. SALES BY BRANCH
# ==========================================

@router.get("/sales/by-branch", response_model=dict)
async def get_sales_by_branch(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Finance and Admin only.
    Revenue breakdown per branch.
    """
    require_finance_or_admin(current_user)

    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    sales = await Sale.find({
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.COMPLETED
    }).to_list()

    branches = await Branch.find_all().to_list()
    branch_map = {b.id: b.name for b in branches}

    branch_data = {}
    for sale in sales:
        bid = sale.branch_id
        if bid not in branch_data:
            branch_data[bid] = {
                "branch_id": str(bid),
                "branch_name": branch_map.get(bid, "Unknown"),
                "revenue": 0,
                "sales_count": 0,
                "tax_collected": 0,
                "discounts_given": 0
            }
        branch_data[bid]["revenue"] += sale.total_amount
        branch_data[bid]["sales_count"] += 1
        branch_data[bid]["tax_collected"] += sale.tax
        branch_data[bid]["discounts_given"] += sale.discount

    result = list(branch_data.values())
    for b in result:
        b["revenue"] = round(b["revenue"], 2)
        b["tax_collected"] = round(b["tax_collected"], 2)
        b["discounts_given"] = round(b["discounts_given"], 2)
        b["avg_transaction"] = round(b["revenue"] / b["sales_count"], 2) if b["sales_count"] else 0

    result.sort(key=lambda x: x["revenue"], reverse=True)

    total = sum(b["revenue"] for b in result)

    return {
        "period": {"start": start_date, "end": end_date},
        "total_revenue": round(total, 2),
        "branches": result
    }


# ==========================================
# 3. PAYMENT METHOD BREAKDOWN
# ==========================================

@router.get("/sales/by-payment", response_model=dict)
async def get_sales_by_payment_method(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    branch_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Finance and Admin only.
    Revenue split by payment method.
    Useful for detecting fraud (branch doing 90% cash is suspicious).
    """
    require_finance_or_admin(current_user)

    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    query = {
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.COMPLETED
    }
    if branch_id:
        query["branch_id"] = branch_id

    sales = await Sale.find(query).to_list()
    total_revenue = sum(s.total_amount for s in sales)

    payment_data = {}
    for sale in sales:
        method = sale.payment_method
        if method not in payment_data:
            payment_data[method] = {"count": 0, "revenue": 0}
        payment_data[method]["count"] += 1
        payment_data[method]["revenue"] += sale.total_amount

    result = []
    for method, data in payment_data.items():
        result.append({
            "payment_method": method,
            "transaction_count": data["count"],
            "revenue": round(data["revenue"], 2),
            "percentage": round((data["revenue"] / total_revenue * 100), 1) if total_revenue else 0
        })

    result.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "period": {"start": start_date, "end": end_date},
        "total_revenue": round(total_revenue, 2),
        "payment_breakdown": result
    }


# ==========================================
# 4. PROFIT REPORT
# ==========================================

@router.get("/profit", response_model=dict)
async def get_profit_report(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    branch_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Gross profit = Revenue - Cost of Goods Sold.
    Uses cost_price from Product at time of sale to estimate COGS.
    Finance and Admin only.
    """
    require_finance_or_admin(current_user)

    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    query = {
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.COMPLETED
    }
    if branch_id:
        query["branch_id"] = branch_id

    sales = await Sale.find(query).to_list()

    total_revenue = 0.0
    total_cogs = 0.0
    branch_profit = {}

    for sale in sales:
        sale_revenue = sale.total_amount
        sale_cogs = 0.0

        for item in sale.items:
            product = await Product.get(item.product_id)
            if product:
                cost = product.cost_price * item.quantity_sold
                sale_cogs += cost

        bid = str(sale.branch_id)
        if bid not in branch_profit:
            branch_profit[bid] = {
                "branch_id": bid,
                "revenue": 0,
                "cogs": 0,
                "gross_profit": 0,
                "margin_percentage": 0
            }

        branch_profit[bid]["revenue"] += sale_revenue
        branch_profit[bid]["cogs"] += sale_cogs

        total_revenue += sale_revenue
        total_cogs += sale_cogs

    # Enrich with branch names and calculate margins
    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    branch_results = []
    for bid, data in branch_profit.items():
        profit = data["revenue"] - data["cogs"]
        margin = (profit / data["revenue"] * 100) if data["revenue"] else 0
        branch_results.append({
            "branch_name": branch_map.get(bid, "Unknown"),
            "branch_id": bid,
            "revenue": round(data["revenue"], 2),
            "cogs": round(data["cogs"], 2),
            "gross_profit": round(profit, 2),
            "margin_percentage": round(margin, 1)
        })

    branch_results.sort(key=lambda x: x["gross_profit"], reverse=True)

    total_profit = total_revenue - total_cogs
    overall_margin = (total_profit / total_revenue * 100) if total_revenue else 0

    return {
        "period": {"start": start_date, "end": end_date},
        "overall": {
            "total_revenue": round(total_revenue, 2),
            "total_cogs": round(total_cogs, 2),
            "gross_profit": round(total_profit, 2),
            "margin_percentage": round(overall_margin, 1)
        },
        "by_branch": branch_results
    }


# ==========================================
# 5. TAX REPORT
# ==========================================

@router.get("/tax", response_model=dict)
async def get_tax_report(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Finance and Admin only.
    Total VAT collected across all branches.
    """
    require_finance_or_admin(current_user)

    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    sales = await Sale.find({
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": SaleStatus.COMPLETED
    }).to_list()

    total_tax = sum(s.tax for s in sales)
    total_revenue = sum(s.total_amount for s in sales)

    branches = await Branch.find_all().to_list()
    branch_map = {b.id: b.name for b in branches}

    branch_tax = {}
    for sale in sales:
        bid = sale.branch_id
        if bid not in branch_tax:
            branch_tax[bid] = 0
        branch_tax[bid] += sale.tax

    by_branch = [
        {
            "branch_name": branch_map.get(bid, "Unknown"),
            "tax_collected": round(tax, 2)
        }
        for bid, tax in branch_tax.items()
    ]
    by_branch.sort(key=lambda x: x["tax_collected"], reverse=True)

    return {
        "period": {"start": start_date, "end": end_date},
        "total_vat_collected": round(total_tax, 2),
        "total_revenue": round(total_revenue, 2),
        "effective_tax_rate": round((total_tax / total_revenue * 100), 2) if total_revenue else 0,
        "by_branch": by_branch
    }


# ==========================================
# 6. PROCUREMENT SPEND
# ==========================================

@router.get("/procurement/spend", response_model=dict)
async def get_procurement_spend(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    How much was spent on Purchase Orders per branch and supplier.
    Finance and Admin only.
    """
    require_finance_or_admin(current_user)

    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    pos = await PurchaseOrder.find({
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": {"$in": [POStatus.RECEIVED, POStatus.SENT, POStatus.APPROVED]}
    }).to_list()

    total_spend = sum(po.total_amount for po in pos)

    # By branch
    branch_spend = {}
    for po in pos:
        bid = str(po.target_branch)
        branch_spend[bid] = branch_spend.get(bid, 0) + po.total_amount

    # By supplier
    supplier_spend = {}
    for po in pos:
        sid = str(po.supplier_id)
        supplier_spend[sid] = supplier_spend.get(sid, 0) + po.total_amount

    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    from app.models.supplier import Supplier
    suppliers = await Supplier.find_all().to_list()
    supplier_map = {str(s.id): s.name for s in suppliers}

    return {
        "period": {"start": start_date, "end": end_date},
        "total_procurement_spend": round(total_spend, 2),
        "total_pos": len(pos),
        "by_branch": sorted([
            {"branch": branch_map.get(bid, "Unknown"), "spend": round(amt, 2)}
            for bid, amt in branch_spend.items()
        ], key=lambda x: x["spend"], reverse=True),
        "by_supplier": sorted([
            {"supplier": supplier_map.get(sid, "Unknown"), "spend": round(amt, 2)}
            for sid, amt in supplier_spend.items()
        ], key=lambda x: x["spend"], reverse=True)
    }


# ==========================================
# 7. SLOW-MOVING INVENTORY
# ==========================================

@router.get("/inventory/slow-moving", response_model=dict)
async def get_slow_moving_inventory(
    days_threshold: int = Query(default=30, description="Products not updated in this many days"),
    current_user: User = Depends(get_current_active_user)
):
    """
    Finance and Admin only.
    Products sitting in stock that haven't moved.
    Money tied up in slow stock.
    """
    require_finance_or_admin(current_user)

    cutoff = datetime.utcnow() - timedelta(days=days_threshold)

    all_inventory = await Inventory.find({
        "quantity": {"$gt": 0},
        "updated_at": {"$lt": cutoff}
    }).to_list()

    branches = await Branch.find_all().to_list()
    branch_map = {str(b.id): b.name for b in branches}

    slow_items = []
    total_value_tied = 0.0

    for item in all_inventory:
        value = item.quantity * item.selling_price
        total_value_tied += value
        slow_items.append({
            "product_name": item.product_name,
            "branch": branch_map.get(item.branch_id, "Unknown"),
            "quantity": item.quantity,
            "selling_price": item.selling_price,
            "value_tied_up": round(value, 2),
            "last_updated": item.updated_at
        })

    slow_items.sort(key=lambda x: x["value_tied_up"], reverse=True)

    return {
        "threshold_days": days_threshold,
        "total_slow_items": len(slow_items),
        "total_value_tied_up": round(total_value_tied, 2),
        "items": slow_items[:50]  # Top 50 worst offenders
    }