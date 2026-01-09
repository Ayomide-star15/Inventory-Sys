from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from uuid import UUID
from datetime import datetime

from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierResponse
from app.models.user import User
from app.dependencies.auth import get_product_manager

router = APIRouter()

# ---------------------------------------------------------
# ➕ CREATE A SUPPLIER
# ---------------------------------------------------------
@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    supplier_data: SupplierCreate, 
    manager: User = Depends(get_product_manager) # Only Managers/Admins
):
    # Check if name already exists
    if await Supplier.find_one(Supplier.name == supplier_data.name):
        raise HTTPException(400, "Supplier with this name already exists")
    
    new_supplier = Supplier(**supplier_data.dict())
    await new_supplier.save()
    return new_supplier

# ---------------------------------------------------------
# 📜 GET ALL SUPPLIERS
# ---------------------------------------------------------
@router.get("/", response_model=List[SupplierResponse])
async def get_suppliers(
    manager: User = Depends(get_product_manager)
):
    return await Supplier.find_all().to_list()

# ---------------------------------------------------------
# 🔍 GET ONE SUPPLIER
# ---------------------------------------------------------
@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID, 
    manager: User = Depends(get_product_manager)
):
    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier

# ---------------------------------------------------------
# ✏️ UPDATE SUPPLIER
# ---------------------------------------------------------
@router.put("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID, 
    update_data: SupplierUpdate, 
    manager: User = Depends(get_product_manager)
):
    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    
    # Update fields
    data_dict = update_data.dict(exclude_unset=True)
    data_dict["updated_at"] = datetime.utcnow()
    
    await supplier.update({"$set": data_dict})
    return await Supplier.get(supplier_id)

# ---------------------------------------------------------
# 🗑️ DELETE SUPPLIER
# ---------------------------------------------------------
@router.delete("/{supplier_id}")
async def delete_supplier(
    supplier_id: UUID, 
    manager: User = Depends(get_product_manager)
):
    supplier = await Supplier.get(supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    
    # Note: Later, we will block this if they have active Purchase Orders!
    await supplier.delete()
    return {"message": "Supplier deleted successfully"}