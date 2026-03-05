# app/routers/product.py - FIXED VERSION (Key endpoints)

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from app.models.product import Product
from app.models.category import Category
from app.models.price_history import PriceHistory, PriceChangeType
from app.schemas.product import (
    ProductCreate,
    ProductPriceUpdate,
    ProductResponseForStaff,
    ProductResponseForAdmin,
    PriceHistoryResponse,
    PriceHistoryItem
)
from app.models.user import User, UserRole
from app.dependencies.auth import get_current_user, get_product_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# ==========================================
# 1. CREATE PRODUCT (Admin/PM only)
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    manager: User = Depends(get_product_manager)  # Admin or Purchase Manager
):
    """
    Create product with GLOBAL pricing.
    
    Both prices set once:
    - price: Selling price (visible to all staff)
    - cost_price: Cost price (admin only)
    
    Product immediately visible in ALL branches.
    """
    
    # 1. Check for duplicates
    existing_barcode = await Product.find_one(Product.barcode == product_data.barcode)
    if existing_barcode:
        raise HTTPException(400, "Product with this barcode already exists")
    
    existing_sku = await Product.find_one(Product.sku == product_data.sku)
    if existing_sku:
        raise HTTPException(400, "Product with this SKU already exists")

    # 2. Verify category exists
    category = await Category.get(product_data.category_id)
    if not category:
        raise HTTPException(404, "Category not found")

    # 3. Validate prices
    if product_data.price <= 0:
        raise HTTPException(400, "Selling price must be positive")
    
    if product_data.cost_price <= 0:
        raise HTTPException(400, "Cost price must be positive")
    
    if product_data.cost_price >= product_data.price:
        raise HTTPException(400, "Cost price must be less than selling price")

    # 4. Create product
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

    # 5. Record price history
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
        changed_by_role=str(manager.role),
        effective_date=datetime.utcnow(),
        applied_branches=0
    )
    await price_record.insert()

    logger.info("Product created", extra={
        "product_id": str(new_product.id),
        "product_name": new_product.name,
        "selling_price": product_data.price,
        "cost_price": product_data.cost_price,
        "created_by": str(manager.user_id)
    })

    return {
        "message": "Product created successfully",
        "product_id": str(new_product.id),
        "name": new_product.name,
        "selling_price": product_data.price,
        "cost_price": product_data.cost_price,
        "margin_percentage": round(margin, 2),
        "visible_to_all_branches": True
    }

# ==========================================
# 2. GET PRODUCT (Role-based response)
# ==========================================

@router.get("/{product_id}")
async def get_product(
    product_id: UUID,
    user: User = Depends(get_current_user)
):
    """
    Get product details - response varies by user role.
    
    Staff see: name, sku, price (NOT cost_price)
    Admin see: name, sku, price, cost_price, margin
    """
    
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    # Check if user is admin or finance
    is_admin_or_finance = user.role in [UserRole.ADMIN, UserRole.FINANCE, UserRole.PURCHASE]

    if is_admin_or_finance:
        # Return full details with cost price
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
            "last_price_changed_by": str(product.last_price_changed_by) if product.last_price_changed_by else None,
            "user_role": "admin"
        }
    else:
        # Return basic details WITHOUT cost price
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
# 3. LIST ALL PRODUCTS (Role-based)
# ==========================================

@router.get("/")
async def get_products(
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    user: User = Depends(get_current_user)
):
    """
    List all products - response varies by user role.
    
    All staff see products and selling prices.
    Admin/Finance also see cost prices.
    """
    
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
    
    products = await query.to_list()
    
    is_admin_or_finance = user.role in [UserRole.ADMIN, UserRole.FINANCE, UserRole.PURCHASE]
    
    result = []
    for product in products:
        margin = ((product.price - product.cost_price) / product.cost_price) * 100
        
        item = {
            "id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "price": product.price,  # Visible to all
            "category_id": str(product.category_id),
            "image_url": product.image_url,
            "created_at": product.created_at
        }
        
        # Only admin/finance see cost price
        if is_admin_or_finance:
            item["cost_price"] = product.cost_price
            item["margin_percentage"] = round(margin, 2)
        
        result.append(item)
    
    return {
        "total": len(result),
        "items": result,
        "viewer_role": "admin" if is_admin_or_finance else "staff"
    }

# ==========================================
# 4. UPDATE PRODUCT PRICE (Global)
# ==========================================

@router.put("/{product_id}/price", response_model=dict)
async def update_product_price(
    product_id: UUID,
    price_update: ProductPriceUpdate,
    manager: User = Depends(get_product_manager)  # Admin or Purchase Manager
):
    """
    Update GLOBAL product prices.
    
    Changes apply to ALL branches immediately.
    Full audit trail recorded.
    """
    
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    # Store old values for history
    old_price = product.price
    old_cost_price = product.cost_price

    # Determine what's being updated
    price_changed = price_update.price is not None
    cost_changed = price_update.cost_price is not None

    # Validate new values - use or operator carefully
    new_price: float = price_update.price if price_changed else old_price # type: ignore
    new_cost_price: float = price_update.cost_price if cost_changed else old_cost_price # type: ignore

    if new_price <= 0:
        raise HTTPException(400, "Selling price must be positive")

    if new_cost_price <= 0:
        raise HTTPException(400, "Cost price must be positive")

    if new_cost_price >= new_price:
        raise HTTPException(400, "Cost price must be less than selling price")

    # Update product
    if price_changed:
        product.price = new_price

    if cost_changed:
        product.cost_price = new_cost_price

    product.updated_at = datetime.utcnow()
    product.updated_by = manager.user_id
    product.last_price_change = datetime.utcnow()
    product.last_price_changed_by = manager.user_id

    await product.save()

    # Record price history
    old_margin = ((old_price - old_cost_price) / old_cost_price) * 100
    new_margin = ((new_price - new_cost_price) / new_cost_price) * 100

    # Determine change type
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
        changed_by_role=str(manager.role),
        effective_date=datetime.utcnow(),
        applied_branches=0
    )
    await price_record.insert()

    logger.info("Product price updated globally", extra={
        "product_id": str(product.id),
        "product_name": product.name,
        "old_price": old_price,
        "new_price": new_price,
        "old_cost_price": old_cost_price,
        "new_cost_price": new_cost_price,
        "updated_by": str(manager.user_id),
        "reason": price_update.reason
    })

    return {
        "message": "Product price updated globally",
        "product_id": str(product.id),
        "product_name": product.name,
        "old_price": old_price,
        "new_price": new_price,
        "old_cost_price": old_cost_price,
        "new_cost_price": new_cost_price,
        "price_change_amount": new_price - old_price,
        "old_margin_percentage": round(old_margin, 2),
        "new_margin_percentage": round(new_margin, 2),
        "applied_to_all_branches": True
    }

# ==========================================
# 5. GET PRICE HISTORY (Admin/PM only)
# ==========================================

@router.get("/{product_id}/price-history")
async def get_price_history(
    product_id: UUID,
    current_user: User = Depends(get_product_manager)  # Admin or Purchase Manager only
):
    """
    View complete price history for a product.
    Full audit trail of all price changes.
    """
    
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    history = await PriceHistory.find(
        PriceHistory.product_id == product_id
    ).sort("created_at", -1).to_list() # type: ignore

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
    manager: User = Depends(get_product_manager)
):
    """
    Delete product (Admin/Purchase Manager only).
    Note: Deletes all related price history.
    """
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    
    await product.delete()
    
    # Clean up price history
    await PriceHistory.find(PriceHistory.product_id == product_id).delete_many()
    
    logger.info("Product deleted", extra={
        "product_id": str(product_id),
        "product_name": product.name,
        "deleted_by": str(manager.user_id)
    })
    
    return {"message": "Product deleted successfully"}