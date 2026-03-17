from fastapi import APIRouter, HTTPException, Depends, status, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from app.models.product import Product
from app.models.category import Category
from app.models.inventory import Inventory
from app.models.price_history import PriceHistory, PriceChangeType
from app.schemas.product import (
    ProductCreate,
    ProductPriceUpdate,
)
from app.models.user import User, UserRole
from app.dependencies.auth import get_current_user, get_product_manager
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip

logger = logging.getLogger(__name__)
router = APIRouter()


# ==========================================
# 1. CREATE PRODUCT
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    request: Request,
    manager: User = Depends(get_product_manager)
):
    existing_barcode = await Product.find_one(Product.barcode == product_data.barcode)
    if existing_barcode:
        raise HTTPException(400, "Product with this barcode already exists")

    existing_sku = await Product.find_one(Product.sku == product_data.sku)
    if existing_sku:
        raise HTTPException(400, "Product with this SKU already exists")

    category = await Category.get(product_data.category_id)
    if not category:
        raise HTTPException(404, "Category not found")

    if product_data.price <= 0:
        raise HTTPException(400, "Selling price must be positive")
    if product_data.cost_price <= 0:
        raise HTTPException(400, "Cost price must be positive")
    if product_data.cost_price >= product_data.price:
        raise HTTPException(400, "Cost price must be less than selling price")

    new_product = Product(
        name=product_data.name,
        sku=product_data.sku,
        barcode=product_data.barcode,
        description=product_data.description,
        price=product_data.price,
        cost_price=product_data.cost_price,
        low_stock_threshold=product_data.low_stock_threshold,
        category_id=product_data.category_id,
        image_url=product_data.image_url,
        created_by=manager.user_id,
        updated_by=manager.user_id
    )
    await new_product.save()

    margin = ((product_data.price - product_data.cost_price) / product_data.cost_price) * 100

    price_record = PriceHistory(
        product_id=new_product.id,
        product_name=new_product.name,
        sku=new_product.sku,
        old_price=None,
        new_price=product_data.price,
        old_cost_price=None,
        new_cost_price=product_data.cost_price,
        new_margin=margin,
        change_type=PriceChangeType.CREATED,
        change_reason="Product created",
        changed_by=manager.user_id,
        changed_by_name=f"{manager.first_name} {manager.last_name}",
        changed_by_role=manager.role.value,
        effective_date=datetime.utcnow(),
        applied_branches=0
    )
    await price_record.insert()

    await log_action(
        user=manager,
        action=AuditAction.PRODUCT_CREATED,
        module=AuditModule.PRODUCTS,
        description=f"Created product: {new_product.name} (SKU: {new_product.sku}) — ₦{product_data.price}",
        target_id=str(new_product.id),
        target_type="product",
        metadata={
            "name": new_product.name,
            "sku": new_product.sku,
            "price": product_data.price,
            "cost_price": product_data.cost_price,
            "margin": round(margin, 2)
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": "Product created successfully",
        "product_id": str(new_product.id),
        "name": new_product.name,
        "selling_price": product_data.price,
        "cost_price": product_data.cost_price,
        "margin_percentage": round(margin, 2)
    }


# ==========================================
# 2. GET PRODUCT (Role-based)
# ==========================================

@router.get("/{product_id}")
async def get_product(product_id: UUID, user: User = Depends(get_current_user)):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    is_admin_or_finance = user.role in [UserRole.ADMIN, UserRole.FINANCE, UserRole.PURCHASE]

    if is_admin_or_finance:
        margin = ((product.price - product.cost_price) / product.cost_price) * 100
        return {
            "id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "description": product.description,
            "price": product.price,
            "cost_price": product.cost_price,
            "margin_percentage": round(margin, 2),
            "category_id": str(product.category_id),
            "image_url": product.image_url,
            "low_stock_threshold": product.low_stock_threshold,
            "created_at": product.created_at,
            "created_by": str(product.created_by),
            "updated_at": product.updated_at,
            "updated_by": str(product.updated_by) if product.updated_by else None,
            "last_price_change": product.last_price_change,
            "user_role": "admin"
        }
    else:
        return {
            "id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "description": product.description,
            "price": product.price,
            "category_id": str(product.category_id),
            "image_url": product.image_url,
            "low_stock_threshold": product.low_stock_threshold,
            "created_at": product.created_at,
            "user_role": "staff"
        }


# ==========================================
# 3. LIST ALL PRODUCTS
# ==========================================

@router.get("/")
async def get_products(
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    page: int = 1,
    limit: int = 50,
    user: User = Depends(get_current_user)
):
    query = Product.find_all()

    if category_id:
        query = Product.find(Product.category_id == category_id)
    if search:
        query = Product.find({
            "$or": [
                {"name": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"barcode": {"$regex": search, "$options": "i"}}
            ]
        })

    skip = (page - 1) * limit
    products = await query.skip(skip).limit(limit).to_list()

    is_admin_or_finance = user.role in [UserRole.ADMIN, UserRole.FINANCE, UserRole.PURCHASE]

    result = []
    for product in products:
        item = {
            "id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "price": product.price,
            "category_id": str(product.category_id),
            "image_url": product.image_url,
            "created_at": product.created_at
        }
        if is_admin_or_finance:
            margin = ((product.price - product.cost_price) / product.cost_price) * 100
            item["cost_price"] = product.cost_price
            item["margin_percentage"] = round(margin, 2)

        result.append(item)

    return {
        "total": len(result),
        "page": page,
        "items": result,
        "viewer_role": "admin" if is_admin_or_finance else "staff"
    }


# ==========================================
# 4. UPDATE PRICE
# ==========================================

@router.put("/{product_id}/price", response_model=dict)
async def update_product_price(
    product_id: UUID,
    price_update: ProductPriceUpdate,
    request: Request,
    manager: User = Depends(get_product_manager)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    old_price = product.price
    old_cost_price = product.cost_price

    price_changed = price_update.price is not None
    cost_changed = price_update.cost_price is not None

    new_price: float = price_update.price if price_changed else old_price  # type: ignore
    new_cost_price: float = price_update.cost_price if cost_changed else old_cost_price  # type: ignore

    if new_price <= 0:
        raise HTTPException(400, "Selling price must be positive")
    if new_cost_price <= 0:
        raise HTTPException(400, "Cost price must be positive")
    if new_cost_price >= new_price:
        raise HTTPException(400, "Cost price must be less than selling price")

    if price_changed:
        product.price = new_price
    if cost_changed:
        product.cost_price = new_cost_price

    product.updated_at = datetime.utcnow()
    product.updated_by = manager.user_id
    product.last_price_change = datetime.utcnow()
    product.last_price_changed_by = manager.user_id
    await product.save()

    inventory_records = await Inventory.find({"product_id": str(product_id)}).to_list()
    branches_updated = 0
    for inventory in inventory_records:
        inventory.selling_price = new_price
        await inventory.save()
        branches_updated += 1

    old_margin = ((old_price - old_cost_price) / old_cost_price) * 100
    new_margin = ((new_price - new_cost_price) / new_cost_price) * 100

    if price_changed and not cost_changed:
        change_type = PriceChangeType.PRICE_INCREASE if new_price > old_price else PriceChangeType.PRICE_DECREASE
    else:
        change_type = PriceChangeType.COST_ADJUSTMENT

    price_record = PriceHistory(
        product_id=product.id,
        product_name=product.name,
        sku=product.sku,
        old_price=old_price,
        new_price=new_price,
        old_cost_price=old_cost_price,
        new_cost_price=new_cost_price,
        old_margin=old_margin,
        new_margin=new_margin,
        change_type=change_type,
        change_reason=price_update.reason,
        changed_by=manager.user_id,
        changed_by_name=f"{manager.first_name} {manager.last_name}",
        changed_by_role=manager.role.value,
        effective_date=datetime.utcnow(),
        applied_branches=branches_updated
    )
    await price_record.insert()

    await log_action(
        user=manager,
        action=AuditAction.PRICE_UPDATED,
        module=AuditModule.PRODUCTS,
        description=f"Updated price for {product.name}: ₦{old_price} → ₦{new_price}",
        target_id=str(product.id),
        target_type="product",
        metadata={
            "product_name": product.name,
            "old_price": old_price,
            "new_price": new_price,
            "old_cost_price": old_cost_price,
            "new_cost_price": new_cost_price,
            "reason": price_update.reason
        },
        ip_address=extract_ip(request)
    )

    return {
        "message": "Product price updated globally",
        "product_id": str(product.id),
        "product_name": product.name,
        "old_price": old_price,
        "new_price": new_price,
        "old_margin_percentage": round(old_margin, 2),
        "new_margin_percentage": round(new_margin, 2),
        "branches_updated": branches_updated,
        "applied_to_all_branches": True
    }


# ==========================================
# 5. PRICE HISTORY
# ==========================================

@router.get("/{product_id}/price-history")
async def get_price_history(
    product_id: UUID,
    current_user: User = Depends(get_product_manager)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    history = await PriceHistory.find(
        PriceHistory.product_id == product_id
    ).sort(-PriceHistory.created_at).to_list()  # type: ignore

    return {
        "product_id": str(product_id),
        "product_name": product.name,
        "sku": product.sku,
        "current_price": product.price,
        "current_cost_price": product.cost_price,
        "total_changes": len(history),
        "history": [
            {
                "change_date": record.created_at,
                "change_type": record.change_type,
                "old_price": record.old_price,
                "new_price": record.new_price,
                "old_cost_price": record.old_cost_price,
                "new_cost_price": record.new_cost_price,
                "old_margin": record.old_margin,
                "new_margin": record.new_margin,
                "changed_by": record.changed_by_name,
                "changed_by_role": record.changed_by_role,
                "reason": record.change_reason,
                "effective_date": record.effective_date
            }
            for record in history
        ]
    }


# ==========================================
# 6. DELETE PRODUCT
# ==========================================

@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID,
    request: Request,
    manager: User = Depends(get_product_manager)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    product_name = product.name

    # ✅ FIXED: Clean up inventory records across all branches
    inventory_count = await Inventory.find({"product_id": str(product_id)}).count()

    await product.delete()
    await PriceHistory.find(PriceHistory.product_id == product_id).delete_many()
    await Inventory.find({"product_id": str(product_id)}).delete_many()  # ✅ Added

    await log_action(
        user=manager,
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
        "message": f"Product '{product_name}' deleted successfully",
        "inventory_records_removed": inventory_count
    }