from fastapi import APIRouter, HTTPException, Depends, Query, status
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from collections import defaultdict

from app.models.sale import Sale, SaleItem, SaleStatus, PaymentMethod
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.category import Category
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.schemas.sale import (
    SaleCreate, 
    SaleResponse, 
    SaleSummaryResponse,
    SaleCancelRequest,
    ProductInventoryResponse,
    SaleItemResponse
)
from app.dependencies.auth import get_current_user

router = APIRouter()


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def generate_sale_number(branch_code: str) -> str:
    """Generate unique sale number like SALE-LOS-20250125-4567"""
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
    """
    Get all products available at the current user's branch.
    Shows product details + available quantity.
    
    Access: Sales Staff, Store Manager
    """
    
    # Check role
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Sales Staff and Store Managers can view products"
        )
    
    # Check branch assignment
    if not current_user.branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not assigned to a branch"
        )
    
    # Build product query
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
    
    # Get inventory for each product at this branch
    result = []
    for product in products:
        # Find inventory at user's branch
        inventory = await Inventory.find_one({
            "product_id": str(product.id),
            "branch_id": str(current_user.branch_id)
        })
        
        # Only show products with stock > 0
        if inventory and inventory.quantity > 0:
            # Get category name
            category = await Category.get(product.category_id)
            
            result.append({
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "price": product.price,
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
    """
    Quick lookup by barcode - used during scanning at checkout.
    
    Access: Sales Staff, Store Manager
    """
    
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied"
        )
    
    if not current_user.branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not assigned to a branch"
        )
    
    # Find product
    product = await Product.find_one(Product.barcode == barcode)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with barcode '{barcode}' not found"
        )
    
    # Check inventory
    inventory = await Inventory.find_one({
        "product_id": str(product.id),
        "branch_id": str(current_user.branch_id)
    })
    
    if not inventory or inventory.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product '{product.name}' is out of stock at your branch"
        )
    
    # Get category
    category = await Category.get(product.category_id)
    
    return {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "price": product.price,
        "category_name": category.name if category else "Unknown",
        "available_quantity": inventory.quantity,
        "image_url": product.image_url
    }


# ==========================================
# 3. CREATE SALE (CRITICAL ENDPOINT)
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_sale(
    sale_data: SaleCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Create a new sale transaction.
    Automatically deducts inventory from the branch.
    
    Access: Sales Staff, Store Manager
    """
    
    # 1. Check role
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Sales Staff can create sales"
        )
    
    # 2. Check branch assignment
    if not current_user.branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not assigned to a branch"
        )
    
    branch_id_str = str(current_user.branch_id)
    
    # 3. Get branch details
    branch = await Branch.get(current_user.branch_id)
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )
    
    # 4. Process each item and validate stock
    sale_items = []
    subtotal = 0.0
    
    for item in sale_data.items:
        # Get product details
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item.product_id} not found"
            )
        
        # Check inventory at this branch
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })
        
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product '{product.name}' not available at your branch"
            )
        
        # Check sufficient stock
        if inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{product.name}'. Available: {inventory.quantity}, Requested: {item.quantity}"
            )
        
        # Calculate line total
        line_total = item.quantity * product.price
        subtotal += line_total
        
        # Build sale item
        sale_items.append(SaleItem(
            product_id=item.product_id,
            product_name=product.name,
            sku=product.sku,
            barcode=product.barcode,
            quantity_sold=item.quantity,
            unit_price=product.price,
            line_total=line_total
        ))
    
    # 5. Calculate totals
    tax = subtotal * 0.075  # 7.5% VAT
    total_amount = subtotal + tax - sale_data.discount
    
    # Validate discount
    if sale_data.discount > subtotal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discount cannot exceed subtotal"
        )
    
    # Validate payment
    if sale_data.amount_paid < total_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient payment. Total: ₦{total_amount:.2f}, Paid: ₦{sale_data.amount_paid:.2f}"
        )
    
    change_given = sale_data.amount_paid - total_amount
    
    # 6. Generate sale number
    sale_number = generate_sale_number(branch.code)
    
    # 7. Create sale record
    new_sale = Sale(
        sale_number=sale_number,
        branch_id=current_user.branch_id,
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
    
    # 8. CRITICAL: Deduct from inventory
    for item in sale_data.items:
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": branch_id_str
        })
        
        inventory.quantity -= item.quantity
        inventory.updated_at = datetime.utcnow()
        await inventory.save()
        
        print(f"✅ Sale recorded: {product.name} - Sold {item.quantity}, New stock: {inventory.quantity}")
    
    # 9. Return receipt data
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
async def get_sale_details(
    sale_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about a specific sale.
    
    Access Control:
    - Sales Staff: Only their own sales
    - Store Manager: All sales at their branch
    - Finance Manager/Admin: Any sale
    """
    
    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    # Access control
    if current_user.role == UserRole.SALES_STAFF:
        if sale.sold_by != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own sales"
            )
    
    elif current_user.role == UserRole.STORE_MANAGER:
        if str(sale.branch_id) != str(current_user.branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view sales from your branch"
            )
    
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get branch and cashier details
    branch = await Branch.get(sale.branch_id)
    cashier = await User.find_one(User.user_id == sale.sold_by)
    
    return {
        "sale_id": str(sale.id),
        "sale_number": sale.sale_number,
        "branch_name": branch.name if branch else "Unknown",
        "cashier_name": f"{cashier.first_name} {cashier.last_name}" if cashier else "Unknown",
        "items": [
            {
                "product_name": item.product_name,
                "sku": item.sku,
                "barcode": item.barcode,
                "quantity": item.quantity_sold,
                "unit_price": item.unit_price,
                "line_total": item.line_total
            }
            for item in sale.items
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
    """
    List sales with filtering.
    
    Access Control:
    - Sales Staff: Only their own sales
    - Store Manager: All sales at their branch
    - Finance Manager/Admin: All sales
    """
    
    # Build query based on role
    query = {}
    
    if current_user.role == UserRole.SALES_STAFF:
        query["sold_by"] = current_user.user_id
    
    elif current_user.role == UserRole.STORE_MANAGER:
        if not current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your account is not assigned to a branch"
            )
        query["branch_id"] = current_user.branch_id
    
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Apply filters
    if start_date:
        query["created_at"] = {"$gte": start_date}
    if end_date:
        if "created_at" in query:
            query["created_at"]["$lte"] = end_date
        else:
            query["created_at"] = {"$lte": end_date}
    if payment_method:
        query["payment_method"] = payment_method
    
    # Fetch sales
    sales = await Sale.find(query).sort(-Sale.created_at).limit(100).to_list()
    
    # Format response
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
async def get_todays_sales(
    current_user: User = Depends(get_current_user)
):
    """Get today's sales summary for current user's branch"""
    
    if current_user.role not in [UserRole.SALES_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    if not current_user.branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not assigned to a branch"
        )
    
    # Get today's date range
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    # Query
    sales = await Sale.find({
        "branch_id": current_user.branch_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
        "status": SaleStatus.COMPLETED
    }).to_list()
    
    # Calculate summary
    total_sales = len(sales)
    total_revenue = sum(sale.total_amount for sale in sales)
    total_items = sum(sum(item.quantity_sold for item in sale.items) for sale in sales)
    
    # If sales staff, show only their stats
    if current_user.role == UserRole.SALES_STAFF:
        my_sales = [s for s in sales if s.sold_by == current_user.user_id]
        total_sales = len(my_sales)
        total_revenue = sum(sale.total_amount for sale in my_sales)
        total_items = sum(sum(item.quantity_sold for item in sale.items) for sale in my_sales)
    
    avg_transaction = total_revenue / total_sales if total_sales > 0 else 0
    
    return {
        "date": today_start.date(),
        "total_sales": total_sales,
        "total_revenue": round(total_revenue, 2),
        "total_items_sold": total_items,
        "average_transaction_value": round(avg_transaction, 2)
    }


# ==========================================
# 7. CANCEL SALE (Manager Only)
# ==========================================

@router.put("/{sale_id}/cancel", response_model=dict)
async def cancel_sale(
    sale_id: UUID,
    cancel_data: SaleCancelRequest,
    current_user: User = Depends(get_current_user)
):
    """Cancel/void a sale and return items to inventory"""
    
    if current_user.role not in [UserRole.STORE_MANAGER, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Managers and Admins can cancel sales"
        )
    
    # Get sale
    sale = await Sale.get(sale_id)
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    # Check if already cancelled
    if sale.status != SaleStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel. Sale status is '{sale.status}'"
        )
    
    # Store Manager can only cancel sales from their branch
    if current_user.role == UserRole.STORE_MANAGER:
        if str(sale.branch_id) != str(current_user.branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only cancel sales from your branch"
            )
    
    # Return items to inventory
    for item in sale.items:
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": str(sale.branch_id)
        })
        
        if inventory:
            inventory.quantity += item.quantity_sold
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
    
    # Update sale
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