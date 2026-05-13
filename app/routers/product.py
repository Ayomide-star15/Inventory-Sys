# app/routers/product.py

from fastapi import APIRouter, HTTPException, Depends, status, Request
from typing import Optional
from uuid import UUID
from datetime import datetime
import logging

from app.models.product import Product
from app.models.category import Category
from app.models.inventory import Inventory
from app.models.price_history import PriceHistory, PriceChangeType
from app.schemas.product import ProductCreate, ProductPriceUpdate
from app.models.user import User, UserRole
from app.dependencies.auth import get_current_user, get_admin_user
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────────────────────

async def get_finance_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Only Finance Manager or Admin can set / update selling prices."""
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Finance Managers can set or update product prices."
        )
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive account.")
    return current_user


# ─────────────────────────────────────────────────────────────
# 1. CREATE PRODUCT — Admin only, no price
# ─────────────────────────────────────────────────────────────

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    request: Request,
    admin: User = Depends(get_admin_user)   # Admin only
):
    """
    Admin creates a product catalog entry — no price required.

    Workflow:
    1. Admin creates product here (name, SKU, barcode, category)
    2. Purchase Manager raises Purchase order and enters cost price per unit
    3. Finance Manager approves Purchase Order and sets global selling price
    """

    # Duplicate checks
    if await Product.find_one(Product.barcode == product_data.barcode):
        raise HTTPException(400, f"A product with barcode '{product_data.barcode}' already exists.")
    if await Product.find_one(Product.sku == product_data.sku):
        raise HTTPException(400, f"A product with SKU '{product_data.sku}' already exists.")

    # Category must exist
    category = await Category.get(product_data.category_id)
    if not category:
        raise HTTPException(404, "Category not found.")

    new_product = Product(
        name=product_data.name,
        sku=product_data.sku,
        barcode=product_data.barcode,
        description=product_data.description,
        low_stock_threshold=product_data.low_stock_threshold,
        category_id=product_data.category_id,
        image_url=product_data.image_url,
        price=None,             # set later by Finance Manager
        cost_price=None,        # reference updated when Finance Manager prices
        created_by=admin.user_id,
        updated_by=admin.user_id
    )
    await new_product.save()

    # Record in price history as "Product Created" with no price yet
    price_record = PriceHistory(
        product_id=new_product.id,
        product_name=new_product.name,
        sku=new_product.sku,
        old_price=None,
        new_price=0,
        change_type=PriceChangeType.CREATED,
        change_reason="Product created — awaiting Finance Manager pricing",
        changed_by=admin.user_id,
        changed_by_name=f"{admin.first_name} {admin.last_name}",
        changed_by_role=admin.role.value,
        effective_date=datetime.utcnow(),
        applied_branches=0
    )
    await price_record.insert()

    await log_action(  # type: ignore[func-returns-value]
        user=admin,
        action=AuditAction.PRODUCT_CREATED,
        module=AuditModule.PRODUCTS,
        description=f"Created product catalog entry: {new_product.name} (SKU: {new_product.sku}) — awaiting pricing",
        target_id=str(new_product.id),
        target_type="product",
        metadata={
            "name": new_product.name,
            "sku": new_product.sku,
            "category": category.name,
            "price_status": "unpriced"
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": "Product created successfully. Finance Manager can now set the selling price.",
        "product_id": str(new_product.id),
        "name": new_product.name,
        "sku": new_product.sku,
        "is_priced": False,
        "next_step": "Finance Manager must set selling price via PUT /products/{id}/price"
    }


# ─────────────────────────────────────────────────────────────
# 2. SET / UPDATE SELLING PRICE — Finance Manager only
# ─────────────────────────────────────────────────────────────

@router.put("/{product_id}/price", response_model=dict)
async def set_product_price(
    product_id: UUID,
    price_update: ProductPriceUpdate,
    request: Request,
    finance: User = Depends(get_finance_user)   # Finance Manager only
):
    """
    Finance Manager sets or updates the global selling price.

    - Price applies to ALL branches immediately
    - reference_cost is optional — taken from the latest PO
    - Every change is recorded in price history
    - Inventory selling_price is synced across all branches
    """
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found.")

    # Validate selling price vs reference cost if provided
    if price_update.reference_cost and price_update.reference_cost >= price_update.price:
        raise HTTPException(
            400,
            f"Selling price (₦{price_update.price:,.2f}) must be higher than "
            f"the cost price (₦{price_update.reference_cost:,.2f})."
        )

    old_price = product.price
    old_cost = product.cost_price

    # Calculate margins
    new_margin = None
    old_margin = None

    if price_update.reference_cost:
        new_margin = round(
            ((price_update.price - price_update.reference_cost) / price_update.reference_cost) * 100, 2
        )

    if old_price and old_cost:
        old_margin = round(((old_price - old_cost) / old_cost) * 100, 2)

    # Determine change type
    if old_price is None:
        change_type = PriceChangeType.CREATED
    elif price_update.price > old_price:
        change_type = PriceChangeType.PRICE_INCREASE
    else:
        change_type = PriceChangeType.PRICE_DECREASE

    # Update product
    product.price = price_update.price
    if price_update.reference_cost:
        product.cost_price = price_update.reference_cost
    product.last_price_change = datetime.utcnow()
    product.last_price_changed_by = finance.user_id
    product.updated_at = datetime.utcnow()
    product.updated_by = finance.user_id
    await product.save()

    # Sync selling price to inventory across all branches
    inventory_records = await Inventory.find(
        {"product_id": str(product_id)}
    ).to_list()

    branches_updated = 0
    for inv in inventory_records:
        inv.selling_price = price_update.price
        inv.updated_at = datetime.utcnow()
        await inv.save()
        branches_updated += 1

    # Record in price history
    price_record = PriceHistory(
        product_id=product.id,
        product_name=product.name,
        sku=product.sku,
        old_price=old_price,
        new_price=price_update.price,
        old_cost_price=old_cost,
        new_cost_price=price_update.reference_cost,
        old_margin=old_margin,
        new_margin=new_margin,
        change_type=change_type,
        change_reason=price_update.reason,
        changed_by=finance.user_id,
        changed_by_name=f"{finance.first_name} {finance.last_name}",
        changed_by_role=finance.role.value,
        effective_date=datetime.utcnow(),
        applied_branches=branches_updated
    )
    await price_record.insert()

    await log_action(  # type: ignore[func-returns-value]
        user=finance,
        action=AuditAction.PRICE_UPDATED,
        module=AuditModule.PRODUCTS,
        description=f"{'Set' if old_price is None else 'Updated'} price for {product.name}: "
                    f"{'unpriced' if old_price is None else f'₦{old_price:,.2f}'} → ₦{price_update.price:,.2f}",
        target_id=str(product.id),
        target_type="product",
        metadata={
            "product_name": product.name,
            "old_price": old_price,
            "new_price": price_update.price,
            "reference_cost": price_update.reference_cost,
            "new_margin": new_margin,
            "reason": price_update.reason,
            "branches_updated": branches_updated
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": f"Selling price {'set' if old_price is None else 'updated'} successfully across all branches.",
        "product_id": str(product_id),
        "product_name": product.name,
        "old_price": old_price,
        "new_price": price_update.price,
        "reference_cost": price_update.reference_cost,
        "margin_percentage": new_margin,
        "branches_updated": branches_updated,
        "is_priced": True
    }


# ─────────────────────────────────────────────────────────────
# 3. GET SINGLE PRODUCT — role based response
# ─────────────────────────────────────────────────────────────

@router.get("/{product_id}")
async def get_product(
    product_id: UUID,
    user: User = Depends(get_current_user)
):

    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found.")

    is_privileged = user.role in [UserRole.ADMIN, UserRole.FINANCE]
    is_priced = product.price is not None

    base = {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "description": product.description,
        "price": product.price,
        "category_id": str(product.category_id),
        "image_url": product.image_url,
        "low_stock_threshold": product.low_stock_threshold,
        "is_priced": is_priced,
        "created_at": product.created_at,
    }

    if is_privileged:
        margin = None
        if product.price and product.cost_price:
            margin = round(
                ((product.price - product.cost_price) / product.cost_price) * 100, 2
            )
        base.update({
            "cost_price": product.cost_price,
            "margin_percentage": margin,
            "created_by": str(product.created_by),
            "updated_at": product.updated_at,
            "updated_by": str(product.updated_by) if product.updated_by else None,
            "last_price_change": product.last_price_change,
            "last_price_changed_by": str(product.last_price_changed_by) if product.last_price_changed_by else None,
        })

    return base


# ─────────────────────────────────────────────────────────────
# 4. LIST ALL PRODUCTS
# ─────────────────────────────────────────────────────────────

@router.get("/")
async def get_products(
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    unpriced_only: bool = False,
    page: int = 1,
    limit: int = 50,
    user: User = Depends(get_current_user)
):
    """
    unpriced_only=true — Finance Manager uses this to find products
    that still need a selling price set.
    """
    if search:
        query = Product.find({
            "$or": [
                {"name": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"barcode": {"$regex": search, "$options": "i"}}
            ]
        })
    elif category_id:
        query = Product.find(Product.category_id == category_id)
    elif unpriced_only:
        query = Product.find({"price": None})
    else:
        query = Product.find_all()

    skip = (page - 1) * limit
    products = await query.skip(skip).limit(limit).to_list()

    is_privileged = user.role in [UserRole.ADMIN, UserRole.FINANCE]

    result = []
    for p in products:
        is_priced = p.price is not None
        item = {
            "id": str(p.id),
            "name": p.name,
            "sku": p.sku,
            "barcode": p.barcode,
            "price": p.price,
            "category_id": str(p.category_id),
            "image_url": p.image_url,
            "is_priced": is_priced,
            "created_at": p.created_at
        }
        if is_privileged:
            margin = None
            if p.price and p.cost_price:
                margin = round(((p.price - p.cost_price) / p.cost_price) * 100, 2)
            item["cost_price"] = p.cost_price
            item["margin_percentage"] = margin

        result.append(item)

    return {
        "total": len(result),
        "page": page,
        "unpriced_count": sum(1 for p in result if not p["is_priced"]),
        "items": result
    }


# ─────────────────────────────────────────────────────────────
# 5. PRICE HISTORY — Finance Manager + Admin
# ─────────────────────────────────────────────────────────────

@router.get("/{product_id}/price-history")
async def get_price_history(
    product_id: UUID,
    finance: User = Depends(get_finance_user)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found.")

    history = await PriceHistory.find(
        PriceHistory.product_id == product_id
    ).sort(-PriceHistory.created_at).to_list()  # type: ignore

    return {
        "product_id": str(product_id),
        "product_name": product.name,
        "sku": product.sku,
        "current_price": product.price,
        "is_priced": product.price is not None,
        "total_changes": len(history),
        "history": [
            {
                "change_date": r.created_at,
                "change_type": r.change_type,
                "old_price": r.old_price,
                "new_price": r.new_price,
                "reference_cost": r.new_cost_price,
                "old_margin": r.old_margin,
                "new_margin": r.new_margin,
                "changed_by": r.changed_by_name,
                "changed_by_role": r.changed_by_role,
                "reason": r.change_reason,
                "effective_date": r.effective_date
            }
            for r in history
        ]
    }


# ─────────────────────────────────────────────────────────────
# 6. DELETE PRODUCT — Admin only
# ─────────────────────────────────────────────────────────────

@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID,
    request: Request,
    admin: User = Depends(get_admin_user)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found.")

    product_name = product.name
    inventory_count = await Inventory.find({"product_id": str(product_id)}).count()

    await product.delete()
    await PriceHistory.find(PriceHistory.product_id == product_id).delete_many()
    await Inventory.find({"product_id": str(product_id)}).delete_many()

    await log_action(  # type: ignore[func-returns-value]
        user=admin,
        action=AuditAction.PRODUCT_DELETED,
        module=AuditModule.PRODUCTS,
        description=f"Deleted product: {product_name} (SKU: {product.sku})",
        target_id=str(product_id),
        target_type="product",
        metadata={
            "product_name": product_name,
            "sku": product.sku,
            "inventory_records_removed": inventory_count
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": f"Product '{product_name}' deleted successfully.",
        "inventory_records_removed": inventory_count
    }