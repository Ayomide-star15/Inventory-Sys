import logging
from fastapi import APIRouter, HTTPException, Depends, status, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from app.core.rate_limit import limiter
from app.models.sale import Sale, SaleItem, SaleStatus, PaymentMethod
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.category import Category
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.models.system_settings import SystemSettings
from app.schemas.sale import (
    SaleCreate, SaleCancelRequest, ProductInventoryResponse,
    QuoteRequest
)
from app.dependencies.auth import get_current_user
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip
from app.utils.stock_alerts import check_and_send_stock_alerts  # ✅ UPDATED

router = APIRouter()
logger = logging.getLogger(__name__)

SALE_ROLES = [
    UserRole.SALES_STAFF,
    UserRole.STORE_MANAGER
]

DISCOUNT_ROLES = [
    UserRole.ADMIN,
    UserRole.FINANCE
]


def generate_sale_number(branch_code: str) -> str:
    import random
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(1000, 9999)
    return f"SALE-{branch_code}-{timestamp}-{random_suffix}"


async def get_settings() -> SystemSettings:
    s = await SystemSettings.find_one({})
    if not s:
        return SystemSettings()
    return s


# ==========================================
# 1. VIEW PRODUCTS WITH INVENTORY
# ==========================================

@router.get("/products", response_model=dict)
@limiter.limit("60/minute")
async def get_products_for_sale(
    request: Request,
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Sales Staff. Paginated in-stock products at the cashier's branch."""
    if current_user.role not in SALE_ROLES:
        raise HTTPException(status_code=403, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="Your account is not assigned to a branch")

    if search:
        product_query = Product.find({
            "$or": [
                {"name": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"barcode": {"$regex": search, "$options": "i"}}
            ]
        })
    elif category_id:
        product_query = Product.find(Product.category_id == category_id)
    else:
        product_query = Product.find_all()

    skip = (page - 1) * limit
    products = await product_query.skip(skip).limit(limit).to_list()

    result = []
    for product in products:
        inventory = await Inventory.find_one({
            "product_id": str(product.id),
            "branch_id": str(current_user.branch_id)
        })
        if inventory and inventory.quantity > 0:
            category = await Category.get(product.category_id)
            result.append({
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "price": inventory.selling_price,
                "category_name": category.name if category else "Unknown",
                "available_quantity": inventory.quantity,
                "image_url": product.image_url
            })

    return {
        "page": page,
        "limit": limit,
        "data": result
    }


# ==========================================
# 2. SEARCH BY BARCODE
# ==========================================

@router.get("/products/barcode/{barcode}", response_model=ProductInventoryResponse)
async def search_product_by_barcode(
    barcode: str,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in SALE_ROLES:
        raise HTTPException(status_code=403, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="Your account is not assigned to a branch")

    product = await Product.find_one(Product.barcode == barcode)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product with barcode '{barcode}' not found")

    inventory = await Inventory.find_one({
        "product_id": str(product.id),
        "branch_id": str(current_user.branch_id)
    })

    if not inventory or inventory.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"'{product.name}' is out of stock at your branch"
        )

    category = await Category.get(product.category_id)

    return {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "price": inventory.selling_price,
        "category_name": category.name if category else "Unknown",
        "available_quantity": inventory.quantity,
        "image_url": product.image_url
    }


# ==========================================
# 3. QUOTE / PRICE PREVIEW
# ==========================================

@router.post("/quote", response_model=dict)
async def get_sale_quote(
    quote_data: QuoteRequest,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in SALE_ROLES:
        raise HTTPException(status_code=403, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned")

    if quote_data.discount > 0 and current_user.role not in DISCOUNT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only Admin and Finance Managers are authorised to apply discounts."
        )

    sys_settings = await get_settings()
    branch_id_str = str(current_user.branch_id)

    items_preview = []
    subtotal = 0.0

    for item in quote_data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })

        if not inventory or inventory.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"'{product.name}' is out of stock at your branch"
            )

        if inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Only {inventory.quantity} unit(s) of '{product.name}' available"
            )

        if inventory.selling_price <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Selling price for '{product.name}' has not been set. "
                       f"Contact your Purchase Manager."
            )

        unit_price = inventory.selling_price
        line_total = item.quantity * unit_price
        subtotal += line_total

        items_preview.append({
            "product_id": str(item.product_id),
            "product_name": product.name,
            "sku": product.sku,
            "quantity": item.quantity,
            "unit_price": unit_price,
            "line_total": round(line_total, 2),
            "available_quantity": inventory.quantity
        })

    if quote_data.discount > 0:
        if quote_data.discount > subtotal:
            raise HTTPException(status_code=400, detail="Discount cannot exceed subtotal")
        max_allowed = subtotal * (sys_settings.max_discount_percentage / 100)
        if quote_data.discount > max_allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Discount exceeds the maximum allowed "
                       f"({sys_settings.max_discount_percentage}%). "
                       f"Max discount for this sale: "
                       f"{sys_settings.currency_symbol}{max_allowed:,.2f}"
            )

    discounted_subtotal = subtotal - quote_data.discount
    tax = discounted_subtotal * sys_settings.vat_rate
    total_amount = discounted_subtotal + tax

    return {
        "items": items_preview,
        "subtotal": round(subtotal, 2),
        "discount": round(quote_data.discount, 2),
        "discounted_subtotal": round(discounted_subtotal, 2),
        "tax": round(tax, 2),
        "tax_rate": f"{sys_settings.vat_rate * 100:.1f}%",
        "total_amount": round(total_amount, 2),
        "currency_symbol": sys_settings.currency_symbol,
        "items_count": len(items_preview),
        "payment_methods": [m.value for m in PaymentMethod]
    }


# ==========================================
# 4. CREATE SALE
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_sale(
    sale_data: SaleCreate,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in SALE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Access Denied: You are not authorised to create sales"
        )

    if not current_user.branch_id:
        raise HTTPException(
            status_code=400,
            detail="Your account is not assigned to a branch"
        )

    sys_settings = await get_settings()
    branch_id_str = str(current_user.branch_id)
    branch = await Branch.get(current_user.branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    sale_items = []
    subtotal = 0.0

    for item in sale_data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })

        if not inventory:
            raise HTTPException(
                status_code=404,
                detail=f"'{product.name}' is not available at your branch"
            )

        if inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for '{product.name}'. "
                       f"Available: {inventory.quantity}, Requested: {item.quantity}"
            )

        unit_price = inventory.selling_price
        if unit_price <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Selling price for '{product.name}' has not been set. "
                       f"Contact your Purchase Manager."
            )

        line_total = item.quantity * unit_price
        subtotal += line_total

        sale_items.append(SaleItem(
            product_id=item.product_id,
            product_name=product.name,
            sku=product.sku,
            barcode=product.barcode,
            quantity_sold=item.quantity,
            unit_price=unit_price,
            line_total=line_total
        ))

    tax = subtotal * sys_settings.vat_rate
    total_amount = subtotal + tax
    sale_number = generate_sale_number(branch.code)

    new_sale = Sale(
        sale_number=sale_number,
        branch_id=current_user.branch_id,
        sold_by=current_user.user_id,
        items=sale_items,
        subtotal=round(subtotal, 2),
        discount=0.0,
        discounted_subtotal=round(subtotal, 2),
        tax=round(tax, 2),
        total_amount=round(total_amount, 2),
        payment_method=sale_data.payment_method,
        amount_paid=round(total_amount, 2),
        change_given=0.0,
        status=SaleStatus.COMPLETED,
        till_number=sale_data.till_number,
        notes=sale_data.notes
    )
    await new_sale.insert()

    # ✅ Deduct inventory and run two-tier stock alert check
    for item in sale_data.items:
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })
        if inventory:
            inventory.quantity -= item.quantity
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

            await check_and_send_stock_alerts(
                inventory, current_user.branch_id, sys_settings
            )

    await log_action(
        user=current_user,
        action=AuditAction.SALE_COMPLETED,
        module=AuditModule.SALES,
        description=f"Completed sale {sale_number} — "
                    f"{sys_settings.currency_symbol}{total_amount:,.2f} "
                    f"({sale_data.payment_method.value})",
        target_id=str(new_sale.id),
        target_type="sale",
        metadata={
            "sale_number": sale_number,
            "subtotal": round(subtotal, 2),
            "tax": round(tax, 2),
            "total_amount": round(total_amount, 2),
            "items_count": len(sale_items),
            "payment_method": sale_data.payment_method.value,
            "branch": branch.name
        },
        branch_name=branch.name,
        ip_address=extract_ip(request)
    )

    return {
        "message": "Sale completed successfully",
        "sale_id": str(new_sale.id),
        "sale_number": new_sale.sale_number,
        "items": [
            {
                "product_name": i.product_name,
                "quantity": i.quantity_sold,
                "unit_price": i.unit_price,
                "line_total": i.line_total
            }
            for i in sale_items
        ],
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "tax_rate": f"{sys_settings.vat_rate * 100:.1f}%",
        "total_amount": round(total_amount, 2),
        "payment_method": sale_data.payment_method.value,
        "currency_symbol": sys_settings.currency_symbol,
        "timestamp": new_sale.created_at
    }


# ==========================================
# 5. LIST SALES
# ==========================================

@router.get("/", response_model=List[dict])
async def list_sales(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    payment_method: Optional[PaymentMethod] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    query = {}

    if current_user.role == UserRole.SALES_STAFF:
        query["sold_by"] = current_user.user_id
    elif current_user.role == UserRole.STORE_MANAGER:
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="No branch assigned")
        query["branch_id"] = current_user.branch_id
    elif current_user.role in [UserRole.ADMIN, UserRole.FINANCE]:
        pass
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    if start_date:
        query["created_at"] = {"$gte": start_date}
    if end_date:
        query.setdefault("created_at", {})["$lte"] = end_date
    if payment_method:
        query["payment_method"] = payment_method

    skip = (page - 1) * limit
    sales = await Sale.find(query).sort(-Sale.created_at).skip(skip).limit(limit).to_list()  # type: ignore

    result = []
    for sale in sales:
        cashier = await User.find_one(User.user_id == sale.sold_by)
        branch = await Branch.get(sale.branch_id)
        result.append({
            "sale_id": str(sale.id),
            "sale_number": sale.sale_number,
            "branch_name": branch.name if branch else "Unknown",
            "cashier_name": f"{cashier.first_name} {cashier.last_name}" if cashier else "Unknown",
            "subtotal": sale.subtotal,
            "discount": sale.discount,
            "tax": sale.tax,
            "total_amount": sale.total_amount,
            "items_count": len(sale.items),
            "payment_method": sale.payment_method,
            "status": sale.status,
            "created_at": sale.created_at
        })

    return result


# ==========================================
# 6. GET SALE DETAILS
# ==========================================

@router.get("/{sale_id}", response_model=dict)
async def get_sale_details(
    sale_id: UUID,
    current_user: User = Depends(get_current_user)
):
    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if current_user.role == UserRole.SALES_STAFF:
        if sale.sold_by != current_user.user_id:
            raise HTTPException(status_code=403, detail="You can only view your own sales")
    elif current_user.role == UserRole.STORE_MANAGER:
        if str(sale.branch_id) != str(current_user.branch_id):
            raise HTTPException(status_code=403, detail="You can only view sales from your branch")
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied")

    branch = await Branch.get(sale.branch_id)
    cashier = await User.find_one(User.user_id == sale.sold_by)

    return {
        "sale_id": str(sale.id),
        "sale_number": sale.sale_number,
        "branch_name": branch.name if branch else "Unknown",
        "cashier_name": f"{cashier.first_name} {cashier.last_name}" if cashier else "Unknown",
        "items": [
            {
                "product_name": i.product_name,
                "sku": i.sku,
                "barcode": i.barcode,
                "quantity": i.quantity_sold,
                "unit_price": i.unit_price,
                "line_total": i.line_total
            }
            for i in sale.items
        ],
        "subtotal": sale.subtotal,
        "discount": sale.discount,
        "tax": sale.tax,
        "total_amount": sale.total_amount,
        "payment_method": sale.payment_method,
        "amount_paid": sale.amount_paid,
        "change_given": sale.change_given,
        "status": sale.status,
        "till_number": sale.till_number,
        "notes": sale.notes,
        "created_at": sale.created_at
    }


# ==========================================
# 7. TODAY'S SALES SUMMARY
# ==========================================

@router.get("/my-branch/today", response_model=dict)
async def get_todays_sales(
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in SALE_ROLES:
        raise HTTPException(status_code=403, detail="Access denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned")

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    sales = await Sale.find({
        "branch_id": current_user.branch_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
        "status": SaleStatus.COMPLETED
    }).to_list()

    if current_user.role == UserRole.SALES_STAFF:
        sales = [s for s in sales if s.sold_by == current_user.user_id]

    total_sales = len(sales)
    total_revenue = sum(s.total_amount for s in sales)
    total_items = sum(sum(i.quantity_sold for i in s.items) for s in sales)

    return {
        "date": today_start.date(),
        "total_sales": total_sales,
        "total_revenue": round(total_revenue, 2),
        "total_items_sold": total_items,
        "average_transaction_value": round(total_revenue / total_sales, 2) if total_sales > 0 else 0
    }


# ==========================================
# 8. CANCEL SALE
# ==========================================

@router.put("/{sale_id}/cancel", response_model=dict)
async def cancel_sale(
    sale_id: UUID,
    cancel_data: SaleCancelRequest,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.STORE_MANAGER, UserRole.SALES_STAFF]:
        raise HTTPException(
            status_code=403,
            detail="Only Store Managers and Sales Staff can cancel sales"
        )

    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale.status != SaleStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel. Sale status is '{sale.status}'"
        )

    sale.status = SaleStatus.CANCELLED
    sale.cancelled_at = datetime.utcnow()
    sale.cancelled_by = current_user.user_id
    sale.cancellation_reason = cancel_data.cancellation_reason
    await sale.save()

    branch_id_str = str(sale.branch_id)
    for item in sale.items:
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })
        if inventory:
            inventory.quantity += item.quantity_sold
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

    await log_action(
        user=current_user,
        action=AuditAction.SALE_CANCELLED,
        module=AuditModule.SALES,
        description=f"Cancelled sale {sale.sale_number}. "
                    f"Reason: {cancel_data.cancellation_reason}",
        target_id=str(sale.id),
        target_type="sale",
        metadata={
            "sale_number": sale.sale_number,
            "reason": cancel_data.cancellation_reason,
            "total_amount": sale.total_amount
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": "Sale cancelled and inventory restored successfully",
        "sale_id": str(sale.id),
        "sale_number": sale.sale_number,
        "status": sale.status
    }