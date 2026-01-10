from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from datetime import datetime
from app.models.purchase_order import PurchaseOrder, POStatus, POItem
from app.models.inventory import Inventory
from app.schemas.procurement import POCreateSchema, ReceiveGoodsSchema
# Assuming you have an auth dependency to get the current user
from app.dependencies.auth import get_current_user 

router = APIRouter(prefix="/procurement", tags=["Procurement"])

# --- ENDPOINT 1: CREATE PO (Purchase Manager) ---
@router.post("/create")
async def create_po(
    data: POCreateSchema, 
    current_user = Depends(get_current_user)
):
    # 1. Role Check
    if current_user.role != "Purchase Manager":
        raise HTTPException(403, "Access Denied: Only Purchase Managers can order.")

    # 2. Process Items & Calculate Total
    po_items = []
    total_amount = 0.0

    for item in data.items:
        line_cost = item.quantity * item.unit_cost
        total_amount += line_cost
        po_items.append(POItem(
            product_id=item.product_id,
            ordered_quantity=item.quantity,
            unit_cost=item.unit_cost,
            total_cost=line_cost
        ))
    
    # 3. Apply Approval Logic (Workflow Step 3)
    # If < $5000 -> Auto Sent. If >= $5000 -> Pending Finance Approval
    if total_amount < 5000:
        status = POStatus.SENT 
        # In a real app, you would trigger the email background task here
    else:
        status = POStatus.PENDING_APPROVAL

    # 4. Save PO
    po = PurchaseOrder(
        supplier_id=data.supplier_id,
        target_branch=data.target_branch,
        total_amount=total_amount,
        status=status,
        items=po_items,
        created_by=current_user.user_id
    )
    await po.save()
    
    return {
        "message": f"PO Created successfully. Status: {status}", 
        "po_id": str(po.id),
        "total": total_amount
    }


# --- ENDPOINT 2: RECEIVE GOODS (Store Staff) ---
@router.post("/{po_id}/receive")
async def receive_goods(
    po_id: str, 
    data: ReceiveGoodsSchema, 
    current_user = Depends(get_current_user)
):
    # 1. Role Check
    if current_user.role not in ["Store Staff"]:
        raise HTTPException(403, "Access Denied: Only Store Staff can receive goods.")

    # 2. Fetch PO & Validate Status
    po = await PurchaseOrder.get(po_id)
    if not po:
        raise HTTPException(404, "PO not found")
        
    if po.status != POStatus.SENT:
        # You can't receive an order that is still pending approval or already received
        raise HTTPException(400, f"Cannot receive goods. PO Status is {po.status}")

    # 3. Update Inventory (The Atomic Transaction)
    for received_item in data.items:
        
        # Find the matching item in the PO to verify
        po_item = next((i for i in po.items if i.product_id == received_item.product_id), None)
        
        if po_item:
            # Update PO record with what actually arrived
            po_item.received_quantity = received_item.received_qty
            
            # --- INVENTORY UPDATE ---
            # Find inventory for THIS product at THIS branch
            inventory = await Inventory.find_one(
                Inventory.product_id == po_item.product_id,
                Inventory.branch_name == po.target_branch
            )
            
            if inventory:
                inventory.quantity += po_item.received_quantity
                await inventory.save()
            else:
                # Create new inventory record if it doesn't exist
                new_inv = Inventory(
                    product_id=po_item.product_id,
                    branch_name=po.target_branch,
                    quantity=po_item.received_quantity
                )
                await new_inv.save()

    # 4. Finalize PO Status
    po.status = POStatus.RECEIVED
    po.receiving_notes = data.notes
    po.received_at = datetime.utcnow()
    await po.save()

    return {"message": "Stock received and Inventory updated successfully"}