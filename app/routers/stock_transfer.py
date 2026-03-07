from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole
from app.models.stock_transfer import StockTransfer, TransferStatus
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.branch import Branch
from app.schemas.stock_transfer import (
    StockTransferCreate, StockTransferApprove, StockTransferShip,
    StockTransferReceive, StockTransferReject
)
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip

router = APIRouter(prefix="/stock-transfers", tags=["Stock Transfers"])


# ==========================================
# 1. CREATE TRANSFER
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_transfer_request(
    transfer_data: StockTransferCreate,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(status_code=403, detail="Only Store Managers can create transfer requests")

    if str(transfer_data.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(status_code=403, detail="You can only transfer FROM your assigned branch")

    from_branch = await Branch.get(transfer_data.from_branch_id)
    to_branch = await Branch.get(transfer_data.to_branch_id)

    if not from_branch or not to_branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    if transfer_data.from_branch_id == transfer_data.to_branch_id:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same branch")

    items = []
    for item in transfer_data.items:
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": str(transfer_data.from_branch_id)
        })

        if not inventory or inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {product.name}. Available: {inventory.quantity if inventory else 0}"
            )

        items.append({
            "product_id": str(item.product_id),
            "product_name": product.name,
            "quantity_requested": item.quantity,
            "quantity_approved": 0,
            "quantity_sent": 0,
            "quantity_received": 0
        })

    new_transfer = StockTransfer(
        from_branch_id=transfer_data.from_branch_id,
        to_branch_id=transfer_data.to_branch_id,
        items=items,
        reason=transfer_data.reason,
        priority=transfer_data.priority,
        notes=transfer_data.notes,
        requested_by=current_user.user_id,
        status=TransferStatus.PENDING
    )
    await new_transfer.insert()

    await log_action(
        user=current_user,
        action=AuditAction.TRANSFER_REQUESTED,
        module=AuditModule.TRANSFERS,
        description=f"Requested stock transfer from {from_branch.name} to {to_branch.name} ({len(items)} products)",
        target_id=str(new_transfer.id),
        target_type="stock_transfer",
        metadata={
            "from_branch": from_branch.name,
            "to_branch": to_branch.name,
            "items_count": len(items),
            "priority": transfer_data.priority,
            "reason": transfer_data.reason
        },
        branch_name=from_branch.name,
        ip_address=extract_ip(request)
    )

    return {
        "message": "Transfer request created successfully",
        "transfer_id": str(new_transfer.id),
        "from_branch": from_branch.name,
        "to_branch": to_branch.name,
        "status": new_transfer.status,
        "items_count": len(items)
    }


# ==========================================
# 2. APPROVE TRANSFER
# ==========================================

@router.put("/{transfer_id}/approve", response_model=dict)
async def approve_transfer(
    transfer_id: UUID,
    approval_data: StockTransferApprove,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(status_code=403, detail="Only Store Managers can approve transfers")

    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if str(transfer.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(status_code=403, detail="Only the source branch manager can approve this transfer")

    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Cannot approve. Transfer status is '{transfer.status}'")

    if approval_data.approved_quantities:
        for approval in approval_data.approved_quantities:
            for item in transfer.items:
                if item["product_id"] == str(approval.product_id):
                    # ✅ FIXED: Validate approved quantity doesn't exceed requested
                    if approval.quantity > item["quantity_requested"]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Approved quantity ({approval.quantity}) cannot exceed "
                                   f"requested quantity ({item['quantity_requested']}) for {item['product_name']}"
                        )
                    item["quantity_approved"] = approval.quantity
    else:
        for item in transfer.items:
            item["quantity_approved"] = item["quantity_requested"]

    transfer.status = TransferStatus.APPROVED
    transfer.approved_by = current_user.user_id
    transfer.approved_at = datetime.utcnow()
    if approval_data.notes:
        transfer.notes = approval_data.notes

    await transfer.save()

    await log_action(
        user=current_user,
        action=AuditAction.TRANSFER_APPROVED,
        module=AuditModule.TRANSFERS,
        description=f"Approved stock transfer of {len(transfer.items)} products",
        target_id=str(transfer.id),
        target_type="stock_transfer",
        ip_address=extract_ip(request)
    )

    return {
        "message": "Transfer approved successfully",
        "transfer_id": str(transfer.id),
        "status": transfer.status
    }


# ==========================================
# 3. SHIP TRANSFER
# ==========================================

@router.put("/{transfer_id}/ship", response_model=dict)
async def ship_transfer(
    transfer_id: UUID,
    ship_data: StockTransferShip,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=403, detail="Only Store Staff can ship transfers")

    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if str(transfer.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(status_code=403, detail="Only source branch staff can ship this transfer")

    if transfer.status != TransferStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot ship. Transfer must be 'Approved'. Current: '{transfer.status}'"
        )

    for ship_item in ship_data.actual_quantities:
        product_id = str(ship_item.product_id)
        quantity_sent = ship_item.quantity

        for item in transfer.items:
            if item["product_id"] == product_id:
                item["quantity_sent"] = quantity_sent

        inventory = await Inventory.find_one({
            "product_id": product_id,
            "branch_id": str(transfer.from_branch_id)
        })

        if inventory:
            if inventory.quantity < quantity_sent:
                raise HTTPException(status_code=400, detail="Insufficient stock to ship")
            inventory.quantity -= quantity_sent
            inventory.updated_at = datetime.utcnow()
            await inventory.save()

    transfer.status = TransferStatus.IN_TRANSIT
    transfer.shipped_by = current_user.user_id
    transfer.shipped_at = datetime.utcnow()
    transfer.shipping_notes = ship_data.shipping_notes
    await transfer.save()

    await log_action(
        user=current_user,
        action=AuditAction.TRANSFER_SHIPPED,
        module=AuditModule.TRANSFERS,
        description=f"Shipped stock transfer — {len(ship_data.actual_quantities)} products dispatched",
        target_id=str(transfer.id),
        target_type="stock_transfer",
        ip_address=extract_ip(request)
    )

    return {
        "message": "Transfer shipped successfully",
        "transfer_id": str(transfer.id),
        "status": transfer.status
    }


# ==========================================
# 4. RECEIVE TRANSFER
# ==========================================

@router.put("/{transfer_id}/receive", response_model=dict)
async def receive_transfer(
    transfer_id: UUID,
    receive_data: StockTransferReceive,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(status_code=403, detail="Only Store Staff can receive transfers")

    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if str(transfer.to_branch_id) != str(current_user.branch_id):
        raise HTTPException(status_code=403, detail="Only destination branch staff can receive this transfer")

    if transfer.status != TransferStatus.IN_TRANSIT:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive. Transfer must be 'In Transit'. Current: '{transfer.status}'"
        )

    for receive_item in receive_data.received_quantities:
        product_id = str(receive_item.product_id)
        quantity_received = receive_item.quantity

        for item in transfer.items:
            if item["product_id"] == product_id:
                item["quantity_received"] = quantity_received

        inventory = await Inventory.find_one({
            "product_id": product_id,
            "branch_id": str(transfer.to_branch_id)
        })

        if inventory:
            inventory.quantity += quantity_received
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
        else:
            product = await Product.get(UUID(product_id))
            source_inventory = await Inventory.find_one({
                "product_id": product_id,
                "branch_id": str(transfer.from_branch_id)
            })
            selling_price = source_inventory.selling_price if source_inventory else (product.price if product else 0.0)

            new_inventory = Inventory(
                product_id=product_id,
                branch_id=str(transfer.to_branch_id),
                quantity=quantity_received,
                product_name=product.name if product else "Unknown",
                selling_price=selling_price,
                reorder_point=product.low_stock_threshold if product else 10
            )
            await new_inventory.insert()

    transfer.status = TransferStatus.COMPLETED
    transfer.received_by = current_user.user_id
    transfer.received_at = datetime.utcnow()
    transfer.receiving_notes = receive_data.receiving_notes
    await transfer.save()

    await log_action(
        user=current_user,
        action=AuditAction.TRANSFER_RECEIVED,
        module=AuditModule.TRANSFERS,
        description=f"Received stock transfer — {len(receive_data.received_quantities)} products received",
        target_id=str(transfer.id),
        target_type="stock_transfer",
        ip_address=extract_ip(request)
    )

    return {
        "message": "Transfer received successfully",
        "transfer_id": str(transfer.id),
        "status": transfer.status
    }


# ==========================================
# 5. REJECT TRANSFER
# ==========================================

@router.put("/{transfer_id}/reject", response_model=dict)
async def reject_transfer(
    transfer_id: UUID,
    reject_data: StockTransferReject,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(status_code=403, detail="Only Store Managers can reject transfers")

    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if str(current_user.branch_id) not in [str(transfer.from_branch_id), str(transfer.to_branch_id)]:
        raise HTTPException(status_code=403, detail="Access denied")

    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(status_code=400, detail="Can only reject pending transfers")

    transfer.status = TransferStatus.REJECTED
    transfer.rejection_reason = reject_data.rejection_reason
    await transfer.save()

    await log_action(
        user=current_user,
        action=AuditAction.TRANSFER_REJECTED,
        module=AuditModule.TRANSFERS,
        description=f"Rejected transfer. Reason: {reject_data.rejection_reason}",
        target_id=str(transfer.id),
        target_type="stock_transfer",
        metadata={"rejection_reason": reject_data.rejection_reason},
        ip_address=extract_ip(request)
    )

    return {
        "message": "Transfer rejected",
        "transfer_id": str(transfer.id),
        "status": transfer.status
    }


# ==========================================
# 6. GET TRANSFER DETAILS
# ==========================================

@router.get("/{transfer_id}", response_model=dict)
async def get_transfer_details(
    transfer_id: UUID,
    current_user: User = Depends(get_current_user)
):
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if current_user.role != UserRole.ADMIN:
        user_branch = str(current_user.branch_id)
        if user_branch not in [str(transfer.from_branch_id), str(transfer.to_branch_id)]:
            raise HTTPException(status_code=403, detail="You can only view transfers involving your branch")

    from_branch = await Branch.get(transfer.from_branch_id)
    to_branch = await Branch.get(transfer.to_branch_id)
    requester = await User.find_one(User.user_id == transfer.requested_by)

    return {
        "transfer_id": str(transfer.id),
        "from_branch": from_branch.name if from_branch else "Unknown",
        "to_branch": to_branch.name if to_branch else "Unknown",
        "status": transfer.status,
        "priority": transfer.priority,
        "items": transfer.items,
        "reason": transfer.reason,
        "notes": transfer.notes,
        "requested_by": f"{requester.first_name} {requester.last_name}" if requester else "Unknown",
        "created_at": transfer.created_at,
        "approved_at": transfer.approved_at,
        "shipped_at": transfer.shipped_at,
        "received_at": transfer.received_at,
        "shipping_notes": transfer.shipping_notes,
        "receiving_notes": transfer.receiving_notes,
        "rejection_reason": transfer.rejection_reason
    }


# ==========================================
# 7. LIST TRANSFERS (with pagination)
# ==========================================

@router.get("/", response_model=List[dict])
async def list_transfers(
    transfer_status: Optional[TransferStatus] = None,
    branch_id: Optional[UUID] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    query = {}

    if current_user.role != UserRole.ADMIN:
        user_branch = UUID(str(current_user.branch_id))
        query["$or"] = [
            {"from_branch_id": user_branch},
            {"to_branch_id": user_branch}
        ]

    if transfer_status:
        query["status"] = transfer_status
    if branch_id and current_user.role == UserRole.ADMIN:
        query["$or"] = [
            {"from_branch_id": branch_id},
            {"to_branch_id": branch_id}
        ]

    skip = (page - 1) * limit
    transfers = await StockTransfer.find(query).sort(-StockTransfer.created_at).skip(skip).limit(limit).to_list()  # type: ignore

    result = []
    for transfer in transfers:
        from_branch = await Branch.get(transfer.from_branch_id)
        to_branch = await Branch.get(transfer.to_branch_id)
        total_qty = sum(item["quantity_requested"] for item in transfer.items)

        result.append({
            "transfer_id": str(transfer.id),
            "from_branch": from_branch.name if from_branch else "Unknown",
            "to_branch": to_branch.name if to_branch else "Unknown",
            "status": transfer.status,
            "priority": transfer.priority,
            "items_count": len(transfer.items),
            "total_quantity": total_qty,
            "created_at": transfer.created_at,
            "reason": transfer.reason
        })

    return result