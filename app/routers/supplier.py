from fastapi import APIRouter, HTTPException, Depends, status, Request
from typing import List
from uuid import UUID
from datetime import datetime

from app.models.supplier import Supplier
from app.models.purchase_order import PurchaseOrder, POStatus
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierResponse
from app.models.user import User
from app.dependencies.auth import get_product_manager
from app.models.audit_log import AuditAction, AuditModule
from app.utils.audit import log_action
from app.utils.security import extract_ip

router = APIRouter()


@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    request: Request,
    supplier_data: SupplierCreate,
    manager: User = Depends(get_product_manager)
):
    """Product Manager only.** Creates a new supplier. Validates that a supplier with the same name does not already exist. Logs the creation action with details about the new supplier."""
    if await Supplier.find_one(Supplier.name == supplier_data.name):
        raise HTTPException(400, "Supplier with this name already exists")

    new_supplier = Supplier(**supplier_data.dict())
    await new_supplier.save()

    await log_action(
        user=manager,
        action=AuditAction.SUPPLIER_CREATED,
        module=AuditModule.SUPPLIERS,
        description=f"Created supplier: {new_supplier.name}",
        target_id=str(new_supplier.id),
        target_type="supplier",
        metadata={"name": new_supplier.name, "phone": new_supplier.phone},
        ip_address=extract_ip(request)
    )

    return new_supplier

@router.get("/", response_model=dict)
async def get_suppliers(
    page: int = 1,
    limit: int = 50,
    manager: User = Depends(get_product_manager)
):
    """Admin and Purchase Manager only. Returns paginated list of suppliers."""
    total = await Supplier.find_all().count()
    skip = (page - 1) * limit
    suppliers = await Supplier.find_all().skip(skip).limit(limit).to_list()
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "data": suppliers
    }


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    manager: User = Depends(get_product_manager)
):
    

    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier


@router.put("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    update_data: SupplierUpdate,
    request: Request,
    manager: User = Depends(get_product_manager)
):
    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    data_dict = update_data.dict(exclude_unset=True)
    data_dict["updated_at"] = datetime.utcnow()

    old_data = {k: getattr(supplier, k, None) for k in data_dict.keys() if k != "updated_at"}

    await supplier.update({"$set": data_dict})

    await log_action(
        user=manager,
        action=AuditAction.SUPPLIER_UPDATED,
        module=AuditModule.SUPPLIERS,
        description=f"Updated supplier: {supplier.name}",
        target_id=str(supplier_id),
        target_type="supplier",
        metadata={"changes": data_dict, "previous": old_data},
        ip_address=extract_ip(request)
    )

    return await Supplier.get(supplier_id)


@router.delete("/{supplier_id}")
async def delete_supplier(
    supplier_id: UUID,
    request: Request,
    manager: User = Depends(get_product_manager)
):
    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # ✅ FIXED: Block deletion if active POs exist
    active_pos = await PurchaseOrder.find({
        "supplier_id": supplier_id,
        "status": {"$nin": [
            POStatus.RECEIVED,
            POStatus.CANCELLED,
            POStatus.REJECTED
        ]}
    }).count()

    if active_pos > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete supplier. They have {active_pos} active Purchase Order(s). "
                   f"Please complete or cancel them first."
        )

    supplier_name = supplier.name
    await supplier.delete()

    await log_action(
        user=manager,
        action=AuditAction.SUPPLIER_DELETED,
        module=AuditModule.SUPPLIERS,
        description=f"Deleted supplier: {supplier_name}",
        target_id=str(supplier_id),
        target_type="supplier",
        metadata={"name": supplier_name},
        ip_address=extract_ip(request)
    )

    return {"message": f"Supplier '{supplier_name}' deleted successfully"}