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

    if current_user.role != UserRole.PURCHASE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Purchase Managers can create Purchase Orders"
        )

    supplier = await Supplier.get(data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    if not supplier.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create PO for inactive supplier")

    branch = await Branch.get(data.target_branch)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target branch not found")

    po_items = []
    total_amount = 0.0

    for item in data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {item.product_id} not found")

        line_cost = item.quantity * item.unit_cost
        total_amount += line_cost

        po_items.append(POItem(
            product_id=item.product_id,
            ordered_quantity=item.quantity,
            received_quantity=0,
            unit_cost=item.unit_cost,
            total_cost=line_cost
        ))

    if total_amount < 5000:
        status_value = POStatus.SENT
        message = "PO created and automatically sent to supplier (under $5,000)"
    else:
        status_value = POStatus.PENDING_APPROVAL
        message = "PO created. Awaiting Finance Manager approval (over $5,000)"

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
async def approve_po(po_id: UUID, current_user: User = Depends(get_current_user)):
    """Approve a high-value Purchase Order. Only Finance Managers can approve."""

    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied: Only Finance Managers can approve orders")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase Order not found")

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot approve. Current status is '{po.status}'")

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
async def reject_po(po_id: UUID, current_user: User = Depends(get_current_user)):
    """Reject a Purchase Order. Only Finance Managers can reject."""

    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied: Only Finance Managers can reject orders")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase Order not found")

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending orders can be rejected")

    po.status = POStatus.REJECTED
    await po.save()

    return {"message": "Purchase Order rejected", "po_id": str(po.id), "status": po.status}


# ==========================================
# 4. RECEIVE GOODS — COPIES selling_price FROM PRODUCT
# ==========================================
@router.post("/{po_id}/receive", response_model=dict)
async def receive_goods(
    po_id: UUID,
    data: ReceiveGoodsSchema,
    current_user: User = Depends(get_current_user)
):
    """
    Receive goods from a Purchase Order.

    - Updates inventory quantity at the target branch.
    - ✅ Copies selling_price from Product into the Inventory record so
      Sales Staff always read price from Inventory, never directly from Product.

    Only Store Staff from the TARGET BRANCH can receive goods.
    """

    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied: Only Store Staff can receive goods")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase Order not found")

    if not current_user.branch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your account is not assigned to a branch")

    if str(po.target_branch) != str(current_user.branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: This order is for another branch."
        )

    if po.status not in [POStatus.SENT, POStatus.APPROVED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive goods. PO status is '{po.status}'. Must be 'Sent' or 'Approved'"
        )

    for received_item in data.items:
        # Find matching PO line item
        po_item = next(
            (item for item in po.items if str(item.product_id) == str(received_item.product_id)),
            None
        )
        if not po_item:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {received_item.product_id} not found in this PO"
            )

        po_item.received_quantity += received_item.received_qty

        product_id_str = str(received_item.product_id)
        branch_id_str = str(po.target_branch)

        # Fetch product — we need name, threshold AND selling price
        product = await Product.get(received_item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {received_item.product_id} not found in database"
            )

        # ✅ The selling price to stamp on inventory is whatever the Purchase Manager
        #    set on the Product at the time of receiving — global, consistent price.
        selling_price = product.price

        inventory = await Inventory.find_one({
    "product_id": product_id_str,
    "branch_id": branch_id_str
})
        

        if inventory:
            # Update quantity AND refresh selling_price in case PM changed it since last delivery
            inventory.quantity += received_item.received_qty
            inventory.selling_price = selling_price  # ✅ Always sync to latest Product price
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

            print(f"✅ Updated inventory: {product.name} | +{received_item.received_qty} units | price: ₦{selling_price}")
        else:
            # First time this product arrives at this branch — create inventory record
            new_inv = Inventory(
                product_id=product_id_str,
                branch_id=branch_id_str,
                quantity=received_item.received_qty,
                product_name=product.name,
                selling_price=selling_price,       # ✅ Copied from Product.price
                reorder_point=product.low_stock_threshold,
                updated_at=datetime.utcnow()
            )
            await new_inv.insert()

            print(f"✅ Created inventory: {product.name} | {received_item.received_qty} units | price: ₦{selling_price}")

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
    query = PurchaseOrder.find_all()
    if status:
        query = PurchaseOrder.find(PurchaseOrder.status == status)

    orders = await query.to_list()

    return [
        {
            "id": str(o.id),
            "supplier_id": str(o.supplier_id),
            "target_branch": str(o.target_branch),
            "total_amount": o.total_amount,
            "status": o.status,
            "created_at": o.created_at,
            "created_by": str(o.created_by),
            "items_count": len(o.items)
        }
        for o in orders
    ]


# ==========================================
# 6. GET SINGLE PURCHASE ORDER
# ==========================================
@router.get("/{po_id}", response_model=dict)
async def get_purchase_order(
    po_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Access Control:
    - Admin / Finance / Purchase Manager: any PO
    - Store Manager: only POs for their branch
    - Store Staff: only POs for their branch that are Sent/Approved
    - Sales Staff: denied
    """

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase Order not found")

    role = current_user.role

    if role in [UserRole.ADMIN, UserRole.FINANCE, UserRole.PURCHASE]:
        pass  # Full access

    elif role == UserRole.STORE_MANAGER:
        if not current_user.branch_id or str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view POs for your branch")

    elif role == UserRole.STORE_STAFF:
        if not current_user.branch_id or str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This order is not for your branch")
        if po.status not in [POStatus.SENT, POStatus.APPROVED]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Order not ready for receiving. Status: {po.status}")

    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to view Purchase Orders")

    supplier = await Supplier.get(po.supplier_id)
    branch = await Branch.get(po.target_branch)

    items_detail = []
    for item in po.items:
        product = await Product.get(item.product_id)
        items_detail.append({
            "product_id": str(item.product_id),
            "product_name": product.name if product else "Unknown",
            "ordered_quantity": item.ordered_quantity,
            "received_quantity": item.received_quantity,
            "unit_cost": item.unit_cost,
            "total_cost": item.total_cost,
            # ✅ Show the current selling price so staff know what price will land on inventory
            "selling_price": product.price if product else None
        })

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
# 7. GET PENDING APPROVALS (Finance Only)
# ==========================================
@router.get("/pending/approvals", response_model=List[dict])
async def get_pending_approvals(current_user: User = Depends(get_current_user)):

    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied")

    pending_orders = await PurchaseOrder.find(PurchaseOrder.status == POStatus.PENDING_APPROVAL).to_list()

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