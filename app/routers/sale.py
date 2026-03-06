from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta

from app.models.sale import Sale, SaleItem, SaleStatus, PaymentMethod
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.category import Category
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.schemas.sale import (
    SaleCreate,
    SaleCancelRequest,
    ProductInventoryResponse,
)
from app.dependencies.auth import get_current_user

router = APIRouter()


def generate_sale_number(branch_code: str) -> str:
    import random
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(1000, 9999)
    return f"SALE-{branch_code}-{timestamp}-{random_suffix}"


# ==========================================
# 1. VIEW PRODUCTS WITH INVENTORY (For Sales Staff)
# ==========================================

@router.get("/products", response_model=List[ProductInventoryResponse])
async def get_products_for_sale(
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")

    product_query = Product.find_all()
    if category_id:
        product_query = Product.find(Product.category_id == category_id)
    if search:
        product_query = Product.find({
            "$or": [
                {"name": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"barcode": {"$regex": search, "$options": "i"}}
            ]
        })

    products = await product_query.to_list()

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
                # ✅ Use selling_price from Inventory, not price from Product
                "price": inventory.selling_price,
                "category_name": category.name if category else "Unknown",
                "available_quantity": inventory.quantity,
                "image_url": product.image_url
            })

    return result


# ==========================================
# 2. SEARCH PRODUCT BY BARCODE
# ==========================================

@router.get("/products/barcode/{barcode}", response_model=ProductInventoryResponse)
async def search_product_by_barcode(
    barcode: str,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")

    product = await Product.find_one(Product.barcode == barcode)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product with barcode '{barcode}' not found")

    inventory = await Inventory.find_one({
        "product_id": str(product.id),
        "branch_id": str(current_user.branch_id)
    })

    if not inventory or inventory.quantity <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{product.name}' is out of stock at your branch")

    category = await Category.get(product.category_id)

    return {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        # ✅ Use selling_price from Inventory
        "price": inventory.selling_price,
        "category_name": category.name if category else "Unknown",
        "available_quantity": inventory.quantity,
        "image_url": product.image_url
    }


# ==========================================
# 3. CREATE SALE
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_sale(
    sale_data: SaleCreate,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied: Only Sales Staff can create sales")

    if not current_user.branch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")

    branch_id_str = str(current_user.branch_id)

    branch = await Branch.get(current_user.branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    sale_items = []
    subtotal = 0.0

    for item in sale_data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {item.product_id} not found")

        inventory = await Inventory.find_one({
    "product_id": str(item.product_id),
    "branch_id": branch_id_str
})
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{product.name}' is not available at your branch. Stock must be received first."
            )

        if inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{product.name}'. Available: {inventory.quantity}, Requested: {item.quantity}"
            )

        # ✅ Use selling_price from Inventory — this is the price the PM stamped
        #    when goods were received, not the raw Product.price
        unit_price = inventory.selling_price
        if unit_price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Selling price for '{product.name}' has not been set on inventory. Please contact your Purchase Manager."
            )

        line_total = item.quantity * unit_price
        subtotal += line_total

        sale_items.append(SaleItem(
            product_id=item.product_id,
            product_name=product.name,
            sku=product.sku,
            barcode=product.barcode,
            quantity_sold=item.quantity,
            unit_price=unit_price,      # ✅ From Inventory, not Product
            line_total=line_total
        ))

    # Calculate totals
    tax = subtotal * 0.075  # 7.5% VAT
    total_amount = subtotal + tax - sale_data.discount

    if sale_data.discount > subtotal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Discount cannot exceed subtotal")

    if sale_data.amount_paid < total_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient payment. Total: ₦{total_amount:.2f}, Paid: ₦{sale_data.amount_paid:.2f}"
        )

    change_given = sale_data.amount_paid - total_amount
    sale_number = generate_sale_number(branch.code)

    new_sale = Sale(
        sale_number=sale_number,
        branch_id=current_user.branch_id,  # type: ignore
        sold_by=current_user.user_id,
        items=sale_items,
        subtotal=subtotal,
        tax=tax,
        discount=sale_data.discount,
        total_amount=total_amount,
        payment_method=sale_data.payment_method,
        amount_paid=sale_data.amount_paid,
        change_given=change_given,
        status=SaleStatus.COMPLETED,
        till_number=sale_data.till_number,
        notes=sale_data.notes
    )
    await new_sale.insert()

    # Deduct inventory
    for item in sale_data.items:
        inventory = await Inventory.find_one({
    "product_id": str(item.product_id),
    "branch_id": branch_id_str
})
        if inventory:
            inventory.quantity -= item.quantity
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

    return {
        "message": "Sale completed successfully",
        "sale_id": str(new_sale.id),
        "sale_number": new_sale.sale_number,
        "total_amount": total_amount,
        "amount_paid": sale_data.amount_paid,
        "change_given": change_given,
        "items_sold": len(sale_items),
        "payment_method": sale_data.payment_method.value,
        "timestamp": new_sale.created_at
    }


# ==========================================
# 4. GET SALE DETAILS
# ==========================================

@router.get("/{sale_id}", response_model=dict)
async def get_sale_details(sale_id: UUID, current_user: User = Depends(get_current_user)):
    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")

    if current_user.role == UserRole.SALES_STAFF:
        if sale.sold_by != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own sales")
    elif current_user.role == UserRole.STORE_MANAGER:
        if str(sale.branch_id) != str(current_user.branch_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view sales from your branch")
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

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
        "tax": sale.tax,
        "discount": sale.discount,
        "total_amount": sale.total_amount,
        "payment_method": sale.payment_method,
        "amount_paid": sale.amount_paid,
        "change_given": sale.change_given,
        "status": sale.status,
        "till_number": sale.till_number,
        "created_at": sale.created_at,
        "notes": sale.notes
    }


# ==========================================
# 5. LIST SALES
# ==========================================

@router.get("/", response_model=List[dict])
async def list_sales(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    payment_method: Optional[PaymentMethod] = None,
    current_user: User = Depends(get_current_user)
):
    query = {}

    if current_user.role == UserRole.SALES_STAFF:
        query["sold_by"] = current_user.user_id
    elif current_user.role == UserRole.STORE_MANAGER:
        if not current_user.branch_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")
        query["branch_id"] = current_user.branch_id
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if start_date:
        query["created_at"] = {"$gte": start_date}
    if end_date:
        query.setdefault("created_at", {})["$lte"] = end_date
    if payment_method:
        query["payment_method"] = payment_method

    sales = await Sale.find(query).sort(-Sale.created_at).limit(100).to_list()  # type: ignore

    result = []
    for sale in sales:
        cashier = await User.find_one(User.user_id == sale.sold_by)
        branch = await Branch.get(sale.branch_id)
        result.append({
            "sale_id": str(sale.id),
            "sale_number": sale.sale_number,
            "branch_name": branch.name if branch else "Unknown",
            "cashier_name": f"{cashier.first_name} {cashier.last_name}" if cashier else "Unknown",
            "total_amount": sale.total_amount,
            "items_count": len(sale.items),
            "payment_method": sale.payment_method,
            "status": sale.status,
            "created_at": sale.created_at
        })

    return result


# ==========================================
# 6. TODAY'S SALES SUMMARY
# ==========================================

@router.get("/my-branch/today", response_model=dict)
async def get_todays_sales(current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not current_user.branch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")

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
    avg_transaction = total_revenue / total_sales if total_sales > 0 else 0

    return {
        "date": today_start.date(),
        "total_sales": total_sales,
        "total_revenue": round(total_revenue, 2),
        "total_items_sold": total_items,
        "average_transaction_value": round(avg_transaction, 2)
    }


# ==========================================
# 7. CANCEL SALE
# ==========================================

@router.put("/{sale_id}/cancel", response_model=dict)
async def cancel_sale(
    sale_id: UUID,
    cancel_data: SaleCancelRequest,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.STORE_MANAGER, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Store Managers and Admins can cancel sales")

    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")

    if sale.status != SaleStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot cancel. Sale status is '{sale.status}'")

    if current_user.role == UserRole.STORE_MANAGER:
        if str(sale.branch_id) != str(current_user.branch_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only cancel sales from your branch")

    # Return items to inventory
    for item in sale.items:
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": str(current_user.branch_id)
        })
        if inventory:
            inventory.quantity += item.quantity_sold
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

    sale.status = SaleStatus.CANCELLED
    sale.cancelled_by = current_user.user_id
    sale.cancelled_at = datetime.utcnow()
    sale.cancellation_reason = cancel_data.cancellation_reason
    await sale.save()

    return {
        "message": "Sale cancelled successfully",
        "sale_id": str(sale.id),
        "sale_number": sale.sale_number,
        "items_returned": len(sale.items),
        "amount_refunded": sale.total_amount
    }