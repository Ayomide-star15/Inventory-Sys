# app/routers/procurement.py

import logging
from fastapi import APIRouter, HTTPException, Depends, status, Request, Query
from datetime import datetime
from uuid import UUID
from typing import List, Optional

from app.core.rate_limit import limiter
from app.models.purchase_order import PurchaseOrder, POStatus, POItem
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.branch import Branch
from app.schemas.procurement import POCreateSchema, ReceiveGoodsSchema
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip
from app.core.email import (
    send_po_pending_email,
    send_po_approved_email,
    send_po_rejected_email
)

router = APIRouter(prefix="/procurement", tags=["Procurement"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _require_finance_or_admin(user: User):
    if user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Access Denied: Only Finance Managers can perform this action."
        )

def _require_purchase_or_admin(user: User):
    if user.role not in [UserRole.PURCHASE, UserRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Access Denied: Only Purchase Managers can perform this action."
        )


# ─────────────────────────────────────────────────────────────
# 1. LIST ALL PURCHASE ORDERS
# ─────────────────────────────────────────────────────────────

@router.get("/", response_model=dict)
async def list_purchase_orders(
    status_filter: Optional[POStatus] = Query(
        default=None,
        alias="status",
        description="Filter by PO status. Leave blank for all."
    ),
    branch_id: Optional[UUID] = None,
    supplier_id: Optional[UUID] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user)
):
    """
     List purchase orders with optional filters.

    Access Control:
    - Finance Manager / Admin:
      Can view all Purchase Orders system-wide.

    - Purchase Manager:
      Can only view Purchase Orders they created.

    - Store Manager:
      Can only view Purchase Orders for their assigned branch.

    Permissions:
     FINANCE
     ADMIN
     PURCHASE
     STORE_MANAGER
    """

    query = {}

    if current_user.role == UserRole.PURCHASE:
        query["created_by"] = current_user.user_id

    elif current_user.role in [UserRole.STORE_MANAGER]:
        if not current_user.branch_id:
            raise HTTPException(400, "Your account has no branch assigned.")
        query["target_branch"] = current_user.branch_id

    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(403, "Access Denied.")

    if status_filter:
        query["status"] = status_filter
    if branch_id and current_user.role in [UserRole.FINANCE, UserRole.ADMIN]:
        query["target_branch"] = branch_id
    if supplier_id and current_user.role in [UserRole.FINANCE, UserRole.ADMIN, UserRole.PURCHASE]:
        query["supplier_id"] = supplier_id

    skip = (page - 1) * limit
    pos = await PurchaseOrder.find(query).sort(
        -PurchaseOrder.created_at   # type: ignore
    ).skip(skip).limit(limit).to_list()

    total = await PurchaseOrder.find(query).count()

    suppliers = await Supplier.find_all().to_list()
    branches  = await Branch.find_all().to_list()
    supplier_map = {str(s.id): s.name for s in suppliers}
    branch_map   = {str(b.id): b.name for b in branches}

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "items": [
            {
                "po_id":         str(po.id),
                "supplier_name": supplier_map.get(str(po.supplier_id), "Unknown"),
                "supplier_id":   str(po.supplier_id),
                "target_branch": branch_map.get(str(po.target_branch), "Unknown"),
                "branch_id":     str(po.target_branch),
                "total_amount":  round(po.total_amount, 2),
                "status":        po.status.value,
                "items_count":   len(po.items),
                "created_by":    str(po.created_by),
                "created_at":    po.created_at,
                "approved_by":   str(po.approved_by) if po.approved_by else None,
                "received_at":   po.received_at,
            }
            for po in pos
        ]
    }


# ─────────────────────────────────────────────────────────────
# 2. PENDING APPROVALS — Finance Manager action list
# ─────────────────────────────────────────────────────────────

@router.get("/pending-approval", response_model=dict)
async def get_pending_approvals(
    current_user: User = Depends(get_current_user)
):
    """
Retrieve all Purchase Orders awaiting approval.

    Access Control:
    - Finance Manager:
      Can view all pending approvals.

    - Admin:
      Can view all pending approvals.

    Permissions:
     FINANCE
     ADMIN
    """
    _require_finance_or_admin(current_user)

    pos = await PurchaseOrder.find(
        PurchaseOrder.status == POStatus.PENDING_APPROVAL
    ).sort(-PurchaseOrder.created_at).to_list()     # type: ignore

    suppliers    = await Supplier.find_all().to_list()
    branches     = await Branch.find_all().to_list()
    supplier_map = {str(s.id): s.name for s in suppliers}
    branch_map   = {str(b.id): b.name for b in branches}

    result = []
    for po in pos:
        items_detail = []
        for item in po.items:
            product = await Product.get(item.product_id)
            items_detail.append({
                "product_id":       str(item.product_id),
                "product_name":     product.name if product else "Unknown",
                "sku":              product.sku  if product else "—",
                "ordered_quantity": item.ordered_quantity,
                "unit_cost":        item.unit_cost,
                "total_cost":       round(item.total_cost, 2),
            })

        creator = await User.find_one(User.user_id == po.created_by)

        result.append({
            "po_id":            str(po.id),
            "supplier_name":    supplier_map.get(str(po.supplier_id), "Unknown"),
            "supplier_id":      str(po.supplier_id),
            "target_branch":    branch_map.get(str(po.target_branch), "Unknown"),
            "branch_id":        str(po.target_branch),
            "total_amount":     round(po.total_amount, 2),
            "status":           po.status.value,
            "items":            items_detail,
            "items_count":      len(po.items),
            "created_by_name":  f"{creator.first_name} {creator.last_name}" if creator else "Unknown",
            "created_at":       po.created_at,
        })

    return {
        "count":       len(result),
        "total_value": round(sum(p["total_amount"] for p in result), 2),
        "orders":      result
    }


# ─────────────────────────────────────────────────────────────
# 3. GET SINGLE PO
# ─────────────────────────────────────────────────────────────

@router.get("/{po_id}", response_model=dict)
async def get_purchase_order(
    po_id: UUID,
    current_user: User = Depends(get_current_user)
):
    """
     Retrieve a single Purchase Order by ID.

    Access Control:

    - Purchase Manager:
      Can view only Purchase Orders they created.

    - Store Manager:
      Can only view Purchase Orders for their assigned branch.

    - Finance Manager:
      Can view any Purchase Order.

    - Admin:
      Can view any Purchase Order
    """
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(404, "Purchase Order not found.")

    if current_user.role == UserRole.PURCHASE:
        if po.created_by != current_user.user_id:
            raise HTTPException(403, "You can only view your own Purchase Orders.")
    elif current_user.role in [UserRole.STORE_MANAGER]:
        if str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(403, "This Purchase Order is for a different branch.")
    elif current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(403, "Access Denied.")

    supplier = await Supplier.get(po.supplier_id)
    branch   = await Branch.get(po.target_branch)
    creator  = await User.find_one(User.user_id == po.created_by)
    approver = None
    if po.approved_by:
        approver = await User.find_one(User.user_id == po.approved_by)

    items_detail = []
    for item in po.items:
        product = await Product.get(item.product_id)
        items_detail.append({
            "product_id":        str(item.product_id),
            "product_name":      product.name if product else "Unknown",
            "sku":               product.sku  if product else "—",
            "ordered_quantity":  item.ordered_quantity,
            "received_quantity": item.received_quantity,
            "unit_cost":         item.unit_cost,
            "total_cost":        round(item.total_cost, 2),
        })

    return {
        "po_id":   str(po.id),
        "status":  po.status.value,
        "supplier": {
            "id":    str(po.supplier_id),
            "name":  supplier.name  if supplier else "Unknown",
            "phone": supplier.phone if supplier else None,
        },
        "target_branch": {
            "id":   str(po.target_branch),
            "name": branch.name if branch else "Unknown",
        },
        "items":           items_detail,
        "items_count":     len(items_detail),
        "total_amount":    round(po.total_amount, 2),
        "created_by":      f"{creator.first_name} {creator.last_name}" if creator else "Unknown",
        "created_at":      po.created_at,
        "approved_by":     f"{approver.first_name} {approver.last_name}" if approver else None,
        "received_at":     po.received_at,
        "receiving_notes": po.receiving_notes,
    }


# ─────────────────────────────────────────────────────────────
# 4. CREATE PO — Purchase Manager only
# ─────────────────────────────────────────────────────────────

@router.post("/create", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_po(
    data: POCreateSchema,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Create a new Purchase Order.

    Access Control:

    - Purchase Manager:
      Can create Purchase Orders.

    - Admin:
      Can create Purchase Orders.
    """
    _require_purchase_or_admin(current_user)

    supplier = await Supplier.get(data.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found.")
    if not supplier.is_active:
        raise HTTPException(400, "Cannot create a PO for an inactive supplier.")

    branch = await Branch.get(data.target_branch)
    if not branch:
        raise HTTPException(404, "Target branch not found.")
    if not branch.is_active:
        raise HTTPException(400, "Cannot create a PO for an inactive branch.")

    po_items = []
    total_amount = 0.0

    for item in data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found.")
        if item.unit_cost <= 0:
            raise HTTPException(400, f"Cost price for '{product.name}' must be greater than zero.")

        line_cost = item.quantity * item.unit_cost
        total_amount += line_cost
        po_items.append(POItem(
            product_id=item.product_id,
            ordered_quantity=item.quantity,
            received_quantity=0,
            unit_cost=item.unit_cost,
            total_cost=line_cost
        ))

    po = PurchaseOrder(
        supplier_id=data.supplier_id,
        target_branch=data.target_branch,
        total_amount=total_amount,
        status=POStatus.PENDING_APPROVAL,
        items=po_items,
        created_by=current_user.user_id,
        created_at=datetime.utcnow()
    )
    await po.insert()

    await log_action(   # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.PO_CREATED,
        module=AuditModule.PROCUREMENT,
        description=f"Created PO for {supplier.name} — "
                    f"₦{total_amount:,.2f} → {branch.name} (awaiting Finance approval)",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "total_amount": total_amount,
            "supplier": supplier.name,
            "branch": branch.name,
            "items_count": len(po_items),
        },
        ip_address=extract_ip(request)
    )

    try:
        finance_managers = await User.find(
            User.role == UserRole.FINANCE,
            User.is_active == True
        ).to_list()
        for fm in finance_managers:
            await send_po_pending_email(
                email_to=fm.email,
                first_name=fm.first_name,
                supplier_name=supplier.name,
                amount=total_amount,
                po_id=str(po.id)
            )
    except Exception as e:
        logger.error(f"PO pending email failed: {e}")

    return {
        "message": "Purchase Order created and sent to Finance Manager for approval.",
        "po_id": str(po.id),
        "total_amount": round(total_amount, 2),
        "status": POStatus.PENDING_APPROVAL,
        "requires_approval": True,
        "note": "All purchase orders require Finance Manager approval regardless of amount."
    }


# ─────────────────────────────────────────────────────────────
# 5. APPROVE — Finance Manager only
# ─────────────────────────────────────────────────────────────

@router.put("/{po_id}/approve", response_model=dict)
async def approve_po(
    po_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
     Approve a pending Purchase Order.

    Access Control:

    - Finance Manager:
      Can approve Purchase Orders.

    - Admin:
      Can approve Purchase Orders.
    """
    _require_finance_or_admin(current_user)

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(404, "Purchase Order not found.")
    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            400,
            f"Cannot approve. Status is '{po.status.value}'. "
            f"Only Pending Approval orders can be approved."
        )

    po.status = POStatus.APPROVED
    po.approved_by = current_user.user_id
    await po.save()

    supplier = await Supplier.get(po.supplier_id)
    branch   = await Branch.get(po.target_branch)

    await log_action(   # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.PO_APPROVED,
        module=AuditModule.PROCUREMENT,
        description=f"Approved PO worth ₦{po.total_amount:,.2f} from "
                    f"{supplier.name if supplier else 'Unknown'} "
                    f"→ {branch.name if branch else 'Unknown'}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "total_amount": po.total_amount,
            "supplier": supplier.name if supplier else None,
            "branch": branch.name if branch else None,
        },
        ip_address=extract_ip(request)
    )

    try:
        creator = await User.find_one(User.user_id == po.created_by)
        if creator:
            await send_po_approved_email(
                email_to=creator.email,
                first_name=creator.first_name,
                supplier_name=supplier.name if supplier else "Unknown",
                amount=po.total_amount,
                po_id=str(po.id)
            )
    except Exception as e:
        logger.error(f"PO approved email failed: {e}")

    return {
        "message": "Purchase Order approved successfully.",
        "po_id": str(po.id),
        "status": po.status.value,
        "approved_by": f"{current_user.first_name} {current_user.last_name}",
        "total_amount": po.total_amount,
        "note": "Store Manager at the target branch can now receive the goods."
    }


# ─────────────────────────────────────────────────────────────
# 6. REJECT — Finance Manager only
# ─────────────────────────────────────────────────────────────

@router.put("/{po_id}/reject", response_model=dict)
async def reject_po(
    po_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
     Reject a pending Purchase Order.

    Access Control:

    - Finance Manager:
      Can reject Purchase Orders.

    - Admin:
      Can reject Purchase Orders.
    """
    _require_finance_or_admin(current_user)

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(404, "Purchase Order not found.")
    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(400, f"Cannot reject. Status is '{po.status.value}'.")

    po.status = POStatus.REJECTED
    await po.save()

    supplier = await Supplier.get(po.supplier_id)

    await log_action(   # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.PO_REJECTED,
        module=AuditModule.PROCUREMENT,
        description=f"Rejected PO worth ₦{po.total_amount:,.2f} from "
                    f"{supplier.name if supplier else 'Unknown'}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={"total_amount": po.total_amount},
        ip_address=extract_ip(request)
    )

    try:
        creator = await User.find_one(User.user_id == po.created_by)
        if creator:
            await send_po_rejected_email(
                email_to=creator.email,
                first_name=creator.first_name,
                supplier_name=supplier.name if supplier else "Unknown",
                amount=po.total_amount,
                po_id=str(po.id),
                reason="Rejected by Finance Manager"
            )
    except Exception as e:
        logger.error(f"PO rejected email failed: {e}")

    return {
        "message": "Purchase Order rejected.",
        "po_id": str(po.id),
        "status": po.status.value
    }


# ─────────────────────────────────────────────────────────────
# 7. RECEIVE GOODS — Store Manager / Admin
# ─────────────────────────────────────────────────────────────

@router.post("/{po_id}/receive", response_model=dict)
async def receive_goods(
    po_id: UUID,
    data: ReceiveGoodsSchema,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Receive goods and update inventory.

    Access Control:

    - Store Manager:
      Can receive goods only for their assigned branch.

    - Admin:
      Can receive goods for branch.

    """
    # FIX: admin can receive goods at any branch
    if current_user.role not in [UserRole.STORE_MANAGER, UserRole.ADMIN]:
        raise HTTPException(403, "Access Denied: Only Store Staff can receive goods.")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(404, "Purchase Order not found.")

    # Non-admin: must have a branch and it must match the PO target
    if current_user.role != UserRole.ADMIN:
        if not current_user.branch_id:
            raise HTTPException(400, "Your account has no branch assigned.")
        if str(po.target_branch) != str(current_user.branch_id):
            raise HTTPException(403, "This order is for a different branch.")

    if po.status != POStatus.APPROVED:
        raise HTTPException(
            400,
            f"Cannot receive goods. PO status is '{po.status.value}'. "
            f"Must be Approved by Finance Manager first."
        )

    received_items_summary = []

    for received_item in data.items:
        po_item = next(
            (i for i in po.items if str(i.product_id) == str(received_item.product_id)),
            None
        )
        if not po_item:
            raise HTTPException(400, f"Product {received_item.product_id} not in this PO.")

        po_item.received_quantity += received_item.received_qty

        product = await Product.get(received_item.product_id)
        if not product:
            raise HTTPException(404, f"Product {received_item.product_id} not found.")

        selling_price = product.price or 0.0

        inventory = await Inventory.find_one({
            "product_id": str(received_item.product_id),
            "branch_id":  str(po.target_branch)
        })

        if inventory:
            inventory.quantity      += received_item.received_qty
            inventory.selling_price  = selling_price
            inventory.updated_at     = datetime.utcnow()
            await inventory.save()
        else:
            await Inventory(
                product_id=str(received_item.product_id),
                branch_id=str(po.target_branch),
                quantity=received_item.received_qty,
                product_name=product.name,
                selling_price=selling_price,
                reorder_point=product.low_stock_threshold,
                updated_at=datetime.utcnow()
            ).insert()

        received_items_summary.append(f"{product.name} x{received_item.received_qty}")

    po.status          = POStatus.RECEIVED
    po.receiving_notes = data.notes
    po.received_at     = datetime.utcnow()
    await po.save()

    branch = await Branch.get(po.target_branch)

    await log_action(   # type: ignore[func-returns-value]
        user=current_user,
        action=AuditAction.PO_RECEIVED,
        module=AuditModule.PROCUREMENT,
        description=f"Received goods for PO at "
                    f"{branch.name if branch else 'Unknown'}: "
                    f"{', '.join(received_items_summary)}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "items_received": len(data.items),
            "branch": branch.name if branch else None,
            "items": received_items_summary,
        },
        branch_name=branch.name if branch else None,
        ip_address=extract_ip(request)
    )

    unpriced = [
        p for p in [await Product.get(i.product_id) for i in data.items]
        if p and p.price is None
    ]

    return {
        "message": "Goods received and inventory updated successfully.",
        "po_id": str(po.id),
        "status": po.status.value,
        "items_received": len(data.items),
        "warning": (
            f"{len(unpriced)} product(s) have no selling price set. "
            f"Finance Manager should price them before they appear at checkout."
            if unpriced else None
        )
    }