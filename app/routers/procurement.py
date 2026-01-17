from fastapi import APIRouter, HTTPException, Depends, status
from datetime import datetime
from uuid import UUID
from typing import List

from app.models.purchase_order import PurchaseOrder, POStatus, POItem
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.branch import Branch
from app.schemas.procurement import POCreateSchema, ReceiveGoodsSchema, POItemResponse
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole

router = APIRouter(prefix="/procurement", tags=["Procurement"])


# ==========================================
# 1. CREATE PURCHASE ORDER
# ==========================================
@router.post("/create", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_po(
    data: POCreateSchema, 
    current_user: User = Depends(get_current_user)
):
    """
    Create a new Purchase Order.
    Only Purchase Managers can create POs.
    
    Workflow:
    - If total < $5,000: Auto-approved and sent to supplier
    - If total >= $5,000: Pending Finance Manager approval
    """
    
    # 1. Role Check
    if current_user.role != UserRole.PURCHASE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Purchase Managers can create Purchase Orders"
        )

    # 2. Validate Supplier
    supplier = await Supplier.get(data.supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found"
        )
    
    if not supplier.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create PO for inactive supplier"
        )

    # 3. Validate Branch
    branch = await Branch.get(data.target_branch)
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target branch not found"
        )

    # 4. Process Items & Calculate Total
    po_items = []
    total_amount = 0.0

    for item in data.items:
        # Verify product exists
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item.product_id} not found"
            )
        
        line_cost = item.quantity * item.unit_cost
        total_amount += line_cost
        
        po_items.append(POItem(
            product_id=item.product_id,
            ordered_quantity=item.quantity,
            received_quantity=0,
            unit_cost=item.unit_cost,
            total_cost=line_cost
        ))
    
    # 5. Apply Approval Workflow
    if total_amount < 5000:
        status_value = POStatus.SENT
        message = "PO Created and automatically sent to supplier (under $5,000)"
    else:
        status_value = POStatus.PENDING_APPROVAL
        message = "PO Created. Awaiting Finance Manager approval (over $5,000)"

    # 6. Create and Save PO
    po = PurchaseOrder(
        supplier_id=data.supplier_id,
        target_branch=data.target_branch,
        total_amount=total_amount,
        status=status_value,
        items=po_items,
        created_by=current_user.user_id,
        created_at=datetime.utcnow()
    )
    await po.insert()
    
    return {
        "message": message,
        "po_id": str(po.id),
        "total_amount": total_amount,
        "status": status_value,
        "requires_approval": total_amount >= 5000
    }


# ==========================================
# 2. APPROVE PURCHASE ORDER
# ==========================================
@router.put("/{po_id}/approve", response_model=dict)
async def approve_po(
    po_id: UUID, 
    current_user: User = Depends(get_current_user)
):
    """
    Approve a high-value Purchase Order.
    Only Finance Managers can approve.
    """
    
    # 1. Role Check
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Finance Managers can approve orders"
        )

    # 2. Fetch PO
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase Order not found"
        )

    # 3. Validate Status
    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve. Current status is '{po.status}'. Must be 'Pending Approval'"
        )

    # 4. Approve
    po.status = POStatus.APPROVED
    po.approved_by = current_user.user_id
    await po.save()

    return {
        "message": "Purchase Order approved successfully",
        "po_id": str(po.id),
        "status": po.status,
        "approved_by": str(current_user.user_id)
    }


# ==========================================
# 3. REJECT PURCHASE ORDER
# ==========================================
@router.put("/{po_id}/reject", response_model=dict)
async def reject_po(
    po_id: UUID, 
    current_user: User = Depends(get_current_user)
):
    """
    Reject a Purchase Order.
    Only Finance Managers can reject.
    """
    
    # 1. Role Check
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Finance Managers can reject orders"
        )

    # 2. Fetch PO
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase Order not found"
        )

    # 3. Validate Status
    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be rejected"
        )

    # 4. Reject
    po.status = POStatus.REJECTED
    await po.save()

    return {
        "message": "Purchase Order rejected",
        "po_id": str(po.id),
        "status": po.status
    }


# ==========================================
# 4. RECEIVE GOODS (CRITICAL - UPDATES INVENTORY)
# ==========================================
@router.post("/{po_id}/receive", response_model=dict)
async def receive_goods(
    po_id: UUID,
    data: ReceiveGoodsSchema, 
    current_user: User = Depends(get_current_user)
):
    """
    Receive goods from a Purchase Order.
    This is THE endpoint that updates inventory!
    
    Only Store Staff can receive goods.
    """
    
    # 1. Role Check
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Store Staff can receive goods"
        )

    # 2. Fetch PO
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase Order not found"
        )
    
    # 3. Validate PO Status
    if po.status not in [POStatus.SENT, POStatus.APPROVED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive goods. PO Status is '{po.status}'. Must be 'Sent' or 'Approved'"
        )

    # 4. Update Inventory for Each Item
    for received_item in data.items:
        
        # Find matching item in PO
        po_item = next(
            (item for item in po.items if str(item.product_id) == str(received_item.product_id)), 
            None
        )
        
        if not po_item:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {received_item.product_id} not found in this PO"
            )
        
        # Update PO item received quantity
        po_item.received_quantity += received_item.received_qty
        
        # Convert IDs to strings for consistency
        product_id_str = str(received_item.product_id)
        branch_id_str = str(po.target_branch)
        
        # Get product details for inventory record
        product = await Product.get(received_item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {received_item.product_id} not found in database"
            )
        
        # Find or Create Inventory Record
        inventory = await Inventory.find_one({
            "product_id": product_id_str,
            "branch_id": branch_id_str
        })
        
        if inventory:
            # Update existing inventory
            inventory.quantity += received_item.received_qty
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
            
            print(f"✅ Updated inventory: {product.name} - Added {received_item.received_qty}, New total: {inventory.quantity}")
        else:
            # Create new inventory record
            new_inv = Inventory(
                product_id=product_id_str,
                branch_id=branch_id_str,
                quantity=received_item.received_qty,
                product_name=product.name,
                reorder_point=product.low_stock_threshold,
                updated_at=datetime.utcnow()
            )
            await new_inv.insert()
            
            print(f"✅ Created new inventory: {product.name} - Quantity: {received_item.received_qty}")

    # 5. Mark PO as Received
    po.status = POStatus.RECEIVED
    po.receiving_notes = data.notes
    po.received_at = datetime.utcnow()
    await po.save()

    return {
        "message": "Goods received and inventory updated successfully",
        "po_id": str(po.id),
        "status": po.status,
        "items_received": len(data.items)
    }


# ==========================================
# 5. GET ALL PURCHASE ORDERS
# ==========================================
@router.get("/", response_model=List[dict])
async def get_purchase_orders(
    status: POStatus = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get all Purchase Orders.
    Can filter by status.
    """
    
    query = PurchaseOrder.find_all()
    
    if status:
        query = PurchaseOrder.find(PurchaseOrder.status == status)
    
    orders = await query.to_list()
    
    result = []
    for order in orders:
        result.append({
            "id": str(order.id),
            "supplier_id": str(order.supplier_id),
            "target_branch": str(order.target_branch),
            "total_amount": order.total_amount,
            "status": order.status,
            "created_at": order.created_at,
            "created_by": str(order.created_by),
            "items_count": len(order.items)
        })
    
    return result


# ==========================================
# 6. GET SINGLE PURCHASE ORDER
# ==========================================
@router.get("/{po_id}", response_model=dict)
async def Get_detailed_information_about_a_specific_Purchase_Order(
    po_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about a specific Purchase Order.
    
    Access Control:
    - Admin: Any PO, anytime
    - Finance Manager: Any PO, anytime
    - Purchase Manager: Any PO, anytime
    - Store Manager: Only POs for their branch, anytime
    - Store Staff: Only POs for their branch AND only if ready to receive (Sent/Approved status)
    - Sales Staff: DENIED
    """
    
    # 1. Fetch PO
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase Order not found"
        )
    
    # 2. ACCESS CONTROL LOGIC
    
    # Admin - Full access, anytime
    if current_user.role == UserRole.ADMIN:
        pass  # Allowed
    
    # Finance Manager - View any PO, anytime
    elif current_user.role == UserRole.FINANCE:
        pass  # Allowed
    
    # Purchase Manager - View any PO, anytime
    elif current_user.role == UserRole.PURCHASE:
        pass  # Allowed
    
    # Store Manager - Only their branch, any status
    elif current_user.role == UserRole.STORE_MANAGER:
        if not current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your account is not assigned to a branch"
            )
        
        if str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied: You can only view Purchase Orders for your assigned branch"
            )
    
    # Store Staff - Only their branch AND only if ready to receive
    elif current_user.role == UserRole.STORE_STAFF:
        if not current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your account is not assigned to a branch"
            )
        
        # Check 1: Must be for their branch
        if str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied: This order is not for your branch"
            )
        
        # Check 2: Must be ready to receive (Sent or Approved status)
        if po.status not in [POStatus.SENT, POStatus.APPROVED]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access Denied: This order is not ready for receiving. Current status: {po.status}. You can only view orders that are 'Sent' or 'Approved'."
            )
    
    # Sales Staff and any other role - DENIED
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view Purchase Orders"
        )
    
    # 3. Get supplier and branch details
    supplier = await Supplier.get(po.supplier_id)
    branch = await Branch.get(po.target_branch)
    
    # 4. Format items with product names
    items_detail = []
    for item in po.items:
        product = await Product.get(item.product_id)
        items_detail.append({
            "product_id": str(item.product_id),
            "product_name": product.name if product else "Unknown",
            "ordered_quantity": item.ordered_quantity,
            "received_quantity": item.received_quantity,
            "unit_cost": item.unit_cost,
            "total_cost": item.total_cost
        })
    
    # 5. Return response
    return {
        "id": str(po.id),
        "supplier_name": supplier.name if supplier else "Unknown",
        "supplier_id": str(po.supplier_id),
        "target_branch_name": branch.name if branch else "Unknown",
        "target_branch_id": str(po.target_branch),
        "total_amount": po.total_amount,
        "status": po.status,
        "items": items_detail,
        "created_at": po.created_at,
        "created_by": str(po.created_by),
        "approved_by": str(po.approved_by) if po.approved_by else None,
        "received_at": po.received_at,
        "receiving_notes": po.receiving_notes
    }

# ==========================================
# 7. GET PENDING APPROVALS (FOR FINANCE)
# ==========================================
@router.get("/pending/approvals", response_model=List[dict])
async def get_pending_approvals(
    current_user: User = Depends(get_current_user)
):
    """
    Get all POs awaiting Finance Manager approval.
    Only Finance Managers and Admins can access.
    """
    
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied"
        )
    
    pending_orders = await PurchaseOrder.find(
        PurchaseOrder.status == POStatus.PENDING_APPROVAL
    ).to_list()
    
    result = []
    for order in pending_orders:
        supplier = await Supplier.get(order.supplier_id)
        branch = await Branch.get(order.target_branch)
        
        result.append({
            "id": str(order.id),
            "supplier_name": supplier.name if supplier else "Unknown",
            "target_branch": branch.name if branch else "Unknown",
            "total_amount": order.total_amount,
            "created_at": order.created_at,
            "items_count": len(order.items)
        })
    
    return result