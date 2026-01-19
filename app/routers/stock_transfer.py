from fastapi import APIRouter, Depends, HTTPException, status, Query
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
    StockTransferCreate,
    StockTransferApprove,
    StockTransferShip,
    StockTransferReceive,
    StockTransferReject,
    StockTransferResponse
)

router = APIRouter(prefix="/stock-transfers", tags=["Stock Transfers"])


# ==========================================
# 1. CREATE TRANSFER REQUEST
# ==========================================

@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_transfer_request(
    transfer_data: StockTransferCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Create a stock transfer request.
    
    Access: Store Managers only
    - Can only transfer FROM their own branch
    - Can transfer TO any other branch
    """
    
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Managers can create transfer requests"
        )
    
    # Verify user can only transfer FROM their branch
    if str(transfer_data.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only transfer FROM your assigned branch"
        )
    
    # Verify branches exist
    from_branch = await Branch.get(transfer_data.from_branch_id)
    to_branch = await Branch.get(transfer_data.to_branch_id)
    
    if not from_branch or not to_branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Prevent transfer to same branch
    if transfer_data.from_branch_id == transfer_data.to_branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot transfer to the same branch"
        )
    
    # Verify stock availability and build items
    items = []
    for item in transfer_data.items:
        # Check product exists
        product = await Product.get(item.product_id)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found"
            )
        
        # Check inventory at source branch
        inventory = await Inventory.find_one({
            "product_id": str(item.product_id),
            "branch_id": str(transfer_data.from_branch_id)
        })
        
        if not inventory or inventory.quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
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
    
    # Create transfer
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
    current_user: User = Depends(get_current_user)
):
    """
    Approve a transfer request.
    
    Access: Purchase Manager of SOURCE branch (where items are coming from)
    - Can approve full quantity or reduce it
    """
    
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Managers can approve transfers"
        )
    
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # Only source branch manager can approve
    if str(transfer.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the source branch manager can approve this transfer"
        )
    
    # Check status
    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve. Transfer status is '{transfer.status}'"
        )
    
    # Update approved quantities
    if approval_data.approved_quantities:
        for approval in approval_data.approved_quantities:
            for item in transfer.items:
                if item["product_id"] == str(approval.product_id):
                    item["quantity_approved"] = approval.quantity
    else:
        # Approve all requested quantities
        for item in transfer.items:
            item["quantity_approved"] = item["quantity_requested"]
    
    # Update transfer
    transfer.status = TransferStatus.APPROVED
    transfer.approved_by = current_user.user_id
    transfer.approved_at = datetime.utcnow()
    if approval_data.notes:
        transfer.notes = approval_data.notes
    
    await transfer.save()
    
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
    current_user: User = Depends(get_current_user)
):
    """
    Mark transfer as shipped and deduct from source inventory.
    
    Access: Store Staff at SOURCE branch
    - Actually packs and sends the items
    - Deducts from source branch inventory
    """
    
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Staff can ship transfers"
        )
    
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # Only source branch staff can ship
    if str(transfer.from_branch_id) != str(current_user.branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only source branch staff can ship this transfer"
        )
    
    # Check status
    if transfer.status != TransferStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot ship. Transfer must be 'Approved'. Current status: '{transfer.status}'"
        )
    
    # Update sent quantities and deduct from inventory
    for ship_item in ship_data.actual_quantities:
        product_id = str(ship_item.product_id)
        quantity_sent = ship_item.quantity
        
        # Update transfer record
        for item in transfer.items:
            if item["product_id"] == product_id:
                item["quantity_sent"] = quantity_sent
        
        # Deduct from source branch inventory
        inventory = await Inventory.find_one({
            "product_id": product_id,
            "branch_id": str(transfer.from_branch_id)
        })
        
        if inventory:
            if inventory.quantity < quantity_sent:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient stock to ship"
                )
            
            inventory.quantity -= quantity_sent
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
    
    # Update transfer
    transfer.status = TransferStatus.IN_TRANSIT
    transfer.shipped_by = current_user.user_id
    transfer.shipped_at = datetime.utcnow()
    transfer.shipping_notes = ship_data.shipping_notes
    await transfer.save()
    
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
    current_user: User = Depends(get_current_user)
):
    """
    Receive transfer and add to destination inventory.
    
    Access: Store Staff at DESTINATION branch
    - Receives and verifies items
    - Adds to destination branch inventory
    """
    
    if current_user.role not in [UserRole.STORE_STAFF, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Staff can receive transfers"
        )
    
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # Only destination branch staff can receive
    if str(transfer.to_branch_id) != str(current_user.branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only destination branch staff can receive this transfer"
        )
    
    # Check status
    if transfer.status != TransferStatus.IN_TRANSIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive. Transfer must be 'In Transit'. Current status: '{transfer.status}'"
        )
    
    # Update received quantities and add to inventory
    for receive_item in receive_data.received_quantities:
        product_id = str(receive_item.product_id)
        quantity_received = receive_item.quantity
        
        # Update transfer record
        for item in transfer.items:
            if item["product_id"] == product_id:
                item["quantity_received"] = quantity_received
        
        # Add to destination branch inventory
        inventory = await Inventory.find_one({
            "product_id": product_id,
            "branch_id": str(transfer.to_branch_id)
        })
        
        if inventory:
            # Update existing
            inventory.quantity += quantity_received
            inventory.updated_at = datetime.utcnow()
            await inventory.save()
        else:
            # Create new inventory record
            product = await Product.get(UUID(product_id))
            new_inventory = Inventory(
                product_id=product_id,
                branch_id=str(transfer.to_branch_id),
                quantity=quantity_received,
                product_name=product.name if product else "Unknown",
                reorder_point=product.low_stock_threshold if product else 10
            )
            await new_inventory.insert()
    
    # Update transfer
    transfer.status = TransferStatus.COMPLETED
    transfer.received_by = current_user.user_id
    transfer.received_at = datetime.utcnow()
    transfer.receiving_notes = receive_data.receiving_notes
    await transfer.save()
    
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
    current_user: User = Depends(get_current_user)
):
    """
    Reject a transfer request.
    
    Access: Store Manager of SOURCE or DESTINATION branch
    """
    
    if current_user.role != UserRole.STORE_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Store Managers can reject transfers"
        )
    
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # Can only reject if source or destination manager
    if str(current_user.branch_id) not in [str(transfer.from_branch_id), str(transfer.to_branch_id)]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Can only reject if pending
    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only reject pending transfers"
        )
    
    transfer.status = TransferStatus.REJECTED
    transfer.rejection_reason = reject_data.rejection_reason
    await transfer.save()
    
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
    """
    Get detailed information about a transfer.
    
    Access:
    - Admin: Any transfer
    - Store Manager/Staff: Only transfers involving their branch
    """
    
    transfer = await StockTransfer.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # Access control
    if current_user.role != UserRole.ADMIN:
        user_branch = str(current_user.branch_id)
        if user_branch not in [str(transfer.from_branch_id), str(transfer.to_branch_id)]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view transfers involving your branch"
            )
    
    # Get branch details
    from_branch = await Branch.get(transfer.from_branch_id)
    to_branch = await Branch.get(transfer.to_branch_id)
    
    # Get user details
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
# 7. LIST TRANSFERS
# ==========================================

@router.get("/", response_model=List[dict])
async def list_transfers(
    status: Optional[TransferStatus] = None,
    branch_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user)
):
    """
    List stock transfers.
    
    Access:
    - Admin: All transfers
    - Store Manager/Staff: Only transfers involving their branch
    """
    
    query = {}
    
    # Role-based filtering
    if current_user.role != UserRole.ADMIN:
        # Only see transfers involving their branch
        user_branch = UUID(str(current_user.branch_id))
        query["$or"] = [
            {"from_branch_id": user_branch},
            {"to_branch_id": user_branch}
        ]
    
    # Apply filters
    if status:
        query["status"] = status
    if branch_id and current_user.role == UserRole.ADMIN:
        query["$or"] = [
            {"from_branch_id": branch_id},
            {"to_branch_id": branch_id}
        ]
    
    transfers = await StockTransfer.find(query).sort(-StockTransfer.created_at).to_list()
    
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


# ==========================================
# 8. MY BRANCH TRANSFERS
# ==========================================

@router.get("/my-branch/all", response_model=dict)
async def get_my_branch_transfers(
    current_user: User = Depends(get_current_user)
):
    """
    Get all transfers for current user's branch.
    Separated into: outgoing, incoming, pending approval, etc.
    """
    
    if current_user.role not in [UserRole.STORE_MANAGER, UserRole.STORE_STAFF]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    user_branch = UUID(str(current_user.branch_id))
    
    # Outgoing (from my branch)
    outgoing = await StockTransfer.find(
        StockTransfer.from_branch_id == user_branch
    ).to_list()
    
    # Incoming (to my branch)
    incoming = await StockTransfer.find(
        StockTransfer.to_branch_id == user_branch
    ).to_list()
    
    # Pending my approval (I'm source branch manager)
    if current_user.role == UserRole.STORE_MANAGER:
        pending_approval = await StockTransfer.find(
            StockTransfer.from_branch_id == user_branch,
            StockTransfer.status == TransferStatus.PENDING
        ).count()
    else:
        pending_approval = 0
    
    # Awaiting receiving (I'm destination)
    awaiting_receive = await StockTransfer.find(
        StockTransfer.to_branch_id == user_branch,
        StockTransfer.status == TransferStatus.IN_TRANSIT
    ).count()
    
    return {
        "outgoing_count": len(outgoing),
        "incoming_count": len(incoming),
        "pending_approval": pending_approval,
        "awaiting_receive": awaiting_receive,
        "outgoing": [
            {
                "transfer_id": str(t.id),
                "to_branch": (await Branch.get(t.to_branch_id)).name,
                "status": t.status,
                "created_at": t.created_at
            }
            for t in outgoing[:5]  # Last 5
        ],
        "incoming": [
            {
                "transfer_id": str(t.id),
                "from_branch": (await Branch.get(t.from_branch_id)).name,
                "status": t.status,
                "created_at": t.created_at
            }
            for t in incoming[:5]  # Last 5
        ]
    }