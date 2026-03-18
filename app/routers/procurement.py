import logging
from fastapi import APIRouter, HTTPException, Depends, status, Request
from datetime import datetime
from uuid import UUID
from typing import List
from app.core.rate_limit import limiter
from app.models.purchase_order import PurchaseOrder, POStatus, POItem
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.branch import Branch
from app.models.system_settings import SystemSettings
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


async def get_settings() -> SystemSettings:
    s = await SystemSettings.find_one({})
    return s if s else SystemSettings()


# ==========================================
# 1. CREATE PURCHASE ORDER
# ==========================================
@router.post("/create", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_po(
    data: POCreateSchema,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Purchase Manager only. Creates a PO for a supplier targeting a specific branch."""
    if current_user.role != UserRole.PURCHASE:
        raise HTTPException(status_code=403, detail="Access Denied: Only Purchase Managers can create Purchase Orders")

    supplier = await Supplier.get(data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not supplier.is_active:
        raise HTTPException(status_code=400, detail="Cannot create PO for inactive supplier")

    branch = await Branch.get(data.target_branch)
    if not branch:
        raise HTTPException(status_code=404, detail="Target branch not found")

    sys_settings = await get_settings()
    threshold = sys_settings.po_approval_threshold

    po_items = []
    total_amount = 0.0

    for item in data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        line_cost = item.quantity * item.unit_cost
        total_amount += line_cost

        po_items.append(POItem(
            product_id=item.product_id,
            ordered_quantity=item.quantity,
            received_quantity=0,
            unit_cost=item.unit_cost,
            total_cost=line_cost
        ))

    if total_amount < threshold:
        status_value = POStatus.SENT
        message = f"PO created and automatically sent to supplier (under {sys_settings.currency_symbol}{threshold:,.0f})"
    else:
        status_value = POStatus.PENDING_APPROVAL
        message = f"PO created. Awaiting Finance Manager approval (over {sys_settings.currency_symbol}{threshold:,.0f})"

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

    await log_action(
        user=current_user,
        action=AuditAction.PO_CREATED,
        module=AuditModule.PROCUREMENT,
        description=f"Created PO for {supplier.name} — {sys_settings.currency_symbol}{total_amount:,.2f} → {branch.name}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "total_amount": total_amount,
            "supplier": supplier.name,
            "branch": branch.name,
            "status": status_value,
            "items_count": len(po_items)
        },
        ip_address=extract_ip(request)
    )

    # ✅ Notify Finance Managers if PO needs approval
    if status_value == POStatus.PENDING_APPROVAL:
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
            logger.error(f"PO pending approval email failed: {e}")

    return {
        "message": message,
        "po_id": str(po.id),
        "total_amount": total_amount,
        "status": status_value,
        "requires_approval": total_amount >= threshold
    }


# ==========================================
# 2. APPROVE PURCHASE ORDER
# ==========================================
@router.put("/{po_id}/approve", response_model=dict)
async def approve_po(
    po_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Finance Manager only. Approves a pending PO."""
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access Denied: Only Finance Managers can approve orders")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve. Current status is '{po.status.value}'"
        )

    po.status = POStatus.APPROVED
    po.approved_by = current_user.user_id
    await po.save()

    supplier = await Supplier.get(po.supplier_id)

    await log_action(
        user=current_user,
        action=AuditAction.PO_APPROVED,
        module=AuditModule.PROCUREMENT,
        description=f"Approved PO worth ₦{po.total_amount:,.2f} from {supplier.name if supplier else 'Unknown'}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "total_amount": po.total_amount,
            "supplier": supplier.name if supplier else None
        },
        ip_address=extract_ip(request)
    )

    # ✅ Notify the Purchase Manager who created the PO
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
        "message": "Purchase Order approved successfully",
        "po_id": str(po.id),
        "status": po.status.value,
        "approved_by": str(current_user.user_id)
    }


# ==========================================
# 3. REJECT PURCHASE ORDER
# ==========================================
@router.put("/{po_id}/reject", response_model=dict)
async def reject_po(
    po_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Finance Manager only. Rejects a pending PO."""
    if current_user.role not in [UserRole.FINANCE, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access Denied: Only Finance Managers can reject orders")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject. Current status is '{po.status.value}'"
        )

    po.status = POStatus.REJECTED
    await po.save()

    supplier = await Supplier.get(po.supplier_id)

    await log_action(
        user=current_user,
        action=AuditAction.PO_REJECTED,
        module=AuditModule.PROCUREMENT,
        description=f"Rejected PO worth ₦{po.total_amount:,.2f} from {supplier.name if supplier else 'Unknown'}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={"total_amount": po.total_amount},
        ip_address=extract_ip(request)
    )

    # ✅ Notify the Purchase Manager who created the PO
    try:
        creator = await User.find_one(User.user_id == po.created_by)
        if creator:
            await send_po_rejected_email(
                email_to=creator.email,
                first_name=creator.first_name,
                supplier_name=supplier.name if supplier else "Unknown",
                amount=po.total_amount,
                po_id=str(po.id),
                reason="No reason provided"
            )
    except Exception as e:
        logger.error(f"PO rejected email failed: {e}")

    return {
        "message": "Purchase Order rejected",
        "po_id": str(po.id),
        "status": po.status.value
    }


# ==========================================
# 4. RECEIVE GOODS
# ==========================================
@router.post("/{po_id}/receive", response_model=dict)
async def receive_goods(
    po_id: UUID,
    data: ReceiveGoodsSchema,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Store Staff and Store Manager only."""
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=403, detail="Access Denied: Only Store Staff can receive goods")

    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="Your account is not assigned to a branch")

    if str(po.target_branch) != str(current_user.branch_id):
        raise HTTPException(status_code=403, detail="Access Denied: This order is for another branch.")

    if po.status not in [POStatus.SENT, POStatus.APPROVED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive goods. PO status is '{po.status.value}'. Must be 'Sent' or 'Approved'"
        )

    received_items_summary = []

    for received_item in data.items:
        po_item = next(
            (item for item in po.items if str(item.product_id) == str(received_item.product_id)),
            None
        )
        if not po_item:
            raise HTTPException(
                status_code=400,
                detail=f"Product {received_item.product_id} not found in this PO"
            )

        po_item.received_quantity += received_item.received_qty

        product_id_str = str(received_item.product_id)
        branch_id_str = str(po.target_branch)

        product = await Product.get(received_item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {received_item.product_id} not found")

        selling_price = product.price

        inventory = await Inventory.find_one({
            "product_id": product_id_str,
            "branch_id": branch_id_str
        })

        if inventory:
            inventory.quantity += received_item.received_qty
            inventory.selling_price = selling_price
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
        else:
            new_inv = Inventory(
                product_id=product_id_str,
                branch_id=branch_id_str,
                quantity=received_item.received_qty,
                product_name=product.name,
                selling_price=selling_price,
                reorder_point=product.low_stock_threshold,
                updated_at=datetime.utcnow()
            )
            await new_inv.insert()

        received_items_summary.append(f"{product.name} x{received_item.received_qty}")

    po.status = POStatus.RECEIVED
    po.receiving_notes = data.notes
    po.received_at = datetime.utcnow()
    await po.save()

    branch = await Branch.get(po.target_branch)

    await log_action(
        user=current_user,
        action=AuditAction.PO_RECEIVED,
        module=AuditModule.PROCUREMENT,
        description=f"Received goods for PO at {branch.name if branch else 'Unknown'}: {', '.join(received_items_summary)}",
        target_id=str(po.id),
        target_type="purchase_order",
        metadata={
            "items_received": len(data.items),
            "branch": branch.name if branch else None,
            "items": received_items_summary
        },
        branch_name=branch.name if branch else None,
        ip_address=extract_ip(request)
    )

    return {
        "message": "Goods received and inventory updated successfully",
        "po_id": str(po.id),
        "status": po.status.value,
        "items_received": len(data.items)
    }